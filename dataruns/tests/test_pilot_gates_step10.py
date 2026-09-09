"""DCS-09 Step 10 — BE acceptance matrix (PRD §10).

Authoritative sign-off gate for backend DCS-09. Deeper unit coverage lives in
steps 0–9; this module proves the PRD §10 checklist end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.assemble import AssembleValidationError, assemble_dcs_score
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.executors.registry import registered_check_ids
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.pilot_gates.context import build_supplemental_gate_context
from dataruns.dcs.pilot_gates.contract import (
    EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
    STATUS_NOT_CONNECTED,
    SUPPLEMENTAL_CHECK_IDS,
)
from dataruns.dcs.pilot_gates.evaluate import evaluate_pilot_gates
from dataruns.dcs.pilot_gates.executors import (
    REASON_ERP_OUT_OF_SCOPE,
    clear_supplemental_executor_registry,
    run_supplemental_check,
)
from dataruns.dcs.pilot_gates.store import (
    get_latest_pilot_gate_eval,
    save_pilot_gate_eval,
)
from dataruns.dcs.pilot_gates.views import (
    PilotGatesEvaluateView,
    PilotGatesMasterView,
    PilotSupplementalReadinessView,
)
from dataruns.dcs.types import CheckResult
from dataruns.dcs.worklist import build_worklist_payload, get_latest_terminal_dcs_run
from dataruns.models import DataRun
from dataruns.use_cases.constants import (
    DEFAULT_MANIFEST_REL,
    SUPPLEMENTAL_PREFLIGHT_CHECKS,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.recommend import (
    STATUS_BLOCKED_CHECKS,
    STATUS_READY,
    STATUS_READY_PROVISIONAL,
    evaluate_pilot,
    resolve_recommendation_context,
)
from dataruns.use_cases.views import UseCaseBuildPackageView
from tenants.models import Company, Tenant, User


class PilotGatesStep10StaticAcceptanceTests(SimpleTestCase):
    """PRD §10 — static 12 IDs match pack + constants."""

    def test_twelve_ids_match_pack_and_constants(self):
        self.assertEqual(len(SUPPLEMENTAL_PREFLIGHT_CHECKS), 12)
        self.assertEqual(EXPECTED_SUPPLEMENTAL_CHECK_COUNT, 12)
        self.assertEqual(
            set(SUPPLEMENTAL_CHECK_IDS),
            set(SUPPLEMENTAL_PREFLIGHT_CHECKS),
        )
        manifest_path = Path(settings.BASE_DIR) / DEFAULT_MANIFEST_REL
        self.assertTrue(manifest_path.is_file(), msg=str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = manifest.get("supplemental_preflight_checks") or []
        self.assertEqual(set(listed), set(SUPPLEMENTAL_PREFLIGHT_CHECKS))

    def test_zero_overlap_with_headline_42(self):
        master = load_check_master_from_json()
        headline_ids = {c.check_id for c in master.checks}
        self.assertEqual(len(headline_ids), 42)
        self.assertEqual(headline_ids & set(SUPPLEMENTAL_CHECK_IDS), set())
        self.assertEqual(registered_check_ids() & set(SUPPLEMENTAL_CHECK_IDS), set())

    def test_pilot_gate_api_routes_mounted(self):
        for name in (
            "dcs-pilot-gates-master",
            "dcs-pilot-gates-latest",
            "dcs-pilot-gates-evaluate",
        ):
            with self.subTest(name=name):
                self.assertTrue(reverse(name).endswith("/"))
        readiness = reverse(
            "dcs-pilot-supplemental-readiness",
            kwargs={"use_case_id": "UC-02"},
        )
        self.assertIn("UC-02", readiness)


class PilotGatesStep10AssembleIsolationTests(SimpleTestCase):
    """PRD §10 — isolation from assemble / headline 42."""

    def test_assemble_rejects_supplemental_and_stays_42(self):
        master = load_check_master_from_json()
        results = [
            CheckResult(check_id=c.check_id, status="PASS") for c in master.checks
        ]
        run = assemble_dcs_score(results, erp_in_scope=False, master=master)
        self.assertEqual(len(run.check_result_refs), 42)
        self.assertEqual(
            set(run.check_result_refs) & set(SUPPLEMENTAL_CHECK_IDS),
            set(),
        )
        with self.assertRaises(AssembleValidationError):
            assemble_dcs_score(
                results + [CheckResult(check_id="CI-08", status="PASS")],
                erp_in_scope=False,
                master=master,
            )


class PilotGatesStep10AcceptanceTests(TestCase):
    """PRD §10 — ready / fail / provisional / ERP-out / evaluate API."""

    def setUp(self):
        clear_supplemental_executor_registry()
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="PG S10", slug="pg-s10")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S10 Co",
            domain="pg-s10.example.com",
        )
        self.analyst = User.objects.create_user(
            email="pg-s10@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.ANALYST,
        )
        self.pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .prefetch_related("stage_maps")
            .get(use_case_id="UC-02")
        )
        self.factory = APIRequestFactory()

    def tearDown(self):
        clear_supplemental_executor_registry()

    def _dcs(
        self,
        *,
        score: float = 80.0,
        checks: list[dict] | None = None,
        snapshot: dict | None = None,
    ) -> DataRun:
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
            run_snapshot=snapshot
            if snapshot is not None
            else {
                "as_of": "2026-06-01T00:00:00Z",
                "connectors": {
                    "manago_ai": {"status": "connected"},
                    "shopify": {"status": "connected"},
                },
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

    def test_evaluate_does_not_change_headline_score_or_worklist_pointer(self):
        score = self._dcs(score=81.5)
        before_meta = dict(score.metadata or {})
        before_snapshot = dict(score.run_snapshot or {})
        before_terminal = get_latest_terminal_dcs_run(company=self.company)
        before_worklist = build_worklist_payload(company=self.company)

        out = evaluate_pilot_gates(
            company=self.company,
            use_case_ids=["UC-02"],
            data_run_id=score.pk,
            erp_in_scope=False,
        )
        self.assertFalse(out.skipped)
        self.assertEqual(set(out.check_ids), {"CI-08", "CC-06"})

        score.refresh_from_db()
        self.assertEqual(score.metadata.get("kind"), DCS_SCORE_KIND)
        self.assertEqual(score.metadata.get("headline_score"), 81.5)
        self.assertEqual(
            score.metadata.get("check_results"),
            before_meta.get("check_results"),
        )
        self.assertEqual(score.run_snapshot, before_snapshot)

        after_terminal = get_latest_terminal_dcs_run(company=self.company)
        self.assertEqual(
            before_terminal.pk if before_terminal else None,
            after_terminal.pk if after_terminal else None,
        )
        self.assertEqual(after_terminal.pk, score.pk)

        after_worklist = build_worklist_payload(company=self.company)
        self.assertEqual(after_worklist["data_run_id"], before_worklist["data_run_id"])
        self.assertEqual(after_worklist["headline_score"], 81.5)
        issue_ids = {
            str(issue.get("check_id") or "")
            for issue in (after_worklist.get("issues") or [])
        }
        self.assertEqual(issue_ids & set(SUPPLEMENTAL_CHECK_IDS), set())

        # Supplemental eval is a separate DataRun — not the DCS score.
        bundle = get_latest_pilot_gate_eval(company=self.company)
        self.assertIsNotNone(bundle)
        self.assertNotEqual(bundle.data_run_id, score.pk)
        self.assertEqual(bundle.data_run_id_score, score.pk)

    def test_uc02_ready_when_ci08_cc06_pass(self):
        self._dcs()
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ]
        )
        row = evaluate_pilot(
            self.pilot,
            resolve_recommendation_context(company=self.company),
        )
        self.assertEqual(row["status"], STATUS_READY)
        self.assertFalse(row["provisional_supplemental"])
        self.assertEqual(row["blockers"], [])
        self.assertEqual(row["supplemental_status"].get("CI-08"), "PASS")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "PASS")

    def test_dcs_injected_supplementals_do_not_unlock_ready(self):
        # Recommend merge lock: store-only; DCS metadata cannot fake ready.
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
        self.assertEqual(ctx.supplemental_results, {})
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertTrue(row["provisional_supplemental"])
        self.assertEqual(row["supplemental_status"].get("CI-08"), "not_evaluated")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "not_evaluated")

    def test_supplemental_fail_blocked_checks_and_generate_locked(self):
        self._dcs()
        self._af()
        self._save_supplemental(
            [
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ]
        )
        row = evaluate_pilot(
            self.pilot,
            resolve_recommendation_context(company=self.company),
        )
        self.assertEqual(row["status"], STATUS_BLOCKED_CHECKS)
        self.assertFalse(row["provisional_supplemental"])
        self.assertTrue(any(b.get("check_id") == "CC-06" for b in row["blockers"]))

        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "blocked_checks")

    def test_unevaluated_still_ready_provisional(self):
        self._dcs()
        self._af()
        row = evaluate_pilot(
            self.pilot,
            resolve_recommendation_context(company=self.company),
        )
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertTrue(row["provisional_supplemental"])
        self.assertEqual(row["supplemental_status"].get("CI-08"), "not_evaluated")
        self.assertEqual(row["supplemental_status"].get("CC-06"), "not_evaluated")

    def test_erp_out_br09_pt06_not_connected(self):
        ctx = build_supplemental_gate_context(
            company=self.company,
            erp_in_scope=False,
        )
        for check_id in ("BR-09", "PT-06"):
            with self.subTest(check_id=check_id):
                result = run_supplemental_check(check_id, context=ctx)
                self.assertEqual(result.status, STATUS_NOT_CONNECTED)
                self.assertEqual(result.reason_code, REASON_ERP_OUT_OF_SCOPE)

        # Orchestration path must persist the same honesty.
        score = self._dcs()
        out = evaluate_pilot_gates(
            company=self.company,
            check_ids=["BR-09", "PT-06"],
            data_run_id=score.pk,
            erp_in_scope=False,
        )
        self.assertEqual(out.status_by_check_id["BR-09"], STATUS_NOT_CONNECTED)
        self.assertEqual(out.status_by_check_id["PT-06"], STATUS_NOT_CONNECTED)

    def test_evaluate_api_and_recommend_merge(self):
        score = self._dcs()
        self._af()

        master_req = self.factory.get("/api/v1/dcs/pilot-gates/master/")
        force_authenticate(master_req, user=self.analyst)
        master = PilotGatesMasterView.as_view()(master_req)
        self.assertEqual(master.status_code, 200)
        self.assertEqual(master.data["count"], 12)
        self.assertEqual(
            {c["check_id"] for c in master.data["checks"]},
            set(SUPPLEMENTAL_PREFLIGHT_CHECKS),
        )

        eval_req = self.factory.post(
            "/api/v1/dcs/pilot-gates/evaluate/",
            {
                "use_case_ids": ["UC-02"],
                "data_run_id": score.id,
                "erp_in_scope": False,
            },
            format="json",
        )
        force_authenticate(eval_req, user=self.analyst)
        evaluated = PilotGatesEvaluateView.as_view()(eval_req)
        self.assertEqual(evaluated.status_code, 200)
        self.assertFalse(evaluated.data["skipped"])
        self.assertEqual(evaluated.data["status_by_check_id"]["CI-08"], "PASS")
        self.assertEqual(evaluated.data["status_by_check_id"]["CC-06"], "PASS")

        ready_req = self.factory.get("/api/v1/dcs/pilots/UC-02/readiness/")
        force_authenticate(ready_req, user=self.analyst)
        readiness = PilotSupplementalReadinessView.as_view()(
            ready_req, use_case_id="UC-02"
        )
        self.assertEqual(readiness.status_code, 200)
        self.assertTrue(readiness.data["supplemental_ready"])
        self.assertEqual(readiness.data["blocked_by"], [])

        row = evaluate_pilot(
            self.pilot,
            resolve_recommendation_context(company=self.company),
        )
        self.assertEqual(row["status"], STATUS_READY)
        self.assertFalse(row["provisional_supplemental"])

        gen = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(gen, user=self.analyst)
        package = UseCaseBuildPackageView.as_view()(gen, use_case_id="UC-02")
        self.assertEqual(package.status_code, 201)
        self.assertFalse(package.data["provisional_supplemental"])
