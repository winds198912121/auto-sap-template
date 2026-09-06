from __future__ import annotations

import json
import os
import re
from pathlib import Path

import jsonschema
import yaml

from .model import ConfigItem, Target, TemplateBundle, PlanStatus, Plan, PlanItem

ROOT = Path(__file__).resolve().parent.parent
VARS_SCHEMA_PATH = ROOT / "schema" / "customer_vars.schema.json"
STEPS_SCHEMA_PATH = ROOT / "schema" / "steps.schema.json"

_CRED_PATTERN = re.compile(r"(?i)pass(word|wd)?|secret|token|pwd|sso|api[_-]?key|credential|password")
_URI_FORBIDDEN = re.compile(r"(?i)(insert\s+into|update\s+\w+\s+set|delete\s+from)\b")


def load_schema(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: template root must be a mapping")
    return data


# ------------------------------------------------------------------ template bundle
def load_bundle(vars_file: Path, steps_file: Path) -> TemplateBundle:
    """Load + schema-validate + merge customer variables with config steps."""
    vs = _read_yaml(vars_file)
    st = _read_yaml(steps_file)

    for name, path_, data in (("customer variables", VARS_SCHEMA_PATH, vs),
                               ("config steps", STEPS_SCHEMA_PATH, st)):
        errors = sorted(jsonschema.Draft7Validator(load_schema(path_)).iter_errors(data),
                        key=lambda e: list(e.path))
        if errors:
            raise SchemaError(_fmt_errors(name, errors))

    _semantic_checks(vs, st, vars_file.name, steps_file.name)

    target = Target(**{k: st["target"][k] for k in
                       ("environment", "sap_system", "client", "language")
                       if k in st["target"]})
    items: list[ConfigItem] = []
    for it in st["config_items"]:
        items.append(ConfigItem(
            id=it["id"], kind=it["kind"], title=it["title"],
            params=dict(it["params"]),
            depends_on=list(it.get("depends_on", [])),
            transaction=it.get("transaction", ""),
            on_existing=it.get("on_existing", "skip_if_match"),
            human_approval=bool(it.get("human_approval", False)),
            timeout_s=it.get("timeout_s", 120),
            retry_max=it.get("retry", {}).get("max", 2),
            retry_backoff_s=it.get("retry", {}).get("backoff_s", 2.0),
            retry_whitelist=it.get("retry", {}).get("whitelist", []),
            verify_scope=it.get("verify", {}).get("scope"),
            verify_ignore=it.get("verify", {}).get("ignore", []),
            verify_extra=it.get("verify", {}).get("extra", {}),
        ))
    return TemplateBundle(
        template_id=st["template_id"], template_version=st["template_version"],
        customer=vs.get("customer", ""), target=target,
        variables=vs.get("variables", {}), items=items,
        source_files=[vars_file.name, steps_file.name],
        title=st.get("template_title", ""), notes=st.get("template_notes", ""),
    )


def _semantic_checks(vs: dict, st: dict, vars_name: str, steps_name: str):
    problems: list[str] = []

    if vs.get("template_id") != st.get("template_id"):
        problems.append(f"template_id mismatch: {vars_name}={vs.get('template_id')!r} "
                        f"vs {steps_name}={st.get('template_id')!r}")
    vt, stt = vs.get("target", {}), st.get("target", {})
    if (vt.get("environment"), vt.get("client")) != (stt.get("environment"), stt.get("client")):
        problems.append("target (environment/client) mismatch between variable file and steps file")

    # credentials denylist in variables (schema propertyNames covers keys; values checked too)
    for k, v in (vs.get("variables") or {}).items():
        if _CRED_PATTERN.search(str(k)):
            problems.append(f"variable name forbidden by policy: {k!r}")
        if isinstance(v, str) and _CRED_PATTERN.search(v) and len(v) >= 6:
            problems.append(f"variable {k!r} looks like a credential (policy: keep secrets out of templates)")

    # no raw SQL / DB hints in params, no control-ID-ish keys
    for it in st["config_items"]:
        for k, v in it.get("params", {}).items():
            if isinstance(v, str) and _URI_FORBIDDEN.search(v):
                problems.append(f"{it['id']}.params.{k}: direct DB SQL is not allowed in templates")
            if re.match(r"(?i)^(wnd|gui|sapgui|cntl).*", k):
                problems.append(f"{it['id']}.params.{k}: raw GUI control IDs must live in step handlers, not templates")
        # unknown dependency targets
        ids = {x["id"] for x in st["config_items"]}
        for dep in it.get("depends_on", []):
            if dep not in ids:
                problems.append(f"{it['id']}.depends_on: unknown item {dep!r}")
        # self dependency
        if it["id"] in it.get("depends_on", []):
            problems.append(f"{it['id']}.depends_on: self reference")
        # variable placeholders syntax
        for k, v in it.get("params", {}).items():
            if isinstance(v, str):
                for m in re.finditer(r"\{\{\s*([\w]+)\s*\}\}", v):
                    if m.group(1) not in (vs.get("variables") or {}):
                        problems.append(f"{it['id']}.params.{k}: undefined variable {m.group(1)!r}")

    if problems:
        raise SchemaError("semantic checks failed:\n  - " + "\n  - ".join(problems))


def _fmt_errors(section: str, errors: list) -> str:
    lines = [f"{section} schema validation failed:"]
    for e in errors:
        where = "/".join(str(p) for p in e.path) or "<root>"
        lines.append(f"  - {where}: {e.message}")
    return "\n".join(lines)


# ------------------------------------------------------------------ variable resolution
_VAR = re.compile(r"\{\{\s*([\w]+)\s*\}\}")


def resolve_params(item: ConfigItem, variables: dict) -> tuple[dict, list[str]]:
    """Substitute {{var}} in scalar string params. Unresolved vars are reported."""
    unresolved: list[str] = []

    def sub(v):
        if isinstance(v, str):
            def rep(m):
                name = m.group(1)
                if name not in variables:
                    return m.group(0)          # leave marker, collect below
                val = variables[name]
                return str(val)
            out = _VAR.sub(rep, v)
            for m in _VAR.finditer(v):
                if m.group(1) not in variables and m.group(1) not in unresolved:
                    unresolved.append(m.group(1))
            return out
        if isinstance(v, list):
            return [sub(x) for x in v]
        return v

    resolved = {k: sub(v) for k, v in item.params.items()}
    leftover = [m for m in re.findall(r"\{\{\s*\w+\s*\}\}", json.dumps(resolved, ensure_ascii=False))]
    if leftover:
        unresolved.extend([x.strip("{} ") for x in leftover])
    return resolved, sorted(set(unresolved))


class SchemaError(Exception):
    """Template failed schema or semantic validation (nothing executed)."""


def parse_plan_doc(data: dict, warnings: list[str] | None = None) -> Plan:
    """Deserialize a saved plan.json back into a Plan (for the console/report)."""
    tgt = data["target"]
    target = Target(environment=tgt.get("environment", "DEV"),
                    sap_system=tgt.get("sap_system", ""),
                    client=tgt.get("client", "000"),
                    language=tgt.get("language", "EN"))
    plan = Plan(run_id=data["run_id"], created_at=data["created_at"],
                template_id=data["template_id"], template_version=data["template_version"],
                customer=data.get("customer", ""), target=target,
                warnings=warnings or [])
    for it in data["items"]:
        plan.items.append(PlanItem(
            seq=it["seq"], item_id=it["item_id"], kind=it["kind"], title=it["title"],
            status=PlanStatus(it["status"]), reason=it.get("reason", ""),
            current=it.get("current", {}), desired=it.get("desired", {}),
            needs_approval=bool(it.get("needs_approval", False)),
            depends_on=it.get("depends_on", []), transaction=it.get("transaction", "")))
    return plan
