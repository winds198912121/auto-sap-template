#!/usr/bin/env python3
"""SAP Config Automation - local visual console (mock SAP only).

Run:  python3 webui/server.py [--port 8912]
Open: http://localhost:8912

Everything executes against the built-in Mock SAP GUI inside this process.
Real-system connection is impossible from this server (win_gui raises on macOS).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sapcfg import VERSION  # noqa: E402
from sapcfg.gui.mock import MockConfig  # noqa: E402
from sapcfg.load import SchemaError, load_bundle  # noqa: E402
from sapcfg.model import PlanStatus  # noqa: E402
from sapcfg.run import apply as run_apply  # noqa: E402
from sapcfg.run import plan as run_plan  # noqa: E402
from sapcfg.store import RUNS_DIR  # noqa: E402

TEMPLATES = ROOT / "templates"
EVIDENCE = ROOT / "runs"

_lock = threading.Lock()
# shared mutable demo state for this server process
STATE = {"config": MockConfig(), "scenario": "clean"}


def _list_runs() -> list[dict]:
    out = []
    for d in sorted(RUNS_DIR.glob("*/"), reverse=True):
        pj = d / "plan.json"
        if not pj.exists():
            continue
        try:
            plan = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            continue
        steps = []
        db = d / "run.sqlite"
        if db.exists():
            import sqlite3
            con = sqlite3.connect(db)
            try:
                for r in con.execute("SELECT item_id,state,verified FROM steps"):
                    steps.append(dict(item=r[0], state=r[1], verified=r[2]))
            except Exception:
                pass
            con.close()
        out.append(dict(run_id=d.name, template_id=plan.get("template_id"),
                        customer=plan.get("customer", ""),
                        created=plan.get("created_at", ""),
                        summary=plan.get("items") and _sum(plan["items"]) or {},
                        steps=steps))
    return out


def _sum(items: list[dict]) -> dict:
    out = {}
    for i in items:
        out[i["status"]] = out.get(i["status"], 0) + 1
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _read_json(self) -> dict:
        ln = int(self.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        return json.loads(self.rfile.read(ln))

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/":
            return self._send_file(ROOT / "webui" / "index.html", "text/html")
        if p == "/api/meta":
            return self._json(dict(
                version=VERSION, adapter="mock", mock=True,
                real_sap_possible=False,
                scenario=STATE["scenario"],
                mode="PLAN_ONLY-until-approved",
                templates=sorted(x.name for x in TEMPLATES.glob("*.yaml")),
                schemas=[x.name for x in (ROOT / "schema").glob("*.json")],
                note="Mock SAP GUI in-process. Real SAP GUI Scripting driver is "
                     "Windows-only and requires explicit env approval.",
            ))
        if p == "/api/runs":
            return self._json(_list_runs())
        if p.startswith("/api/runs/") and "/events" in p:
            run = p.split("/")[3]
            after = int(self.path.split("after=")[-1]) if "after=" in self.path else 0
            return self._json(_events(run, after))
        if p.startswith("/api/runs/") and p.endswith("/plan"):
            run = p.split("/")[3]
            return self._send_file(RUNS_DIR / run / "plan.json", "application/json")
        if p == "/api/kb":
            from sapcfg.error_kb import ErrorKB
            kb = ErrorKB()
            return self._json(dict(pending=kb.pending(), stats=kb.rule_summary()))
        if p.startswith("/api/runs/") and p.endswith("/report"):
            run = p.split("/")[3]
            from sapcfg.reporter import report_md
            from sapcfg.store import RunStore
            st = RunStore(run_id=run)
            try:
                txt = report_md(st, RUNS_DIR / run)
            finally:
                st.close()
            return self._json(dict(markdown=txt))
        if p.startswith("/evidence/"):
            rel = p[len("/evidence/"):]
            f = EVIDENCE / rel
            if f.exists() and f.suffix in (".svg", ".png", ".md", ".json"):
                ctype = {"svg": "image/svg+xml", "png": "image/png",
                         "md": "text/markdown", "json": "application/json"}[f.suffix]
                return self._send_file(f, ctype)
            return self._json(dict(error="not found"), 404)
        return self._json(dict(error="no such endpoint"), 404)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        try:
            body = self._read_json()
            p = self.path.split("?", 1)[0]
            if p == "/api/scenario":
                self._set_scenario(body.get("name", "clean"))
                return self._json(dict(ok=True, scenario=STATE["scenario"]))
            if p == "/api/validate-template":
                vs = body.get("vars", "example_customer_vars.yaml")
                sf = body.get("steps", "example_config_steps.yaml")
                try:
                    st = self._structure(body)
                except SchemaError as e:
                    # 防呆：内容级诊断（选反/同一文件）＋スキーマ原文
                    return self._json(dict(error=str(e), diagnosis=self._diagnose_pair(vs, sf)), 400)
                return self._json(dict(structure=st, diagnosis=self._diagnose_pair(vs, sf)), 200)
            if p == "/api/plan":
                with _lock:
                    run = self._plan(body)
                return self._json(dict(run_id=run), 200)
            if p == "/api/apply":
                with _lock:
                    out = self._apply(body)
                return self._json(out, 200)
            if p == "/api/kill":
                run = body.get("run", "")
                d = RUNS_DIR / run
                if not d.exists():
                    return self._json(dict(error="unknown run"), 404)
                (d / "KILL").write_text("kill switch engaged from console\n")
                return self._json(dict(ok=True))
            return self._json(dict(error="no such endpoint"), 404)
        except SchemaError as e:
            return self._json(dict(error=str(e)), 400)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._json(dict(error=f"{type(e).__name__}: {e}"), 500)

    # ------------------------------------------------------------------ logic
    def _send_file(self, path: Path, ctype: str):
        if not path.exists():
            return self._json(dict(error="not found"), 404)
        self._send(200, path.read_bytes(), ctype)

    def _resolve_template(self, name: str) -> Path:
        f = TEMPLATES / name
        if not f.exists() or not str(f.resolve()).startswith(str(TEMPLATES.resolve())):
            raise ValueError(f"template not allowed: {name}")
        return f

    def _top_keys(self, name: str) -> set:
        """テンプレートYAMLのトップレベルキーを読む（診断用・読み取りのみ）"""
        try:
            f = self._resolve_template(name)
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            return set(d.keys()) if isinstance(d, dict) else set()
        except Exception:
            return set()

    def _diagnose_pair(self, vars_name: str, steps_name: str) -> dict:
        """ファイルを中身で判別：vars欄にsteps系・steps欄にvars系が来ていないか"""
        vk = self._top_keys(vars_name)
        sk = self._top_keys(steps_name)
        return dict(
            same_file=(vars_name == steps_name),
            vars_looks_like_steps=("config_items" in vk and "variables" not in vk),
            steps_looks_like_vars=("config_items" not in sk
                                   and ("variables" in sk or "customer" in sk)),
            file_names=dict(vars=vars_name, steps=steps_name),
        )

    def _structure(self, body: dict) -> dict:
        vars_f = self._resolve_template(body.get("vars", "example_customer_vars.yaml"))
        steps_f = self._resolve_template(body.get("steps", "example_config_steps.yaml"))
        b = load_bundle(vars_f, steps_f)
        t = b.target
        return dict(
            template_id=b.template_id, template_version=b.template_version,
            customer=b.customer,
            target=dict(environment=t.environment, sap_system=t.sap_system,
                        client=t.client, language=t.language),
            variables=b.variables,
            validation=dict(schema="customer_vars.schema.json + steps.schema.json",
                            status="PASS", adapter="mock",
                            note="structure parsed; variables resolve at plan time"),
            items=[dict(id=it.id, kind=it.kind, title=it.title,
                        transaction=it.transaction, depends_on=it.depends_on,
                        on_existing=it.on_existing, human_approval=it.human_approval,
                        params=it.params) for it in b.items])

    def _plan(self, body: dict) -> str:
        vars_f = self._resolve_template(body.get("vars", "example_customer_vars.yaml"))
        steps_f = self._resolve_template(body.get("steps", "example_config_steps.yaml"))
        store = run_plan(vars_f, steps_f, config=STATE["config"])
        return store.run_id

    def _apply(self, body: dict) -> dict:
        run_id = body.get("run")
        if not run_id or not (RUNS_DIR / run_id / "plan.json").exists():
            return dict(error=f"unknown run: {run_id}")
        # re-approval token must be explicit (UI sends it when the box is ticked)
        if not body.get("consent"):
            return dict(error="Apply refused: consent flag missing (mock simulation only)")
        approvals = body.get("approvals", [])
        approve_all = bool(body.get("approve_all"))
        store = run_apply(run_id, approvals=approvals, approve_all=approve_all,
                          config=STATE["config"])
        steps = store.list_steps()
        return dict(run_id=run_id, steps=steps,
                    stats=store.summary_stats(),
                    evidence=store.evidence_files())

    def _set_scenario(self, name: str):
        cfg = MockConfig()
        if name == "clean":
            pass
        elif name == "conflict":
            # company code already exists with different currency -> CONFLICT gate demo
            cfg.upsert("company_code", dict(company_code="JP01", company_name="Old Name",
                                            currency="USD", chart_of_accounts="ICOA",
                                            fiscal_year_variant="K4", country="US",
                                            city="Dallas", language="EN"), "company_code")
            cfg.upsert("coa", dict(code="ICOA", name="International COA"), "code")
            cfg.upsert("fiscal_variant", dict(code="K4", name="Calendar year",
                                              n_periods="16"), "code")
        elif name == "fault":
            cfg.faults = dict(company_code_global_params=dict(
                count=1, message="Table E071K is locked by user T-1 (retryable)"))
        elif name == "permission":
            cfg.faults = dict(company_code_global_params=dict(
                count=5, message="You are not authorized to run transaction OBY6 (SU53)"))
        elif name == "unknown":
            cfg.faults = dict(company_code_global_params=dict(
                count=1, message="Internal error code F0A_17 (not in KB yet)"))
        elif name == "partial":
            cfg.upsert("coa", dict(code="YCOA", name="JP Group Chart of Accounts"), "code")
            cfg.upsert("fiscal_variant", dict(code="K4", name="Calendar year, 4 special periods",
                                              n_periods="16"), "code")
        else:
            name = "clean"
        STATE["config"] = cfg
        STATE["scenario"] = name


def _events(run: str, after: int) -> dict:
    f = RUNS_DIR / run / "events.jsonl"
    if not f.exists():
        return dict(events=[], last=after)
    events = []
    last = after
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e["seq"] <= after:
            continue
        last = e["seq"]
        events.append(e)
    return dict(events=events, last=last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8912)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), H)
    print(f"SAP Config Automation console  (mock SAP, v{VERSION})")
    print(f"  open http://{args.host}:{args.port}")
    print("  PLAN-ONLY until you tick consent + per-item approvals; apply = mock simulation")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
