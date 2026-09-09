"""DCS-09 Step 6 — recommend.py merges supplemental store (not DCS inject)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from dataruns.models import DataRun
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.recommend import (
    STATUS_BLOCKED_CHECKS,
    STATUS_BLOCKED_DCS,
    STATUS_READY,
    STATUS_READY_PROVISIONAL,
    build_gates_snapshot,
    evaluate_pilot,
    resolve_recommendation_context,
)
from tenants.models import Company, Tenant


class PilotGatesStep6RecommendMergeTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="PG S6", slug="pg-s6")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S6 Co",
            domain="pg-s6.example.com",
        )
        self.pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .prefetch_related("stage_maps")
            .get(use_case_id="UC-02")
        )

    def _dcs(self, *, score: float = 80.0, checks: list[dict] | None = None) -> DataRun:
        check_rows = checks if checks is not None else [
            {"check_id": "CC-03", "status": "PASS"}
        ]
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": score,
                "check_results": check_rows,
                "dcs_run": {"headline_score": score, "check_results": check_rows},
            },
        )

    def _af(self) -> ArchitectureAssessment:
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="Architecture Assessment",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        return ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.AUGMENT,
            probe_coverage={"lifecycle_gaps": [], "lifecycle_gap_count": 0},
        )

    def _save_supplemental(self, results: list[dict]) -> None:
        save_pilot_gate_eval(
            company=self.company,
            results=results,
            erp_in_scope=False,
            merge_with_previous=False,
        )

    def test_uc02_ready_when_store_ci08_cc06_pass(self):
        self._dcs()
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ]
        )
        ctx = resolve_recommendation_context(company=self.company)
        self.assertEqual(ctx.supplemental_results.get("CI-08"), "PASS")
        self.assertEqual(ctx.supplemental_results.get("CC-06"), "PASS")
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY)
        self.assertFalse(row["provisional_supplemental"])
        self.assertEqual(row["supplemental_status"].get("CI-08"), "PASS")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "PASS")
        self.assertEqual(row["blockers"], [])

    def test_uc02_blocked_when_store_supplemental_fail(self):
        self._dcs()
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ]
        )
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_CHECKS)
        self.assertFalse(row["provisional_supplemental"])
        self.assertTrue(
            any(b.get("check_id") == "CC-06" for b in row["blockers"])
        )
        # DCS-09 FE lock: supplemental blockers must not deep-link to score tiles.
        for blocker in row["blockers"]:
            if blocker.get("check_id") == "CC-06":
                self.assertFalse(blocker.get("href"))
        for check in row["check_results"]:
            if check.get("check_id") == "CC-06":
                self.assertNotIn("href", check)

    def test_uc02_ready_provisional_when_no_eval(self):
        self._dcs()
        self._af()
        ctx = resolve_recommendation_context(company=self.company)
        self.assertEqual(ctx.supplemental_results, {})
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertTrue(row["provisional_supplemental"])
        self.assertEqual(row["supplemental_status"].get("CI-08"), "not_evaluated")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "not_evaluated")

    def test_dcs_injected_supplementals_do_not_unlock_ready(self):
        self._dcs(
            checks=[
                {"check_id": "CC-03", "status": "PASS"},
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ]
        )
        self._af()
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        # Even if DCS metadata lists them, recommend uses store only.
        self.assertEqual(ctx.supplemental_results, {})
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertEqual(row["supplemental_status"].get("CI-08"), "not_evaluated")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "not_evaluated")

    def test_partial_store_keeps_missing_provisional(self):
        self._dcs()
        self._af()
        self._save_supplemental([{"check_id": "CI-08", "status": "PASS"}])
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertTrue(row["provisional_supplemental"])
        self.assertEqual(row["supplemental_status"].get("CI-08"), "PASS")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "not_evaluated")

    def test_gates_snapshot_reads_supplemental_store(self):
        self._dcs()
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "WARN"},
            ]
        )
        ctx = resolve_recommendation_context(company=self.company)
        snap = build_gates_snapshot(
            gates={"min_dcs": 70, "gating_check_ids": ["CC-03", "CI-08", "CC-06"]},
            ctx=ctx,
            provisional_supplemental=False,
        )
        self.assertEqual(snap["checks"]["CC-03"], "PASS")
        self.assertEqual(snap["checks"]["CI-08"], "PASS")
        self.assertEqual(snap["checks"]["CC-06"], "WARN")

    def test_uc02_blocked_when_store_unknown(self):
        self._dcs()
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "UNKNOWN"},
                {"check_id": "CC-06", "status": "PASS"},
            ]
        )
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_CHECKS)
        self.assertTrue(any(b.get("check_id") == "CI-08" for b in row["blockers"]))

    def test_blocked_dcs_still_exposes_supplemental_status(self):
        self._dcs(score=50.0)
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ]
        )
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_DCS)
        self.assertEqual(row["supplemental_status"].get("CI-08"), "PASS")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "FAIL")

    def test_evaluate_then_recommend_ready_e2e(self):
        """Step 5 evaluate persist → Step 6 recommend merge → ready."""
        from dataruns.dcs.pilot_gates.evaluate import evaluate_pilot_gates
        from dataruns.dcs.pilot_gates.executors import clear_supplemental_executor_registry

        clear_supplemental_executor_registry()
        score = self._dcs()
        self._af()
        snapshot = {
            "as_of": "2026-06-01T00:00:00Z",
            "connectors": {"manago_ai": {"status": "connected"}},
            "gate_inputs": {
                "manago_contacts": [
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
            },
        }
        out = evaluate_pilot_gates(
            company=self.company,
            use_case_ids=["UC-02"],
            data_run_id=score.id,
            scoring_snapshot=snapshot,
            erp_in_scope=False,
        )
        self.assertEqual(out.status_by_check_id.get("CI-08"), "PASS")
        self.assertEqual(out.status_by_check_id.get("CC-06"), "PASS")
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY)
        self.assertFalse(row["provisional_supplemental"])
        clear_supplemental_executor_registry()
