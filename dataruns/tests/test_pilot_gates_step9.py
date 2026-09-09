"""DCS-09 Step 9 — QA + build_package regression (provisional / Generate lock).

Production wiring lives in recommend → build_package → qa_normalize → qa_run.
This module locks the Step 9 acceptance matrix; deeper unit coverage stays in
test_qa_normalize_step2.py, test_qa_evaluators_step3.py, and
test_use_case_build_package.py.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from dataruns.models import DataRun
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot, WorkflowBuildPackage
from dataruns.use_cases.qa_normalize import data_gates_blocking_checks
from dataruns.use_cases.qa_run import QA_STATUS_FAIL, run_qa_for_package
from dataruns.use_cases.recommend import (
    STATUS_READY,
    STATUS_READY_PROVISIONAL,
    evaluate_pilot,
    resolve_recommendation_context,
)
from dataruns.use_cases.views import UseCaseBuildPackageView
from tenants.models import Company, Tenant, User


class PilotGatesStep9QaBuildPackageTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="PG S9", slug="pg-s9")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S9 Co",
            domain="pg-s9.example.com",
        )
        self.analyst = User.objects.create_user(
            email="pg-s9@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.ANALYST,
        )
        self.pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .get(use_case_id="UC-02")
        )
        self.factory = APIRequestFactory()

    def _seed_ready_hard_gates(self) -> None:
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 80.0,
                "check_results": [{"check_id": "CC-03", "status": "PASS"}],
            },
        )
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="Architecture Assessment",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.AUGMENT,
            probe_coverage={"lifecycle_gaps": []},
        )

    def _persist_package(self, payload: dict) -> WorkflowBuildPackage:
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=payload,
            provisional_supplemental=bool(payload.get("provisional_supplemental")),
            blueprint_content_hash=self.pilot.blueprint.content_hash,
            package_content_hash=(payload.get("hashes") or {}).get(
                "package_content_hash", "c" * 64
            ),
            generated_by=self.analyst,
        )
        payload = dict(payload)
        payload["package_id"] = str(record.id)
        record.payload = payload
        record.save(update_fields=["payload"])
        return (
            WorkflowBuildPackage.objects.select_related("pilot", "pilot__blueprint")
            .get(pk=record.pk)
        )

    def test_unevaluated_still_ready_provisional(self):
        self._seed_ready_hard_gates()
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY_PROVISIONAL)
        self.assertTrue(row["provisional_supplemental"])

        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["provisional_supplemental"])
        blocking = data_gates_blocking_checks(response.data["gates_snapshot"])
        self.assertEqual(blocking, [])

    def test_all_supplementals_pass_clears_provisional(self):
        self._seed_ready_hard_gates()
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "PASS"},
            ],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY)
        self.assertFalse(row["provisional_supplemental"])

        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["provisional_supplemental"])
        self.assertFalse(response.data["gates_snapshot"]["provisional_supplemental"])
        self.assertEqual(response.data["gates_snapshot"]["checks"]["CC-06"], "PASS")
        self.assertEqual(
            data_gates_blocking_checks(response.data["gates_snapshot"]),
            [],
        )

    def test_supplemental_fail_locks_generate(self):
        self._seed_ready_hard_gates()
        save_pilot_gate_eval(
            company=self.company,
            results=[
                {"check_id": "CI-08", "status": "PASS"},
                {"check_id": "CC-06", "status": "FAIL"},
            ],
            erp_in_scope=False,
            merge_with_previous=False,
        )
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "blocked_checks")
        self.assertTrue(
            any(b.get("check_id") == "CC-06" for b in response.data["blockers"])
        )

    def test_qa_data_gates_pass_ok_on_provisional_package(self):
        self._seed_ready_hard_gates()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        response = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["provisional_supplemental"])

        package = WorkflowBuildPackage.objects.get(pk=response.data["package_id"])
        outcome = run_qa_for_package(package=package, created_by=self.analyst)
        data_gates = next(
            r
            for r in outcome.payload["hard_tests"]
            if r["test_id"] == "data_gates_pass"
        )
        self.assertEqual(data_gates["status"], "PASS")

    def test_qa_data_gates_pass_fails_when_supplemental_fail_in_package(self):
        # FAIL blocks Generate, so craft snapshot directly (defense-in-depth).
        self._seed_ready_hard_gates()
        request = self.factory.post("/api/v1/use-cases/UC-02/build-package/")
        force_authenticate(request, user=self.analyst)
        created = UseCaseBuildPackageView.as_view()(request, use_case_id="UC-02")
        self.assertEqual(created.status_code, 201)
        payload = dict(created.data)
        payload["gates_snapshot"] = {
            **payload.get("gates_snapshot", {}),
            "checks": {
                **(payload.get("gates_snapshot") or {}).get("checks", {}),
                "CC-06": "FAIL",
                "CI-08": "PASS",
            },
            "provisional_supplemental": True,
        }
        payload["provisional_supplemental"] = True
        package = self._persist_package(payload)
        outcome = run_qa_for_package(package=package, created_by=self.analyst)
        self.assertEqual(outcome.payload["status"], QA_STATUS_FAIL)
        fail_ids = [
            row["test_id"]
            for row in outcome.payload["hard_tests"]
            if row["status"] == "FAIL"
        ]
        self.assertIn("data_gates_pass", fail_ids)
