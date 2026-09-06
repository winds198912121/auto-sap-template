# SAP GUI Configuration Automation (Phase 1 · Plan + Mock)

> SAP Configuration Automation / Configuration as Code — implements the design in
> `SAP_GUI_Configuration_Automation_Design.md` §1–§5 as a runnable pipeline.
> **Phase 1 runs exclusively against an in-process Mock SAP GUI.** It never connects
> to a real system, never writes to a real SAP database, and never enters Apply mode
> without explicit human approval.

```
Documents/SAP/sap-config-automation/
├── schema/                     # JSON Schema (template structure)
│   ├── customer_vars.schema.json   # §4.1 customer variables file
│   └── steps.schema.json           # §4.2 configuration steps file
├── templates/                  # example business templates (YAML)
│   ├── example_customer_vars.yaml
│   └── example_config_steps.yaml   # OB13 / OB29 / OBY6 / OX02 / OX10
├── sapcfg/                     # core library
│   ├── load.py                     # parse + schema + semantic checks + {{var}} resolve
│   ├── planner.py                  # dependency DAG → topo order → CREATE/UPDATE/SKIP/
│   │                               #   CONFLICT/BLOCKED/ERROR diff (Plan mode, read-only)
│   ├── orchestrator.py             # gated Apply state machine: approval gate → execute
│   │                               #   → §6 classification → bounded retry → read-back
│   │                               #   verify → human queue (§8 target re-check/kill)
│   ├── errclass.py                 # §6 error classifier (msg key → tcode+text → text)
│   ├── error_kb.py                 # §7.2 Error Knowledge Base: stats + review queue
│   ├── verify.py                   # read-back comparison engine (eq/neq/contains/in/regex)
│   ├── store.py                    # run folder + SQLite step state + JSONL events + SVG
│   │                               #   screenshot evidence
│   ├── reporter.py                 # Markdown execution report
│   ├── gui/                        # SAP adapter channel (uniform protocol)
│   │   ├── base.py                     # SapGuiAdapter protocol
│   │   ├── mock.py                     # Mock SAP GUI driver + config store + fault inject
│   │   └── win_gui.py                  # real SAP GUI Scripting driver (Windows only,
│   │                                   #   guarded: needs SAPCFG_ALLOW_REAL_SAP=1)
│   └── steps/fi_basic.py          # step skills: per-tcode screen catalog + handlers
│                                   #   + planner tables + verify columns (design §4.3)
├── error_rules/default_rules.yaml  # versioned, approved error whitelist (design §6.2)
├── error_kb/                       # runtime KB history/stats + pending review queue
├── webui/                       # visual console (localhost:8912) — mock SAP only
├── run.py                       # CLI: plan / apply / report / demo
├── tests/test_pipeline.py       # 26 mock-data tests (unittest)
└── runs/                        # per-run: plan.json, events.jsonl, run.sqlite,
                                 #   evidence/*.svg (screenshots), report.md
```

## Safety posture (enforced in code)

| rule | where |
|---|---|
| No real-SAP adapter importable on this machine | `sapcfg/gui/win_gui.py` raises unless Windows + `SAPCFG_ALLOW_REAL_SAP=1` |
| Plan mode is read-only | `planner.build_plan` takes a read-only `SapStateView` |
| Apply runs only on the mock adapter here | CLI `--adapter mock` (only choice); console is in-process mock |
| No direct SAP DB writes anywhere | code base has no INSERT/UPDATE SQL against SAP tables |
| Apply needs an existing plan + per-item approval | gate in `orchestrator._run_item`; overwrite/`human_approval` items → human queue |
| Credentials / SQL / GUI control-IDs forbidden in templates | schema + semantic checks (`load._semantic_checks`) |

## Quickstart

```bash
cd ~/Documents/SAP/sap-config-automation
uv sync

# 1) tests (mock data, offline)
uv run python -m unittest discover -s tests -v

# 2) CLI: Plan mode (diff, no writes)          → runs/<run>/plan.json
uv run python run.py plan

# 3) CLI: gated Apply on mock (needs approval for assign_cc_company)
uv run python run.py apply --run <run_id> --approve assign_cc_company

# 4) CLI: full demo incl. transient-lock retry + report
uv run python run.py demo

# 5) Visual console
uv run python webui/server.py --port 8912     # open http://localhost:8912
```

Console flow: **Overview** → scenario → **Template & Schema** (Load & validate)
→ **Plan** (Generate Plan) → tick approvals + consent → **Run Apply (MOCK)**
(live mock SAP GUI, event log, verify results, SVG screenshots) → **Report**.

## Design-doc mapping

| design doc | implementation |
|---|---|
| §1 goals 1–7 | parse+validate (`load`) · deps (`planner`) · ordered GUI ops (`orchestrator`+`gui/mock`) · bounded retry (`_run_item`) · read-back verify (`verify`) · input/ops/screens/messages/retry/results logging (`store` events) · report + human queue (`reporter`) |
| §2 幂等/可验证/有限纠错/可恢复/可审计 | SKIP-on-match · post-save read-back compare · whitelisted transient errors only · per-item state in SQLite + resume skips SUCCESS · full evidence trail |
| §3 components | Template/Schema/Planner/Orchestrator/Adapter/Verification/State Store/Evidence/Reporter all present |
| §4.1–4.2 format | two YAML files validated against the two JSON Schemas |
| §4.3 (no creds/SQL/control-IDs in templates) | schema + semantic checks |
| §5 Plan mode | `run.py plan`, console Plan tab, `plan.json` diff with reasons |
| §5 Apply state machine | approval gate → RUNNING/RETRYING → SUCCESS(+verified) / FAILED / MANUAL / BLOCKED; CONFLICT needs explicit override |
| §6 error classification | `errclass.py` + `error_rules/default_rules.yaml` (whitelist). Priority msg class+number → tcode+text → text → UNKNOWN. LOCK/TRANSIENT/NAVIGATION auto-retry ≤2; PERMISSION/INPUT/BUSINESS_CONFLICT/UNKNOWN never retry → human queue; ALREADY_EXISTS → verify/skip |
| §7.1 per-execution log | every run records actor-less tech session, target, step params, status messages w/ classification, before/after values, retries, screenshots, outcome (`events.jsonl` + `record` audit event + SVG evidence) |
| §7.2 Error KB | rule usage stats incl. first/last_seen + success_rate; unknown errors auto-proposed to `error_kb/pending.json` with auto_fix_allowed=False, High risk, awaiting consultant approval |
| §7.3 report | Markdown report with plan summary, step results, error-classification table, PoC metrics (read-back coverage, first-try success, idempotence), evidence list |
| §8 target triple-check | adapter system/client re-checked before every step against the plan target; mismatch aborts the run (ABORTED) |
| §8 kill switch | per-run `KILL` marker file, project `.kill_switch`, or `SAPCFG_KILL_SWITCH=1` → remaining steps ABORTED |

## Roadmap (needs your go-ahead, nothing automatic)

1. **Your real template** → drop in `templates/` (YAML/JSON; Excel import next) and
   re-run Plan. Nothing in Apply happens without approval.
2. **Real SAP GUI Scripting channel** — on a Windows box with SAP GUI scripting
   enabled; record per-screen control paths once per client release into
   `sapcfg/gui/win_gui.py` screen maps (the console keeps screenshots/logs).
3. Later channels per design: read-only RFC/report verification, then Transport for PRD.
