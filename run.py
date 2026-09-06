#!/usr/bin/env python3
"""SAP Config Automation CLI (Plan / Simulate modes; Apply = mock or real macOS GUI).

Usage:
  python run.py plan    --vars templates/example_customer_vars.yaml \
                        --steps templates/example_config_steps.yaml
  python run.py apply   --run <run_id> [--approve cc_jp01,assign_cc_company] [--approve-all]
  python run.py apply   --run <run_id> --adapter sap_gui_mac --approve-all   # REAL SAP GUI (macOS)
  python run.py report  --run <run_id>
  python run.py demo    # end-to-end: plan + gated apply with a fault-injected retry

Safety: default adapter is mock. The real macOS adapter (sap_gui_mac) drives the
actual SAP GUI for Java on this machine and needs explicit consent
(SAPCFG_ALLOW_REAL_SAP=1 or repo-root .sapcfg_allow_real_sap) + Accessibility.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sapcfg.gui.mock import MockConfig  # noqa: E402
from sapcfg.load import load_bundle  # noqa: E402
from sapcfg.orchestrator import Orchestrator  # noqa: E402
from sapcfg.reporter import report_md  # noqa: E402
from sapcfg.store import RUNS_DIR, RunStore  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _load(args):
    vp = Path(args.vars)
    sp = Path(args.steps)
    if not vp.exists() or not sp.exists():
        sys.exit(f"template files not found:\n  {vp}\n  {sp}")
    print(f"loading bundle: {vp.name} + {sp.name}")
    return load_bundle(vp, sp)


def cmd_plan(args):
    bundle = _load(args)
    orch = Orchestrator(adapter_name=args.adapter)
    store = orch.plan_mode(bundle)
    print(f"plan written: runs/{store.run_id}/plan.json")
    print("\n" + _pretty_plan(store))
    print("\n[plan mode complete - nothing was modified in SAP (mock read-only)]")


def cmd_apply(args):
    orch = Orchestrator(adapter_name=args.adapter)
    approvals = [x.strip() for x in (args.approve or "").split(",") if x.strip()]
    store = orch.apply_mode(args.run, approvals=approvals, approve_all=args.approve_all)
    print(f"apply finished: runs/{store.run_id}")
    print("step states: " + ", ".join(f"{s['item_id']}={s['state']}" for s in store.list_steps()))
    missing = store.pending_approvals()
    if missing:
        print(f"\nhuman queue (pending approval): {', '.join(missing)}")
        print(f"-> approve with: python run.py apply --run {args.run} "
              f"--approve {','.join(missing)}")


def cmd_report(args):
    rd = RUNS_DIR / args.run
    if not rd.exists():
        sys.exit(f"run not found: runs/{args.run}")
    store = RunStore(run_id=args.run)
    print(report_md(store, rd))
    store.close()


def cmd_demo(args):
    """End-to-end demo on mock data: plan, then gated apply with approvals."""
    bundle = load_bundle(TEMPLATES / "example_customer_vars.yaml",
                         TEMPLATES / "example_config_steps.yaml")
    # inject a transient table-lock fault on the company-code step to show bounded retry
    cfg = MockConfig()
    cfg.faults = {"company_code_global_params": dict(
        count=1, message="Table E071K is locked by user T-1 (retryable)")}
    orch = Orchestrator(adapter_name="mock", config=cfg)
    store = orch.plan_mode(bundle)
    rid = store.run_id
    print("\n--- PLAN ---")
    print(_pretty_plan(store))
    print("\nApplying with approval for: assign_cc_company (template requires human_approval)...\n")
    orch2 = Orchestrator(adapter_name="mock", config=cfg)
    store2 = orch2.apply_mode(rid, approvals=["assign_cc_company"])
    print("--- RESULT ---")
    for s in store2.list_steps():
        print(f"  {s['seq']}. {s['item_id']:<18} {s['state']:<8} attempts={s['attempts']} "
              f"verified={s['verified']}")
    rd = RUNS_DIR / rid
    rd.joinpath("report.md").write_text(report_md(store2, rd), encoding="utf-8")
    print(f"\nreport: runs/{rid}/report.md   evidence: {len(store2.evidence_files())} svg screenshots")
    store.close(); store2.close()


def _pretty_plan(store: RunStore) -> str:
    import json
    pj = json.loads((RUNS_DIR / store.run_id / "plan.json").read_text(encoding="utf-8"))
    out = []
    for i in pj["items"]:
        mark = {"CREATE": "+", "UPDATE": "~", "SKIP": "=", "CONFLICT": "!", "BLOCKED": "X", "ERROR": "E"}[i["status"]]
        out.append(f"[{mark}] #{i['seq']:>2} {i['item_id']:<18} {i['status']:<9} {i['reason']}")
        if i["needs_approval"]:
            out[-1] += "  (requires approval)"
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="SAP Config Automation CLI")
    ap.add_argument("--adapter", default="mock",
                    choices=["mock", "sap_gui_mac"],
                    help="mock = in-process simulation (default); "
                         "sap_gui_mac = real SAP GUI for Java on this macOS "
                         "machine (needs SAPCFG_ALLOW_REAL_SAP=1 + Accessibility)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="Plan mode: validate + dependency diff (no writes)")
    p.add_argument("--vars", default=str(TEMPLATES / "example_customer_vars.yaml"))
    p.add_argument("--steps", default=str(TEMPLATES / "example_config_steps.yaml"))
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("apply", help="Apply mode on mock SAP (gated)")
    p.add_argument("--run", required=True)
    p.add_argument("--approve", default="", help="comma list of item ids to approve")
    p.add_argument("--approve-all", action="store_true")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("report", help="Print Markdown report of a run")
    p.add_argument("--run", required=True)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("demo", help="End-to-end demo (plan + gated apply, mock)")
    p.set_defaults(fn=cmd_demo)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
