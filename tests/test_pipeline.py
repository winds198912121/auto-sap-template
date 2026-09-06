"""Pipeline tests on mock data (no real SAP, no network).

Covers: template structure identification, schema + semantic validation, dependency
resolution (order + cycle detection), plan classification (CREATE/SKIP/CONFLICT/
BLOCKED/ERROR), gated apply state machine, retry on transient errors, read-back
verification (incl. tampered-store mismatch -> human queue), screenshots/evidence,
report generation, resume behaviour.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sapcfg.gui.mock import MockConfig  # noqa: E402
from sapcfg.error_kb import ErrorKB  # noqa: E402
from sapcfg.load import SchemaError, load_bundle, resolve_params  # noqa: E402
from sapcfg.model import PlanStatus, StepResult  # noqa: E402
from sapcfg.orchestrator import Orchestrator  # noqa: E402
from sapcfg.reporter import report_md  # noqa: E402
from sapcfg.steps import fi_basic  # noqa: E402

VARS = ROOT / "templates" / "example_customer_vars.yaml"
STEPS = ROOT / "templates" / "example_config_steps.yaml"

TMP = Path(tempfile.mkdtemp(prefix="sapcfg-test-"))


def tmp_runs() -> Path:
    d = TMP / "runs"
    d.mkdir(exist_ok=True)
    return d


def tmp_kb() -> ErrorKB:
    import uuid
    return ErrorKB(root=TMP / f"kb-{uuid.uuid4().hex[:8]}")


class Base(unittest.TestCase):
    def setUp(self):
        self.bundle = load_bundle(VARS, STEPS)

    def orch(self, config=None):
        return Orchestrator(adapter_name="mock", base_dir=tmp_runs(),
                            config=config, kb=tmp_kb())


class TestTemplateStructure(Base):
    def test_structure_identified(self):
        b = self.bundle
        self.assertEqual(b.template_id, "ADT_MANUFACTURING_BASE")
        self.assertEqual(b.customer, "CUSTOMER_A")
        self.assertEqual(b.target.environment, "DEV")
        self.assertEqual(b.target.client, "100")
        ids = [i.id for i in b.items]
        self.assertEqual(ids, ["coa_jp", "fv_jp", "cc_jp01", "assign_cc_company", "plant_jp10"])
        # dependency edges exist
        self.assertIn("coa_jp", b.item("cc_jp01").depends_on)
        self.assertIn("fv_jp", b.item("cc_jp01").depends_on)
        # every kind has a handler + screen definition
        for it in b.items:
            self.assertIsNotNone(fi_basic.get_handler(it.kind), it.kind)
            self.assertIn(it.transaction, fi_basic.SCREENS_BY_TCODE)

    def test_variables_resolve(self):
        it = self.bundle.item("cc_jp01")
        resolved, unresolved = resolve_params(it, self.bundle.variables)
        self.assertEqual(unresolved, [])
        self.assertEqual(resolved["company_code"], "JP01")
        self.assertEqual(resolved["currency"], "JPY")
        self.assertEqual(resolved["chart_of_accounts"], "YCOA")

    def test_undefined_variable_detected(self):
        cfg = MockConfig()
        bundle = load_bundle(VARS, STEPS)
        bundle.variables.pop("plant", None)
        it = bundle.item("plant_jp10")
        _, un = resolve_params(it, bundle.variables)
        self.assertIn("plant", un)


class TestSchema(Base):
    def test_bad_type_rejected(self):
        import yaml
        tmp = TMP / "bad_steps.yaml"
        d = yaml.safe_load(STEPS.read_text())
        d["config_items"][0]["params"]["name"] = [1, 2, 3]   # array not allowed there
        tmp.write_text(yaml.safe_dump(d))
        with self.assertRaises(SchemaError):
            load_bundle(VARS, tmp)

    def test_credentials_forbidden(self):
        import yaml
        tmp = TMP / "bad_vars.yaml"
        d = yaml.safe_load(VARS.read_text())
        d["variables"]["sap_password"] = "hunter2"
        tmp.write_text(yaml.safe_dump(d))
        with self.assertRaises(SchemaError):
            load_bundle(tmp, STEPS)

    def test_cross_file_target_mismatch(self):
        import yaml
        tmp = TMP / "mismatch_steps.yaml"
        d = yaml.safe_load(STEPS.read_text())
        d["target"]["environment"] = "QA"
        tmp.write_text(yaml.safe_dump(d))
        with self.assertRaises(SchemaError):
            load_bundle(VARS, tmp)


class TestDependency(Base):
    def test_topo_order(self):
        b = self.bundle
        plan = self.orch().plan_mode(b)
        items = json.loads((tmp_runs() / plan.run_id / "plan.json").read_text())["items"]
        seq = {i["item_id"]: i["seq"] for i in items}
        self.assertLess(seq["coa_jp"], seq["cc_jp01"])
        self.assertLess(seq["fv_jp"], seq["cc_jp01"])
        self.assertLess(seq["cc_jp01"], seq["assign_cc_company"])
        self.assertLess(seq["cc_jp01"], seq["plant_jp10"])

    def test_cycle_detection(self):
        b = self.bundle
        b.item("coa_jp").depends_on = ["cc_jp01"]   # cc depends on coa -> cycle
        plan = self.orch().plan_mode(b)
        statuses = [i["status"] for i in json.loads(
            (tmp_runs() / plan.run_id / "plan.json").read_text())["items"]]
        self.assertTrue(any(s == PlanStatus.ERROR.value for s in statuses),
                        "cycle should mark items ERROR")


class TestPlanModes(Base):
    def test_clean_dev_all_create_or_gated(self):
        plan_items = self._plan_items(MockConfig())
        by_id = {i["item_id"]: i["status"] for i in plan_items}
        self.assertEqual(by_id["coa_jp"], PlanStatus.CREATE.value)
        self.assertEqual(by_id["fv_jp"], PlanStatus.CREATE.value)
        self.assertEqual(by_id["cc_jp01"], PlanStatus.CREATE.value)
        # assign requires approval -> still CREATE but gated
        item = next(i for i in plan_items if i["item_id"] == "assign_cc_company")
        self.assertEqual(item["status"], PlanStatus.CREATE.value)
        self.assertTrue(item["needs_approval"])
        self.assertEqual(by_id["plant_jp10"], PlanStatus.CREATE.value)

    def test_idempotent_skip_when_matches(self):
        cfg = MockConfig()
        cfg.upsert("coa", dict(code="YCOA", name="JP Group Chart of Accounts"), "code")
        cfg.upsert("fiscal_variant", dict(code="K4", name="Calendar year, 4 special periods",
                                          n_periods="16"), "code")
        cfg.upsert("plant", dict(plant="JP10", company_code="JP01",
                                 name_1="Japan Plant 10"), "plant")
        items = self._plan_items(cfg)
        by_id = {i["item_id"]: i["status"] for i in items}
        self.assertEqual(by_id["coa_jp"], PlanStatus.SKIP.value)
        self.assertEqual(by_id["fv_jp"], PlanStatus.SKIP.value)
        self.assertEqual(by_id["plant_jp10"], PlanStatus.SKIP.value)

    def test_conflict_when_differs(self):
        cfg = MockConfig()
        cfg.upsert("company_code", dict(company_code="JP01", company_name="Old",
                                        currency="USD", chart_of_accounts="ICOA",
                                        fiscal_year_variant="K4", country="US",
                                        city="Dallas", language="EN"), "company_code")
        items = self._plan_items(cfg)
        it = next(i for i in items if i["item_id"] == "cc_jp01")
        self.assertEqual(it["status"], PlanStatus.CONFLICT.value)
        self.assertTrue(it["needs_approval"])

    def test_blocked_when_dependency_blocked(self):
        # make coa a CONFLICT -> cc_jp01 (dep) must be BLOCKED
        cfg = MockConfig()
        cfg.upsert("coa", dict(code="YCOA", name="Wrong Name"), "code")
        items = self._plan_items(cfg)
        by_id = {i["item_id"]: i["status"] for i in items}
        self.assertEqual(by_id["coa_jp"], PlanStatus.CONFLICT.value)
        self.assertEqual(by_id["cc_jp01"], PlanStatus.BLOCKED.value)
        self.assertEqual(by_id["plant_jp10"], PlanStatus.BLOCKED.value)

    def _plan_items(self, cfg):
        bundle = load_bundle(VARS, STEPS)
        store = self.orch(cfg).plan_mode(bundle)
        doc = json.loads((tmp_runs() / store.run_id / "plan.json").read_text())
        store.close()
        return doc["items"]


class TestApply(Base):
    def test_full_apply_verified(self):
        cfg = MockConfig()
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        states = {s["item_id"]: s["state"] for s in store.list_steps()}
        self.assertEqual(states["coa_jp"], StepResult.SUCCESS.value)
        self.assertEqual(states["fv_jp"], StepResult.SUCCESS.value)
        self.assertEqual(states["cc_jp01"], StepResult.SUCCESS.value)
        self.assertEqual(states["assign_cc_company"], StepResult.SUCCESS.value)
        self.assertEqual(states["plant_jp10"], StepResult.SUCCESS.value)
        # read-back: mock store really has the entries
        self.assertEqual(cfg.get("company_code", "JP01")["currency"], "JPY")
        self.assertEqual(cfg.get("cc_company_assign", "JP01")["company"], "01")
        self.assertEqual(cfg.get("plant", "JP10")["company_code"], "JP01")
        # evidence screenshots exist
        self.assertGreaterEqual(len(store.evidence_files()), 10)
        ev = next(iter(store.ev_dir.glob("*.svg")))
        self.assertTrue(ev.read_text().startswith("<svg"))
        store.close()

    def test_gate_requires_approval(self):
        orch = self.orch(MockConfig())
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid)          # NO approvals given
        states = {s["item_id"]: s["state"] for s in store.list_steps()}
        self.assertEqual(states["coa_jp"], StepResult.SUCCESS.value)
        self.assertEqual(states["cc_jp01"], StepResult.SUCCESS.value)
        self.assertEqual(states["assign_cc_company"], StepResult.MANUAL.value)  # gated
        store.close()

    def test_retry_on_transient_lock(self):
        cfg = MockConfig()
        cfg.faults = dict(company_code_global_params=dict(
            count=1, message="Table E071K is locked by user T-1 (retryable)"))
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        s = next(x for x in store.list_steps() if x["item_id"] == "cc_jp01")
        self.assertEqual(s["state"], StepResult.SUCCESS.value)
        self.assertGreaterEqual(s["attempts"], 2)          # retried once
        self.assertTrue(s["verified"])
        store.close()

    def test_verification_mismatch_goes_to_human_queue(self):
        cfg = MockConfig()
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()

        # sabotage: patch the OBY6 handler so that right after a successful save the
        # "SAP side" shows a different currency (saved-but-not-effective simulation).
        # The orchestrator's read-back must then detect the mismatch and route the
        # step to the human queue with verified=False.
        real = fi_basic.HANDLERS["company_code_global_params"]

        class Sabotaged:
            kind, tcode = real.kind, real.tcode
            verify_columns = real.verify_columns

            def screen(self):
                return real.screen()

            def actions(self, p):
                return real.actions(p)

            def apply(self, adapter, item, step_log):
                res = real.apply(adapter, item, step_log)
                cfg.upsert("company_code", dict(
                    company_code="JP01", company_name="Japan Company",
                    currency="EUR", chart_of_accounts="YCOA",
                    fiscal_year_variant="K4", country="JP", city="Tokyo",
                    language="JA"), "company_code")
                return res

        fi_basic.HANDLERS["company_code_global_params"] = Sabotaged()
        try:
            store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        finally:
            fi_basic.HANDLERS["company_code_global_params"] = real
        s = next(x for x in store.list_steps() if x["item_id"] == "cc_jp01")
        self.assertEqual(s["state"], StepResult.FAILED.value)   # mismatch detected
        self.assertFalse(s["verified"])
        self.assertIn("verification", s["error"])
        # downstream steps are BLOCKED by the failed upstream
        assign = next(x for x in store.list_steps() if x["item_id"] == "assign_cc_company")
        self.assertEqual(assign["state"], StepResult.BLOCKED.value)
        plant = next(x for x in store.list_steps() if x["item_id"] == "plant_jp10")
        self.assertEqual(plant["state"], StepResult.BLOCKED.value)
        store.close()

    def test_verify_engine_detects_divergence(self):
        from sapcfg.verify import build_expectations, verify_readback
        bundle = load_bundle(VARS, STEPS)
        for it in bundle.items:
            it.resolved_params, _ = resolve_params(it, bundle.variables)
        handler = fi_basic.get_handler("company_code_global_params")
        it = bundle.item("cc_jp01")
        exps = build_expectations(it, handler.verify_columns)
        ok, results = verify_readback(dict(company_code="JP01", company_name="Japan Company",
                                           currency="EUR", chart_of_accounts="YCOA",
                                           fiscal_year_variant="K4", country="JP",
                                           city="Tokyo", language="JA"), exps)
        self.assertFalse(ok)  # currency differs
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad[0]["column"], "currency")


class TestStoreReport(Base):
    def test_report_md_contains_evidence(self):
        orch = Orchestrator(adapter_name="mock", base_dir=tmp_runs())
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        md = report_md(store, tmp_runs() / rid)
        self.assertIn("# SAP Configuration Automation", md)
        self.assertIn("company_code", md)
        self.assertIn("Evidence", md)
        self.assertIn("report", md.lower())
        store.close()

    def test_resume_skips_success_steps(self):
        cfg = MockConfig()
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        first = orch.apply_mode(rid, approvals=["assign_cc_company"])
        first.close()
        # re-apply on the same run id: SUCCESS/SKIPPED steps must not re-execute
        store2 = orch.apply_mode(rid)   # no approvals this time
        states = {s["item_id"]: s["state"] for s in store2.list_steps()}
        self.assertEqual(states["assign_cc_company"], StepResult.SUCCESS.value)
        cc = next(x for x in store2.list_steps() if x["item_id"] == "cc_jp01")
        self.assertEqual(cc["attempts"], 1)      # not re-executed
        store2.close()


class TestErrorPolicy(Base):
    """Design §6: error classification, bounded retry, no-retry kinds, KB."""

    def _plan_and_run(self, cfg, approvals=None, **kw):
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=approvals or ["assign_cc_company"], **kw)
        return store, rid

    def test_lock_retried_then_success_and_kb_success_rate(self):
        cfg = MockConfig()
        cfg.faults = dict(company_code_global_params=dict(
            count=1, message="Table E071K is locked by user T-1"))
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        s = next(x for x in store.list_steps() if x["item_id"] == "cc_jp01")
        self.assertEqual(s["state"], StepResult.SUCCESS.value)
        self.assertGreaterEqual(s["attempts"], 2)   # auto-retried once
        self.assertTrue(s["verified"])
        ev = [e for e in store.events_all() if e["type"] == "error_classify"]
        self.assertEqual(ev[0]["payload"]["kind"], "LOCK")
        self.assertEqual(ev[0]["payload"]["key"], "LK-100")
        store.close()
        # KB recorded fail + success -> success_rate 0.5 for LK-100
        stats = orch.kb.rule_summary()
        self.assertEqual(stats["LK-100"]["hits"], 2)
        self.assertEqual(stats["LK-100"]["success_rate"], 0.5)

    def test_permission_never_retries(self):
        cfg = MockConfig()
        cfg.faults = dict(company_code_global_params=dict(
            count=5, message="You are not authorized to run transaction OBY6 (SU53)"))
        store, _ = self._plan_and_run(cfg)
        s = next(x for x in store.list_steps() if x["item_id"] == "cc_jp01")
        self.assertEqual(s["state"], StepResult.MANUAL.value)
        self.assertEqual(s["attempts"], 1)          # NO retry for permission
        self.assertIn("PERMISSION", s["error"])
        assign = next(x for x in store.list_steps() if x["item_id"] == "assign_cc_company")
        self.assertEqual(assign["state"], StepResult.BLOCKED.value)  # downstream blocked
        store.close()

    def test_unknown_error_proposes_to_kb_and_saves_context(self):
        kb = tmp_kb()
        orch = Orchestrator(adapter_name="mock", base_dir=tmp_runs(),
                            config=MockConfig(), kb=kb)
        cfg = MockConfig()
        cfg.faults = dict(company_code_global_params=dict(
            count=1, message="Internal error code F0A_17 (unknown)"))
        bundle = load_bundle(VARS, STEPS)
        orch.config = cfg
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        s = next(x for x in store.list_steps() if x["item_id"] == "cc_jp01")
        self.assertEqual(s["state"], StepResult.MANUAL.value)
        pending = kb.pending()
        self.assertTrue(any("F0A_17" in p["text"] for p in pending))
        self.assertFalse(pending[0]["auto_fix_allowed"])
        self.assertEqual(pending[0]["risk_level"], "High")
        self.assertTrue(list(store.ev_dir.glob("context_cc_jp01.json")))
        store.close()

    def test_classifier_priority_class_number_first(self):
        from sapcfg.errclass import Classifier, ErrorKind
        from sapcfg.gui.base import StepMessageError
        clf = Classifier()
        # text would match LOCK, but class+number rule BS-100 wins (priority 1)
        v = clf.classify(StepMessageError("Table E071K is locked", tcode="OBY6",
                                          msg_class="E0", msg_number="000"))
        self.assertEqual(v.kind, ErrorKind.TRANSIENT)
        self.assertEqual(v.error_key, "E0/000")
        # plain text only -> LOCK rule
        v2 = clf.classify(StepMessageError("Table E071K is locked", tcode="OBY6"))
        self.assertEqual(v2.kind, ErrorKind.LOCK)
        # unmatched -> UNKNOWN, no auto fix
        v3 = clf.classify(StepMessageError("weird new popup text", tcode="ZZ99"))
        self.assertEqual(v3.kind, ErrorKind.UNKNOWN)
        self.assertFalse(v3.auto_fix_allowed)


class TestGuards(Base):
    """Design §8: target triple-check abort + Kill Switch."""

    def test_target_mismatch_aborts_run(self):
        # adapter forced to PRD/999 while plan target is S4D/100
        orch = Orchestrator(adapter_name="mock", base_dir=tmp_runs(),
                            kb=tmp_kb(), mock_system="PRD", mock_client="999")
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        self.assertEqual(store.run_status(), "aborted")
        states = {s["item_id"]: s["state"] for s in store.list_steps()}
        self.assertEqual(set(states.values()), {StepResult.ABORTED.value})
        store.close()

    def test_kill_switch_aborts_before_execution(self):
        from sapcfg.store import RunStore as RS
        orch = self.orch(MockConfig())
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        # write kill marker into the run dir then apply
        marker = RS(run_id=rid, base=tmp_runs())
        (marker.dir / "KILL").write_text("user requested abort")
        marker.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        self.assertEqual(store.run_status(), "aborted")
        states = {s["item_id"]: s["state"] for s in store.list_steps()}
        self.assertEqual(set(states.values()), {StepResult.ABORTED.value})
        store.close()

    def test_record_event_has_before_after(self):
        cfg = MockConfig()
        orch = self.orch(cfg)
        bundle = load_bundle(VARS, STEPS)
        store = orch.plan_mode(bundle)
        rid = store.run_id
        store.close()
        store = orch.apply_mode(rid, approvals=["assign_cc_company"])
        rec = [e for e in store.events_all() if e["type"] == "record"
               and e["step"] == "cc_jp01"][0]["payload"]
        self.assertEqual(rec["state"], "SUCCESS")
        self.assertIsNone(rec["before"])                    # did not exist
        self.assertEqual(rec["after"]["currency"], "JPY")  # after value captured
        store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
