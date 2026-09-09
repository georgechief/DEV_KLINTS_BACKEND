"""DCS-09 Step 5 — evaluate orchestration (resolve → run → persist)."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.assemble import assemble_dcs_score
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.pilot_gates.contract import (
    EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
    PILOT_GATE_EVAL_KIND,
    PILOT_SUPPLEMENTAL_SCOPE,
    SLICE_A_CHECK_IDS,
    STATUS_FAIL,
    STATUS_NOT_CONNECTED,
    STATUS_PASS,
    STATUS_UNKNOWN,
)
from dataruns.dcs.pilot_gates.evaluate import (
    PilotGateEvaluateError,
    evaluate_pilot_gates,
    supplemental_readiness_for_use_case,
)
from dataruns.dcs.pilot_gates.executors import clear_supplemental_executor_registry
from dataruns.dcs.pilot_gates.store import (
    get_latest_pilot_gate_eval,
    get_latest_supplemental_status_map,
)
from dataruns.dcs.types import CheckResult
from dataruns.dcs.worklist import get_latest_terminal_dcs_run
from dataruns.models import DataRun
from tenants.models import Company, Tenant


class PilotGatesStep5IsolationTests(SimpleTestCase):
    def test_assemble_still_42_only(self):
        master = load_check_master_from_json()
        results = [
            CheckResult(check_id=c.check_id, status="PASS") for c in master.checks
        ]
        run = assemble_dcs_score(results, erp_in_scope=False, master=master)
        self.assertEqual(len(run.check_result_refs), 42)


class PilotGatesStep5EvaluateTests(TestCase):
    def setUp(self):
        clear_supplemental_executor_registry()
        self.tenant = Tenant.objects.create(name="PG S5", slug="pg-s5")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S5 Co",
            domain="pg-s5.example.com",
        )

    def tearDown(self):
        clear_supplemental_executor_registry()

    def _dcs_score(self, *, snapshot: dict | None = None) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 80,
            },
            run_snapshot=snapshot
            if snapshot is not None
            else {
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
            },
        )

    def _slice_a_contacts_pass(self) -> list[dict]:
        return [
            {
                "email": "ok@example.com",
                "contactId": "1",
                "state": "CONFIRMED",
                "createdOn": "2026-01-01T00:00:00Z",
            },
            {
                "email": "ok2@example.com",
                "contactId": "2",
                "state": "CONFIRMED",
                "createdOn": "2026-01-01T00:00:00Z",
            },
        ]

    def test_evaluate_uc02_resolves_slice_a_and_persists(self):
        score = self._dcs_score()
        snapshot = {
            "as_of": "2026-06-01T00:00:00Z",
            "connectors": {"manago_ai": {"status": "connected"}},
            "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
        }
        out = evaluate_pilot_gates(
            company=self.company,
            use_case_ids=["UC-02"],
            data_run_id=score.pk,
            scoring_snapshot=snapshot,
            erp_in_scope=False,
        )
        self.assertEqual(set(out.check_ids), set(SLICE_A_CHECK_IDS))
        self.assertFalse(out.skipped)
        self.assertIsNotNone(out.bundle)
        self.assertEqual(out.data_run_id_score, score.pk)
        self.assertEqual(out.status_by_check_id["CI-08"], STATUS_PASS)
        self.assertEqual(out.status_by_check_id["CC-06"], STATUS_PASS)
        self.assertEqual(len(out.readiness), 1)
        self.assertEqual(out.readiness[0]["use_case_id"], "UC-02")
        self.assertTrue(out.readiness[0]["supplemental_ready"])
        self.assertEqual(out.readiness[0]["blocked_by"], [])
        self.assertEqual(out.readiness[0]["not_evaluated"], [])

        latest = get_latest_pilot_gate_eval(company=self.company)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.data_run_id, out.bundle.data_run_id)
        self.assertEqual(latest.scope, PILOT_SUPPLEMENTAL_SCOPE)

    def test_evaluate_check_ids_subset(self):
        score = self._dcs_score()
        out = evaluate_pilot_gates(
            company=self.company,
            check_ids=["CI-08"],
            data_run_id=score.pk,
            scoring_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
                "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
            },
        )
        self.assertEqual(list(out.check_ids), ["CI-08"])
        self.assertEqual(out.status_by_check_id["CI-08"], STATUS_PASS)

    def test_evaluate_empty_check_ids_skips_persist(self):
        before = DataRun.objects.filter(
            tenant=self.tenant,
            metadata__kind=PILOT_GATE_EVAL_KIND,
        ).count()
        out = evaluate_pilot_gates(
            company=self.company,
            check_ids=[],
            erp_in_scope=False,
        )
        self.assertTrue(out.skipped)
        self.assertEqual(out.skip_reason, "empty_check_set")
        self.assertEqual(out.results, ())
        after = DataRun.objects.filter(
            tenant=self.tenant,
            metadata__kind=PILOT_GATE_EVAL_KIND,
        ).count()
        self.assertEqual(before, after)

    def test_evaluate_all_twelve_when_both_null(self):
        score = self._dcs_score()
        out = evaluate_pilot_gates(
            company=self.company,
            data_run_id=score.pk,
            scoring_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "disconnected"}},
            },
            erp_in_scope=False,
        )
        self.assertEqual(len(out.check_ids), EXPECTED_SUPPLEMENTAL_CHECK_COUNT)
        self.assertEqual(out.status_by_check_id["BR-09"], STATUS_NOT_CONNECTED)
        self.assertEqual(out.status_by_check_id["PT-06"], STATUS_NOT_CONNECTED)
        self.assertEqual(out.status_by_check_id["CI-08"], STATUS_NOT_CONNECTED)
        self.assertIn(
            out.status_by_check_id["LE-07"],
            {STATUS_UNKNOWN, STATUS_NOT_CONNECTED},
        )

    def test_partial_merge_preserves_prior_checks(self):
        score = self._dcs_score()
        snap = {
            "as_of": "2026-06-01T00:00:00Z",
            "connectors": {"manago_ai": {"status": "connected"}},
            "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
        }
        evaluate_pilot_gates(
            company=self.company,
            check_ids=["CI-08", "CC-06"],
            data_run_id=score.pk,
            scoring_snapshot=snap,
        )
        snap_fail = {
            "as_of": "2026-06-01T00:00:00Z",
            "connectors": {"manago_ai": {"status": "connected"}},
            "gate_inputs": {
                "manago_contacts": [
                    {"email": "bad@gmial.com", "contactId": "1"},
                ]
            },
        }
        out = evaluate_pilot_gates(
            company=self.company,
            check_ids=["CI-08"],
            data_run_id=score.pk,
            scoring_snapshot=snap_fail,
        )
        self.assertEqual(out.status_by_check_id["CI-08"], STATUS_FAIL)
        self.assertEqual(out.status_by_check_id["CC-06"], STATUS_PASS)

    def test_does_not_pollute_dcs_score_latest(self):
        score = self._dcs_score()
        evaluate_pilot_gates(
            company=self.company,
            check_ids=["CI-08"],
            data_run_id=score.pk,
            scoring_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
                "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
            },
        )
        latest_dcs = get_latest_terminal_dcs_run(company=self.company)
        self.assertIsNotNone(latest_dcs)
        self.assertEqual(latest_dcs.pk, score.pk)
        meta = latest_dcs.metadata if isinstance(latest_dcs.metadata, dict) else {}
        self.assertEqual(meta.get("kind"), DCS_SCORE_KIND)

    def test_readiness_blocked_and_not_evaluated(self):
        row = supplemental_readiness_for_use_case(
            use_case_id="UC-02",
            status_by_check_id={"CI-08": STATUS_PASS, "CC-06": STATUS_FAIL},
        )
        self.assertFalse(row["supplemental_ready"])
        self.assertEqual(
            row["blocked_by"],
            [{"check_id": "CC-06", "status": STATUS_FAIL}],
        )
        self.assertEqual(row["not_evaluated"], [])

        missing = supplemental_readiness_for_use_case(
            use_case_id="UC-02",
            status_by_check_id={"CI-08": STATUS_PASS},
        )
        self.assertFalse(missing["supplemental_ready"])
        self.assertEqual(missing["not_evaluated"], ["CC-06"])

    def test_status_map_matches_bundle(self):
        score = self._dcs_score()
        out = evaluate_pilot_gates(
            company=self.company,
            use_case_ids=["uc-02"],
            data_run_id=score.pk,
            scoring_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
                "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
            },
        )
        self.assertEqual(
            get_latest_supplemental_status_map(company=self.company),
            out.status_by_check_id,
        )
        # This-pass results are store-normalized (required_by filled from master).
        self.assertEqual(len(out.results), 2)
        by_id = {r["check_id"]: r for r in out.results}
        self.assertIn("UC-02", by_id["CI-08"]["required_by"])
        self.assertEqual(out.to_dict()["merged_count"], 2)

    def test_invalid_explicit_data_run_id_raises(self):
        with self.assertRaises(PilotGateEvaluateError):
            evaluate_pilot_gates(
                company=self.company,
                check_ids=["CI-08"],
                data_run_id=999999,
            )
        # Wrong company score id also rejected.
        other = Company.objects.create(
            tenant=self.tenant,
            name="Other",
            domain="pg-s5-other.example.com",
        )
        score = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(other.id),
            },
            run_snapshot={},
        )
        with self.assertRaises(PilotGateEvaluateError):
            evaluate_pilot_gates(
                company=self.company,
                check_ids=["CI-08"],
                data_run_id=score.pk,
            )

    def test_company_isolation(self):
        other = Company.objects.create(
            tenant=self.tenant,
            name="Other Co",
            domain="pg-s5-b.example.com",
        )
        score = self._dcs_score()
        evaluate_pilot_gates(
            company=self.company,
            check_ids=["CI-08"],
            data_run_id=score.pk,
            scoring_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
                "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
            },
        )
        self.assertEqual(
            get_latest_supplemental_status_map(company=other),
            {},
        )
        self.assertIsNone(get_latest_pilot_gate_eval(company=other))

    def test_readiness_empty_map_does_not_fall_through_to_db(self):
        score = self._dcs_score()
        evaluate_pilot_gates(
            company=self.company,
            check_ids=["CI-08", "CC-06"],
            data_run_id=score.pk,
            scoring_snapshot={
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {"manago_ai": {"status": "connected"}},
                "gate_inputs": {"manago_contacts": self._slice_a_contacts_pass()},
            },
        )
        # Explicit empty map must not reload store PASS results.
        row = supplemental_readiness_for_use_case(
            use_case_id="UC-02",
            status_by_check_id={},
            company=self.company,
        )
        self.assertFalse(row["supplemental_ready"])
        self.assertEqual(set(row["not_evaluated"]), {"CI-08", "CC-06"})

    def test_readiness_unknown_blocks(self):
        row = supplemental_readiness_for_use_case(
            use_case_id="UC-02",
            status_by_check_id={
                "CI-08": STATUS_PASS,
                "CC-06": STATUS_UNKNOWN,
            },
        )
        self.assertFalse(row["supplemental_ready"])
        self.assertEqual(
            row["blocked_by"],
            [{"check_id": "CC-06", "status": STATUS_UNKNOWN}],
        )

    def test_empty_use_case_ids_skips(self):
        out = evaluate_pilot_gates(
            company=self.company,
            use_case_ids=[],
        )
        self.assertTrue(out.skipped)
        self.assertEqual(out.skip_reason, "empty_check_set")
