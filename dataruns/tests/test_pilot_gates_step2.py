"""DCS-09 Step 2 — pilot gate eval persistence (DataRun)."""

from __future__ import annotations

from django.test import TestCase

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.pilot_gates.contract import (
    GATE_CATALOG_VERSION,
    PILOT_GATE_EVAL_KIND,
    PILOT_SUPPLEMENTAL_SCOPE,
)
from dataruns.dcs.pilot_gates.store import (
    PILOT_GATE_EVAL_DATA_RUN_NAME,
    PilotGateStoreError,
    get_latest_pilot_gate_eval,
    get_latest_supplemental_status_map,
    save_pilot_gate_eval,
)
from dataruns.dcs.worklist import get_latest_terminal_dcs_run
from dataruns.models import DataRun
from tenants.models import Company, Tenant


class PilotGatesStep2StoreTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PG S2", slug="pg-s2")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S2 Co",
            domain="pg-s2.example.com",
        )
        self.other = Company.objects.create(
            tenant=self.tenant,
            name="PG S2 Other",
            domain="pg-s2-other.example.com",
        )

    def _dcs_score(self, *, company: Company | None = None) -> DataRun:
        company = company or self.company
        return DataRun.objects.create(
            tenant=company.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(company.id),
                "headline_score": 80,
                "check_results": [{"check_id": "CC-03", "status": "PASS"}],
            },
        )

    def test_save_and_load_latest_envelope(self):
        score = self._dcs_score()
        bundle = save_pilot_gate_eval(
            company=self.company,
            results=[
                {
                    "check_id": "CI-08",
                    "status": "PASS",
                    "evidence": [],
                },
                {
                    "check_id": "CC-06",
                    "status": "FAIL",
                    "severity": "Medium",
                    "evidence": [{"source": "test"}],
                },
            ],
            data_run_id_score=score.pk,
            erp_in_scope=False,
        )
        self.assertEqual(bundle.scope, PILOT_SUPPLEMENTAL_SCOPE)
        self.assertEqual(bundle.gate_catalog_version, GATE_CATALOG_VERSION)
        self.assertEqual(bundle.data_run_id_score, score.pk)
        self.assertEqual(bundle.status_by_check_id["CI-08"], "PASS")
        self.assertEqual(bundle.status_by_check_id["CC-06"], "FAIL")
        self.assertEqual(len(bundle.results), 2)

        loaded = get_latest_pilot_gate_eval(company=self.company)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.data_run_id, bundle.data_run_id)
        self.assertEqual(loaded.to_dict()["count"], 2)
        for row in loaded.results:
            self.assertIn("required_by", row)
            self.assertIn("evaluated_at", row)
            self.assertIn("severity", row)

        status_map = get_latest_supplemental_status_map(company=self.company)
        self.assertEqual(status_map, {"CI-08": "PASS", "CC-06": "FAIL"})

        data_run = DataRun.objects.get(pk=bundle.data_run_id)
        self.assertEqual(data_run.name, PILOT_GATE_EVAL_DATA_RUN_NAME)
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)
        self.assertEqual(data_run.metadata["kind"], PILOT_GATE_EVAL_KIND)
        self.assertEqual(data_run.metadata["scope"], PILOT_SUPPLEMENTAL_SCOPE)

    def test_merge_partial_eval_preserves_prior_checks(self):
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ],
        )
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "SP-10", "status": "FAIL"}],
        )
        loaded = get_latest_pilot_gate_eval(company=self.company)
        assert loaded is not None
        self.assertEqual(
            loaded.status_by_check_id,
            {"CC-06": "PASS", "CI-08": "PASS", "SP-10": "FAIL"},
        )
        self.assertEqual(len(loaded.results), 3)

    def test_replace_without_merge(self):
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ],
        )
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "SP-10", "status": "WARN"}],
            merge_with_previous=False,
        )
        loaded = get_latest_pilot_gate_eval(company=self.company)
        assert loaded is not None
        self.assertEqual(loaded.status_by_check_id, {"SP-10": "WARN"})

    def test_tenant_company_isolation(self):
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "CI-08", "status": "PASS"}],
        )
        save_pilot_gate_eval(
            company=self.other,
            results=[{"check_id": "CI-08", "status": "FAIL"}],
        )
        a = get_latest_supplemental_status_map(company=self.company)
        b = get_latest_supplemental_status_map(company=self.other)
        self.assertEqual(a, {"CI-08": "PASS"})
        self.assertEqual(b, {"CI-08": "FAIL"})
        self.assertIsNotNone(get_latest_pilot_gate_eval(company=self.company))
        self.assertIsNotNone(get_latest_pilot_gate_eval(company=self.other))

    def test_rejects_unknown_check_and_bad_status(self):
        with self.assertRaises(PilotGateStoreError):
            save_pilot_gate_eval(
                company=self.company,
                results=[{"check_id": "CC-03", "status": "PASS"}],
            )
        with self.assertRaises(PilotGateStoreError):
            save_pilot_gate_eval(
                company=self.company,
                results=[{"check_id": "CI-08", "status": "READY"}],
            )

    def test_does_not_pollute_dcs_score_latest(self):
        score = self._dcs_score()
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "CI-08", "status": "PASS"}],
            data_run_id_score=score.pk,
        )
        latest_dcs = get_latest_terminal_dcs_run(company=self.company)
        self.assertIsNotNone(latest_dcs)
        assert latest_dcs is not None
        self.assertEqual(latest_dcs.pk, score.pk)
        self.assertEqual(latest_dcs.metadata["kind"], DCS_SCORE_KIND)
        # Pilot eval runs must not appear as DCS score runs.
        self.assertEqual(
            DataRun.objects.filter(
                tenant=self.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
                metadata__kind=DCS_SCORE_KIND,
                metadata__company_id=str(self.company.id),
            ).count(),
            1,
        )

    def test_empty_company_has_no_eval(self):
        self.assertIsNone(get_latest_pilot_gate_eval(company=self.company))
        self.assertEqual(get_latest_supplemental_status_map(company=self.company), {})

    def test_merge_preserves_score_link_and_erp_flag(self):
        score = self._dcs_score()
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "CI-08", "status": "PASS"}],
            data_run_id_score=score.pk,
            erp_in_scope=True,
        )
        # Partial follow-up omits score + erp — must not wipe prior metadata.
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "CC-06", "status": "PASS"}],
        )
        loaded = get_latest_pilot_gate_eval(company=self.company)
        assert loaded is not None
        self.assertEqual(loaded.data_run_id_score, score.pk)
        self.assertTrue(loaded.erp_in_scope)
        self.assertEqual(
            loaded.status_by_check_id,
            {"CC-06": "PASS", "CI-08": "PASS"},
        )

    def test_rejects_empty_results_and_bad_severity(self):
        with self.assertRaises(PilotGateStoreError):
            save_pilot_gate_eval(company=self.company, results=[])
        with self.assertRaises(PilotGateStoreError):
            save_pilot_gate_eval(
                company=self.company,
                results=[{"check_id": "CI-08", "status": "PASS", "severity": "CRITICAL"}],
            )

    def test_failed_eval_ignored_for_latest(self):
        save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "CI-08", "status": "PASS"}],
        )
        good = get_latest_pilot_gate_eval(company=self.company)
        assert good is not None
        DataRun.objects.create(
            tenant=self.tenant,
            name=PILOT_GATE_EVAL_DATA_RUN_NAME,
            status=DataRun.Status.FAILED,
            metadata={
                "kind": PILOT_GATE_EVAL_KIND,
                "scope": PILOT_SUPPLEMENTAL_SCOPE,
                "company_id": str(self.company.id),
                "results": [{"check_id": "CI-08", "status": "FAIL"}],
                "count": 1,
            },
        )
        loaded = get_latest_pilot_gate_eval(company=self.company)
        assert loaded is not None
        self.assertEqual(loaded.data_run_id, good.data_run_id)
        self.assertEqual(loaded.status_by_check_id["CI-08"], "PASS")

    def test_ci08_required_by_filled_from_master(self):
        bundle = save_pilot_gate_eval(
            company=self.company,
            results=[{"check_id": "ci-08", "status": "pass"}],
        )
        row = next(r for r in bundle.results if r["check_id"] == "CI-08")
        self.assertEqual(row["required_by"], ["UC-02"])
        self.assertEqual(row["severity"], "Medium")
        self.assertEqual(row["status"], "PASS")
