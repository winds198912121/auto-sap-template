"""Read-back verification: compare actual SAP state with desired state.

Design principle '可验证': 'saved' is NOT success -- orchestrator re-reads the
configuration store (GUI read-back / report) and compares with expectations.
"""
from __future__ import annotations

import re
from typing import Any

from .model import ConfigItem


def _norm(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().upper()


def match_op(op: str, actual: Any, expected: Any) -> tuple[bool, str]:
    a, e = _norm(actual), _norm(expected)
    if op == "eq":
        return a == e, f"'{a}' == '{e}'"
    if op == "neq":
        return a != e, f"'{a}' != '{e}'"
    if op == "contains":
        return e in a, f"'{a}' contains '{e}'"
    if op == "in":
        lst = [_norm(x) for x in (expected if isinstance(expected, list) else [expected])]
        return a in lst, f"'{a}' in {lst}"
    if op == "regex":
        return bool(re.search(str(expected), a, re.I)), f"'{a}' ~ /{expected}/"
    return False, f"unknown op {op}"


def build_expectations(item: ConfigItem, handler_columns: dict[str, str]) -> list[dict]:
    """Expectation list: {param, column, op, expected} for scalar params.

    scope: only these param keys (default = all scalar params).
    ignore: exclude these param keys.
    extra: additional expectations not backed by a param.
    """
    exps: list[dict] = []
    p = item.resolved_params
    scope = item.verify_scope if item.verify_scope else list(p.keys())
    for key in scope:
        if key in item.verify_ignore or key not in handler_columns:
            continue
        if key not in p:
            continue
        if not isinstance(p[key], (str, int, float, bool)):
            continue
        exps.append(dict(param=key, column=handler_columns[key],
                         op="eq", expected=p[key]))
    for fname, spec in item.verify_extra.items():
        exps.append(dict(param=fname, column=handler_columns.get(fname, fname),
                         op=spec.get("op", "eq"), expected=spec.get("expected")))
    return exps


def verify_readback(actual: dict | None, expectations: list[dict]) -> tuple[bool, list[dict]]:
    """Compare stored entry with expectations; returns (ok, per-check results)."""
    if actual is None:
        return False, [dict(ok=False, column="<entry>", op="exists",
                            actual="<missing>", expected="<any>",
                            detail="entry does not exist in SAP (read-back)")]
    results = []
    for e in expectations:
        ok, expr = match_op(e["op"], actual.get(e["column"]), e["expected"])
        results.append(dict(ok=ok, column=e["column"], op=e["op"],
                            actual=actual.get(e["column"]), expected=e["expected"],
                            detail=expr))
    return all(r["ok"] for r in results), results
