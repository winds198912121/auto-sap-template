"""Orchestrator: Plan mode (read-only) and gated Apply mode state machine.

Design doc §5/§6/§7/§8. Apply follows the per-step protocol:
  1. re-check target system + client (design §8 triple check; §"单步处理逻辑" #1)
  2. read current state + evidence (before values)
  3. match target -> SKIPPED_IDEMPOTENT
  4. conflict -> run or wait for approval by risk rules
  5. execute GUI/API actions
  6. capture status bar / popup / exceptions / screenshots
  7. read-back verify all key fields
  8. success -> persist before/after values; failure -> error classification (§6)

Errors are classified by the rule engine (message class+number -> tcode+text -> text
-> UNKNOWN). Retry is bounded (§6.3): LOCK/TRANSIENT/NAVIGATION auto-retry <= 2;
PERMISSION / INPUT / BUSINESS_CONFLICT / UNKNOWN never retry and go to the human
queue; UNKNOWN additionally proposes an entry to the Error Knowledge Base (§7.2).
Global Kill Switch + per-step timeout are honoured. Phase 1 always uses the mock
adapter; nothing connects to a real system or writes to a real SAP DB.
"""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from typing import Optional

from .errclass import Classifier, ErrorKind, Verdict
from .error_kb import ErrorKB
from .gui.base import HumanRequiredError, SapAutomationError, StepMessageError
from .gui.mock import MockConfig, MockGui
from .load import parse_plan_doc, resolve_params
from .model import Plan, PlanItem, PlanStatus, StepResult, TemplateBundle, now_iso
from .planner import SapStateView, build_plan
from .store import RUNS_DIR, RunStore
from .steps import fi_basic
from .verify import build_expectations, verify_readback

NO_RETRY_KINDS = {ErrorKind.PERMISSION, ErrorKind.INPUT, ErrorKind.BUSINESS_CONFLICT,
                  ErrorKind.UNKNOWN, ErrorKind.PRECONDITION, ErrorKind.ALREADY_EXISTS}


class _StateView(SapStateView):
    """Planner view = read-only access to current (mock) SAP config state."""

    def __init__(self, cfg: MockConfig):
        self.cfg = cfg

    def read_entry(self, table: str, key: str) -> dict | None:
        return self.cfg.get(table, key)

    def list_keys(self, table: str) -> list[str]:
        return self.cfg.keys(table)


class _TargetMismatch(SapAutomationError):
    """Abort signal: adapter session does not match the planned target (design §8)."""


class Orchestrator:
    def __init__(self, adapter_name: str = "mock", base_dir=RUNS_DIR,
                 config: Optional[MockConfig] = None,
                 classifier: Optional[Classifier] = None,
                 kb: Optional[ErrorKB] = None,
                 mock_system: str = "", mock_client: str = ""):
        self.adapter_name = adapter_name
        self.base_dir = base_dir
        self.config = config
        self.classifier = classifier or Classifier()
        self.kb = kb or ErrorKB()
        self.mock_system = mock_system      # override knobs for target-drift tests
        self.mock_client = mock_client
        self.adapter: Optional[MockGui] = None

    # ------------------------------------------------------------------ plumbing
    def _new_mock(self, store: RunStore, plan: Plan) -> MockGui:
        if self.config is None:
            self.config = MockConfig()
        gui = MockGui(fi_basic.SCREENS, self.config,
                      system=self.mock_system or plan.target.sap_system,
                      client=self.mock_client or plan.target.client)
        gui.connect()
        return gui

    def _new_adapter(self, store: RunStore, plan: Plan):
        """Adapter factory: name -> driver (design §3 SAP Adapter layer).

        mock       : in-process simulated SAP GUI (Phase 1 default; only one
                     allowed to plan against the mock state view).
        sap_gui_mac: real SAP GUI for Java on THIS macOS machine, driven by
                     Accessibility + local OCR. Consent-gated inside the
                     adapter (env flag / .sapcfg_allow_real_sap).
        win/sap_gui_scripting exists as a class but is never constructed here.
        """
        if self.adapter_name == "sap_gui_mac":
            from .gui.mac_gui import MacSapGui   # noqa: E402  (guarded import)
            gui = MacSapGui(system=plan.target.sap_system,
                            client=plan.target.client,
                            language=plan.target.language)
            gui.connect()
            if hasattr(gui, "set_evidence_dir"):
                gui.set_evidence_dir(str(store.ev_dir))
            return gui
        return self._new_mock(store, plan)

    def _plan_from_store(self, run_id: str) -> Plan:
        pj = self.base_dir / run_id / "plan.json"
        return parse_plan_doc(json.loads(pj.read_text(encoding="utf-8")))

    def _verify_meta(self, run_id: str) -> dict[str, dict]:
        pj = self.base_dir / run_id / "plan.json"
        data = json.loads(pj.read_text(encoding="utf-8"))
        return data.get("verify_meta", {})

    def _state_view(self) -> SapStateView:
        return _StateView(self.config or MockConfig())

    # ------------------------------------------------------------------ guards (§8)
    @staticmethod
    def _kill_marker(store: RunStore) -> bool:
        env = os.environ.get("SAPCFG_KILL_SWITCH", "") == "1"
        local = (store.dir / "KILL").exists()
        global_ = (RUNS_DIR.parent / ".kill_switch").exists()
        return env or local or global_

    def _enforce_target(self, store: RunStore, plan: Plan) -> None:
        """Per-step re-check of system id + client (design §8 / per-step logic #1)."""
        if self.adapter is None:
            return
        sys_ok = self.adapter.system == plan.target.sap_system
        cli_ok = self.adapter.client == plan.target.client
        if sys_ok and cli_ok:
            store.log(f"target re-check OK: {self.adapter.system}/{self.adapter.client} "
                      f"== {plan.target.sap_system}/{plan.target.client}")
            return
        raise _TargetMismatch(
            f"TARGET MISMATCH: adapter session {self.adapter.system}/{self.adapter.client} "
            f"!= plan target {plan.target.sap_system}/{plan.target.client}. Aborting "
            f"(design §8 triple-check).")

    # ------------------------------------------------------------------ PLAN MODE
    def plan_mode(self, bundle: TemplateBundle, run_id: Optional[str] = None) -> RunStore:
        """Resolve variables, read current SAP state, diff -> plan. NO SAP writes."""
        for it in bundle.items:
            it.resolved_params, it.unresolved_vars = resolve_params(it, bundle.variables)
        store = RunStore(run_id=run_id, base=self.base_dir)
        plan = build_plan(bundle, self._state_view(), fi_basic.HANDLER_TABLES,
                          store.run_id)
        store.meta(plan, self.adapter_name)
        meta = {it.id: dict(scope=it.verify_scope, ignore=it.verify_ignore,
                            extra=it.verify_extra)
                for it in bundle.items}
        pj = store.dir / "plan.json"
        doc = json.loads(pj.read_text(encoding="utf-8"))
        doc["verify_meta"] = meta
        pj.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        store.emit("plan", dict(summary=plan.summary(),
                                items=[dict(item_id=i.item_id, seq=i.seq,
                                            status=i.status.value, reason=i.reason,
                                            needs_approval=i.needs_approval)
                                       for i in plan.items]))
        store.log("Plan mode complete: " +
                  ", ".join(f"{k}={v}" for k, v in plan.summary().items()))
        store.close()
        return store

    # ------------------------------------------------------------------ APPLY MODE
    def apply_mode(self, run_id: str, approvals: Optional[list[str]] = None,
                   approve_all: bool = False) -> RunStore:
        """Execute a planned run against the mock adapter (gated)."""
        store = RunStore(run_id=run_id, base=self.base_dir)
        plan_file = self.base_dir / run_id / "plan.json"
        if not plan_file.exists():
            store.close()
            raise RuntimeError(f"no plan found for run {run_id} (plan first)")
        plan = self._plan_from_store(run_id)
        approvals = set(approvals or [])
        verify_meta = self._verify_meta(run_id)

        gui = self._new_adapter(store, plan)
        self.adapter = gui
        store.set_run_status("applying")
        store.emit("apply", dict(started=now_iso(), adapter=gui.name,
                                 approvals=sorted(approvals), approve_all=approve_all,
                                 target=dict(system=plan.target.sap_system,
                                             client=plan.target.client,
                                             environment=plan.target.environment)))
        done = {s["item_id"] for s in store.list_steps()
                if s["state"] in (StepResult.SUCCESS.value, StepResult.SKIPPED.value)}
        BAD = {StepResult.FAILED.value, StepResult.MANUAL.value, StepResult.BLOCKED.value,
               StepResult.ABORTED.value}
        finished: dict[str, str] = {}
        aborted = False
        try:
            for item in plan.items:
                if self._kill_marker(store):
                    aborted = True
                    store.log("KILL SWITCH engaged -> aborting remaining steps",
                              item.item_id, "error")
                    store.emit("kill", dict(item=item.item_id), item.item_id)
                    break
                if item.item_id in done:
                    store.log(f"[{item.item_id}] resume: already SUCCESS/SKIPPED, "
                              f"not re-executed", item.item_id)
                    finished[item.item_id] = StepResult.SUCCESS.value
                    continue
                blocked_by = [d for d in item.depends_on if finished.get(d) in BAD]
                if blocked_by:
                    store.emit("block", dict(item=item.item_id, deps=blocked_by),
                               item.item_id)
                    store.log(f"[{item.item_id}] BLOCKED: upstream {','.join(blocked_by)} "
                              f"did not succeed", item.item_id, "error")
                    store.step_save(item.item_id, item.seq, item.kind, StepResult.BLOCKED,
                                    started=now_iso(), finished=now_iso(),
                                    error=f"blocked by upstream: {','.join(blocked_by)}")
                    finished[item.item_id] = StepResult.BLOCKED.value
                    continue
                self._run_item(store, plan, item, approvals, approve_all, verify_meta)
                st = store.step_load(item.item_id)
                finished[item.item_id] = (st or {}).get("state", StepResult.PENDING.value)
        except _TargetMismatch as e:
            aborted = True
            store.emit("abort", dict(reason=str(e)))
            store.log(f"RUN ABORTED: {e}", "", "error")
            # mark remaining not-yet-finished steps as ABORTED
            for item in plan.items:
                if item.item_id not in finished:
                    store.step_save(item.item_id, item.seq, item.kind, StepResult.ABORTED,
                                    started="", finished=now_iso(), error=str(e))
        finally:
            if aborted:
                store.set_run_status("aborted")
                for item in plan.items:
                    if item.item_id not in finished:
                        store.step_save(item.item_id, item.seq, item.kind,
                                        StepResult.ABORTED, started="", finished=now_iso(),
                                        error="aborted")
            else:
                store.set_run_status("finished")
            gui.disconnect()
            self.kb.close()
            store.emit("apply", dict(finished=now_iso()))
            store.log("Apply finished. Summary: " +
                      ", ".join(f"{k}={v}" for k, v in store.summary_stats().items()))
            store.close()
        return store

    # ------------------------------------------------------------------ per-step machine
    def _run_item(self, store: RunStore, plan: Plan, item: PlanItem,
                  approvals: set, approve_all: bool,
                  verify_meta: dict[str, dict]):
        kind = item.kind
        handler = fi_basic.get_handler(kind)
        started = now_iso()
        gate = (item.status in (PlanStatus.UPDATE, PlanStatus.CONFLICT)
                or item.needs_approval)
        approved = approve_all or item.item_id in approvals

        # (per-step protocol 1) target re-check --------------------------------
        try:
            self._enforce_target(store, plan)
        except _TargetMismatch:
            raise

        # (2a) approval gate ----------------------------------------------------
        if gate and not approved:
            store.emit("gate", dict(item=item.item_id, status=item.status.value,
                                    reason=item.reason), item.item_id)
            store.log(f"[{item.item_id}] {item.title}: AWAITING HUMAN APPROVAL "
                      f"({item.status.value}: {item.reason}) -> human queue",
                      item.item_id, "warn")
            store.step_save(item.item_id, item.seq, kind, StepResult.MANUAL,
                            approval="pending", started=started, finished=now_iso(),
                            error=item.reason)
            self._record(store, item, before=None, verdict=None, messages=[])
            return

        # (3) idempotent skip ----------------------------------------------------
        if item.status is PlanStatus.SKIP:
            store.log(f"[{item.item_id}] SKIPPED_IDEMPOTENT (exists and matches; "
                      f"verified at plan time)", item.item_id)
            store.step_save(item.item_id, item.seq, kind, StepResult.SKIPPED,
                            verified=True, started=started, finished=now_iso())
            self._record(store, item, before=None, verdict=None, messages=[])
            return
        if item.status in (PlanStatus.BLOCKED, PlanStatus.ERROR):
            store.log(f"[{item.item_id}] {item.status.value}: {item.reason} -> blocked",
                      item.item_id, "error")
            store.step_save(item.item_id, item.seq, kind, StepResult.BLOCKED,
                            started=started, finished=now_iso(), error=item.reason)
            self._record(store, item, before=None, verdict=None, messages=[])
            return
        if item.status is PlanStatus.CONFLICT and approved:
            store.log(f"[{item.item_id}] CONFLICT OVERRIDDEN by explicit approval: "
                      f"overwriting differing existing entry", item.item_id, "warn")
        if handler is None:
            store.log(f"[{item.item_id}] no step handler for kind {kind!r}", item.item_id, "error")
            store.step_save(item.item_id, item.seq, kind, StepResult.FAILED,
                            started=started, finished=now_iso(),
                            error=f"no handler for kind {kind!r}")
            return

        # (2b) read current state + before-values -------------------------------
        tspec = fi_basic.HANDLER_TABLES[kind]
        key_val = str(item.desired.get(tspec["key"], ""))
        before = self.adapter.read_config(tspec["table"], key_val) if self.adapter else None

        item_stub = SimpleNamespace(id=item.item_id, kind=kind, title=item.title,
                                    transaction=item.transaction,
                                    resolved_params=item.desired)
        meta = verify_meta.get(item.item_id, {})
        exp_stub = SimpleNamespace(resolved_params=item.desired,
                                   verify_scope=meta.get("scope"),
                                   verify_ignore=meta.get("ignore", []),
                                   verify_extra=meta.get("extra", {}))
        messages: list[str] = []
        seen_keys: list[str] = []
        last_err, last_err_key = "", ""
        ok = False
        attempts = 0
        verdict: Optional[Verdict] = None
        max_attempts = 3          # initial + 2 auto retries (design §6.3)
        while attempts < max_attempts and not ok:
            attempts += 1
            if self._kill_marker(store):
                store.log(f"[{item.item_id}] kill switch -> abort", item.item_id, "error")
                store.step_save(item.item_id, item.seq, kind, StepResult.ABORTED,
                                attempts=attempts, started=started, finished=now_iso(),
                                error="kill switch")
                return
            store.step_save(item.item_id, item.seq, kind,
                            StepResult.RETRYING if attempts > 1 else StepResult.RUNNING,
                            attempts=attempts, started=started, approval="approved")
            store.log(f"[{item.item_id}] executing attempt {attempts}/{max_attempts} "
                      f"via {self.adapter_name} ({item.transaction or kind})",
                      item.item_id)
            try:
                res = handler.apply(self.adapter, item_stub,
                                    _mk_step_log(store, item.item_id))
                if isinstance(res, dict) and res.get("message"):
                    messages.append(str(res["message"]))
                # (7) read-back verification of all key fields ------------------
                actual = self.adapter.read_config(tspec["table"], key_val) if self.adapter else None
                exps = build_expectations(exp_stub, handler.verify_columns)
                vok, results = verify_readback(actual, exps)
                store.emit("verify", dict(item=item.item_id, ok=vok, results=results,
                                          actual=actual, before=before), item.item_id)
                if not vok:
                    store.log(f"[{item.item_id}] READ-BACK MISMATCH after save -> "
                              f"human queue (before={json.dumps(before, ensure_ascii=False)})",
                              item.item_id, "error")
                    store.step_save(item.item_id, item.seq, kind, StepResult.FAILED,
                                    attempts=attempts, verified=False,
                                    readback=dict(before=before, actual=actual,
                                                  results=results),
                                    messages=messages, started=started,
                                    finished=now_iso(),
                                    error="read-back verification failed")
                    return
                store.step_save(item.item_id, item.seq, kind, StepResult.SUCCESS,
                                attempts=attempts, verified=True,
                                readback=dict(before=before, actual=actual,
                                              results=results),
                                messages=messages, started=started, finished=now_iso())
                store.log(f"[{item.item_id}] SUCCESS + verified (attempt {attempts}); "
                          f"before={json.dumps(before, ensure_ascii=False)} after="
                          f"{json.dumps(actual, ensure_ascii=False)}", item.item_id)
                if attempts > 1 and last_err_key:
                    self.kb.record_hit(last_err_key, ok=True, run_id=plan.run_id,
                                       tcode=item.transaction or item.kind)
                ok = True
            except StepMessageError as e:
                verdict = self.classifier.classify(e)
                last_err = f"{verdict.kind.value}: {e.text} [{verdict.error_key}]"
                last_err_key = verdict.error_key
                messages.append(last_err)
                seen_keys.append(verdict.error_key)
                self._on_error(store, plan, item, e, verdict)
                # decide: retry or human (design §6.3)
                budget_ok = attempts <= verdict.retry_max
                repeats = len(set(seen_keys)) <= 1 and seen_keys.count(verdict.error_key) >= 2
                if (verdict.retryable and budget_ok and not repeats
                        and not self._kill_marker(store)):
                    store.step_save(item.item_id, item.seq, kind, StepResult.RETRYING,
                                    attempts=attempts, messages=messages, started=started,
                                    error=last_err)
                    store.log(f"[{item.item_id}] retry allowed "
                              f"({verdict.kind.value}, rule {verdict.error_key}, "
                              f"attempt {attempts}/{verdict.retry_max})", item.item_id)
                    time.sleep(min(0.5 * attempts, 2.0))
                    continue
                # no retry -> human queue with classification evidence
                human_reason = last_err
                if verdict.kind is ErrorKind.PERMISSION:
                    human_reason += " (SU53 evidence attached; permission problems are never auto-retried)"
                elif verdict.kind is ErrorKind.UNKNOWN:
                    human_reason += " (unknown error -> Error Knowledge Base review)"
                store.step_save(item.item_id, item.seq, kind, StepResult.MANUAL,
                                attempts=attempts, messages=messages, started=started,
                                finished=now_iso(), error=human_reason)
                store.log(f"[{item.item_id}] -> HUMAN QUEUE: {human_reason}",
                          item.item_id, "error")
                return
            except HumanRequiredError as e:
                store.step_save(item.item_id, item.seq, kind, StepResult.MANUAL,
                                attempts=attempts, messages=messages, started=started,
                                finished=now_iso(), error=str(e))
                store.log(f"[{item.item_id}] -> HUMAN QUEUE: {e}", item.item_id, "error")
                return
            except Exception as e:     # unexpected code error -> UNKNOWN semantics
                verdict = Verdict(ErrorKind.UNKNOWN, None,
                                  f"EXC:{type(e).__name__}", "human", 0, False, "high",
                                  f"unexpected exception {type(e).__name__}: {e!r}")
                last_err = str(e)
                store.log(f"[{item.item_id}] unexpected {e!r} -> human queue",
                          item.item_id, "error")
                store.step_save(item.item_id, item.seq, kind, StepResult.MANUAL,
                                attempts=attempts, messages=messages, started=started,
                                finished=now_iso(), error=f"unexpected: {e!r}")
                self._save_context(store, item, last_err)
                return

        if not ok:
            store.step_save(item.item_id, item.seq, kind, StepResult.FAILED,
                            attempts=attempts, messages=messages, started=started,
                            finished=now_iso(), error=last_err or "retries exhausted")
            store.log(f"[{item.item_id}] FAILED after {attempts} attempts: {last_err}",
                      item.item_id, "error")
        self._record(store, item, before, verdict, messages)

    # ------------------------------------------------------------------ error handling (§6/§7)
    def _on_error(self, store: RunStore, plan: Plan, item: PlanItem,
                  e: StepMessageError, verdict: Verdict):
        store.emit("error_classify", dict(
            item=item.item_id, kind=verdict.kind.value, key=verdict.error_key,
            action=verdict.action, retry_max=verdict.retry_max, risk=verdict.risk,
            reason=verdict.reason, text=e.text), item.item_id)
        store.message(item.item_id, f"{e.text}  [{verdict.kind.value}]", "error")
        # KB: record hit + success_rate
        self.kb.record_hit(verdict.error_key, ok=False, run_id=plan.run_id,
                           tcode=item.transaction or item.kind)
        # unknown -> propose to KB review queue with evidence
        if verdict.kind is ErrorKind.UNKNOWN:
            ev = self._save_context(store, item, e.text)
            self.kb.propose_unknown(dict(
                error_key=verdict.error_key, text=e.text,
                tcode=item.transaction or item.kind, screen="",
                classification="UNKNOWN",
                root_cause="unmatched SAP message (auto-proposed)",
                remediation="await consultant analysis",
                auto_fix_allowed=False, risk_level="High",
                approved_by="", run_id=plan.run_id,
                evidence=ev))

    def _save_context(self, store: RunStore, item: PlanItem, text: str) -> str:
        """Persist step context (screen + params + message) for the human queue."""
        cap = self.adapter.capture_screen() if self.adapter else {}
        ctx = dict(item=item.item_id, kind=item.kind, transaction=item.transaction,
                   message=text, desired=item.desired, screen=cap)
        fname = f"context_{item.item_id}.json"
        (store.ev_dir / fname).write_text(
            json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
        store.emit("evidence", dict(file=f"evidence/{fname}", kind="context"),
                   item.item_id)
        return f"evidence/{fname}"

    def _record(self, store: RunStore, item: PlanItem, before: Optional[dict],
                verdict: Optional[Verdict], messages: list[str]):
        """(per-step protocol 8) persist before/after + full audit record."""
        st = store.step_load(item.item_id) or {}
        rb = st.get("readback") or {}
        store.emit("record", dict(
            item=item.item_id, kind=item.kind, transaction=item.transaction,
            tcode=item.transaction, state=st.get("state"),
            attempts=st.get("attempts", 0), verified=st.get("verified"),
            classification=verdict.kind.value if verdict else None,
            error_key=verdict.error_key if verdict else None,
            before=before, after=rb.get("actual"),
            error=st.get("error", ""), messages=messages,
            started=st.get("started", ""), finished=st.get("finished", ""),
        ), item.item_id)


def _mk_step_log(store: RunStore, item_id: str):
    """Callback handed to handler.apply(); records screens/messages as evidence."""
    def log(etype: str, payload: dict):
        if etype == "screen":
            store.screen(item_id, payload)
        elif etype == "message":
            store.message(item_id, payload.get("text", ""), payload.get("cls", "info"))
        else:
            store.emit(etype, payload, item_id)
    return log


__all__ = ["Orchestrator", "_StateView"]
