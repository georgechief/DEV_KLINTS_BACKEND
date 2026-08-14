"""Tests for PRD-UC-01 Phase B — recommendations / gate evaluation."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot
from dataruns.use_cases.recommend import (
    STATUS_BLOCKED_CHECKS,
    STATUS_BLOCKED_DCS,
    STATUS_BLOCKED_MODE,
    STATUS_READY,
    build_recommendations_payload,
    evaluate_pilot,
    resolve_recommendation_context,
)
from dataruns.use_cases.views import (
    UseCaseRecommendationDetailView,
    UseCaseRecommendationsView,
)
from tenants.models import Company, Tenant, User


class UseCaseRecommendationEvalTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="UC Rec", slug="uc-rec")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="UC Rec Co",
            domain="uc-rec.example.com",
        )
        self.pilot = (
            UseCasePilot.objects.select_related("blueprint")
            .prefetch_related("stage_maps")
            .get(use_case_id="UC-02")
        )

    def _dcs(
        self,
        *,
        score: float | None,
        checks: list[dict],
        status=DataRun.Status.SUCCEEDED,
    ) -> DataRun:
        meta: dict = {
            "kind": DCS_SCORE_KIND,
            "company_id": str(self.company.id),
            "check_results": checks,
        }
        if score is not None:
            meta["headline_score"] = score
            meta["dcs_run"] = {"headline_score": score, "check_results": checks}
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=status,
            metadata=meta,
        )

    def _af(
        self,
        *,
        mode: str | None = ArchitectureAssessment.Mode.AUGMENT,
        gaps: list[str] | None = None,
        status=ArchitectureAssessment.Status.SUCCEEDED,
    ) -> ArchitectureAssessment:
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="Architecture Assessment",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        probe = {
            "lifecycle_gaps": [
                {"stage_id": sid, "stage": int(sid.split("_")[1]), "job": "x"}
                for sid in (gaps or [])
            ],
            "lifecycle_gap_count": len(gaps or []),
        }
        return ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            status=status,
            mode=mode,
            probe_coverage=probe,
        )

    def _uc02_pass_checks(self) -> list[dict]:
        return [
            {"check_id": "CC-03", "status": "PASS"},
            {"check_id": "CC-06", "status": "PASS"},
            {"check_id": "CI-08", "status": "PASS"},
        ]

    def test_uc02_ready_when_score_mode_and_checks_ok(self):
        self._dcs(score=75, checks=self._uc02_pass_checks())
        self._af(mode=ArchitectureAssessment.Mode.AUGMENT)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY)
        self.assertEqual(row["blockers"], [])
        self.assertFalse(row["gap_suggested"])

    def test_uc02_blocked_dcs_when_score_below_70(self):
        self._dcs(score=67, checks=self._uc02_pass_checks())
        self._af(mode=ArchitectureAssessment.Mode.AUGMENT)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_DCS)
        self.assertTrue(any(b["code"] == "min_dcs" for b in row["blockers"]))

    def test_uc02_blocked_dcs_when_no_score(self):
        self._dcs(score=None, checks=[])
        self._af(mode=ArchitectureAssessment.Mode.AUGMENT)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_DCS)

    def test_uc02_blocked_mode_when_incomplete(self):
        self._dcs(score=80, checks=self._uc02_pass_checks())
        self._af(mode=ArchitectureAssessment.Mode.INCOMPLETE)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_MODE)
        self.assertTrue(
            any(b.get("href") == "/lifecycle" for b in row["blockers"])
        )

    def test_uc02_blocked_mode_when_no_af(self):
        self._dcs(score=80, checks=self._uc02_pass_checks())
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_MODE)

    def test_uc02_blocked_checks_when_gate_fails(self):
        checks = [
            {"check_id": "CC-03", "status": "PASS"},
            {"check_id": "CC-06", "status": "FAIL"},
            {"check_id": "CI-08", "status": "PASS"},
        ]
        self._dcs(score=80, checks=checks)
        self._af(mode=ArchitectureAssessment.Mode.SELECTIVE_REBUILD)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_CHECKS)
        self.assertTrue(
            any(
                b.get("href") == "/data-consistency?issue=CC-06"
                for b in row["blockers"]
            )
        )

    def test_uc02_blocked_checks_when_gate_missing(self):
        # Only CC-03 present — CC-06 and CI-08 missing ⇒ not silent ready
        self._dcs(
            score=80,
            checks=[{"check_id": "CC-03", "status": "PASS"}],
        )
        self._af(mode=ArchitectureAssessment.Mode.REBUILD)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_CHECKS)
        codes = {b["code"] for b in row["blockers"]}
        self.assertIn("gate_not_in_latest_score", codes)

    def test_uc02_warn_treated_as_blocked_checks(self):
        checks = [
            {"check_id": "CC-03", "status": "PASS"},
            {"check_id": "CC-06", "status": "WARN"},
            {"check_id": "CI-08", "status": "PASS"},
        ]
        self._dcs(score=80, checks=checks)
        self._af(mode=ArchitectureAssessment.Mode.AUGMENT)
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_BLOCKED_CHECKS)

    def test_gap_suggested_when_stage_in_wf12_gaps(self):
        self._dcs(score=80, checks=self._uc02_pass_checks())
        self._af(
            mode=ArchitectureAssessment.Mode.AUGMENT,
            gaps=["stage_02", "stage_09"],
        )
        ctx = resolve_recommendation_context(company=self.company)
        row = evaluate_pilot(self.pilot, ctx)
        self.assertEqual(row["status"], STATUS_READY)
        self.assertTrue(row["gap_suggested"])
        self.assertIn("stage_02", row["gap_stages"])

    def test_payload_summary_and_sort_ready_gap_first(self):
        self._dcs(score=80, checks=self._uc02_pass_checks())
        # Only UC-02 gates pass; others will be blocked_checks — but score+mode OK
        # Seed enough checks so UC-02 is ready; leave others missing.
        self._af(
            mode=ArchitectureAssessment.Mode.AUGMENT,
            gaps=["stage_02"],
        )
        payload = build_recommendations_payload(company=self.company)
        self.assertEqual(payload["dcs"]["headline_score"], 80)
        self.assertEqual(payload["architecture"]["mode"], "AUGMENT")
        self.assertGreaterEqual(payload["summary"]["ready"], 1)
        first = payload["pilots"][0]
        self.assertEqual(first["use_case_id"], "UC-02")
        self.assertEqual(first["status"], STATUS_READY)
        self.assertTrue(first["gap_suggested"])


class UseCaseRecommendationsApiTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="UC API", slug="uc-api")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="UC API Co",
            domain="uc-api.example.com",
        )
        self.viewer = User.objects.create_user(
            email="uc-api@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.VIEWER,
        )
        self.factory = APIRequestFactory()

        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 67,
                "check_results": [
                    {"check_id": "CC-03", "status": "PASS"},
                    {"check_id": "CC-06", "status": "PASS"},
                    {"check_id": "CI-08", "status": "PASS"},
                ],
            },
        )
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name="AF",
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

    def test_recommendations_api_returns_pilots(self):
        request = self.factory.get("/api/v1/use-cases/recommendations/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseRecommendationsView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dcs"]["headline_score"], 67)
        self.assertEqual(len(response.data["pilots"]), 16)
        uc02 = next(p for p in response.data["pilots"] if p["use_case_id"] == "UC-02")
        self.assertEqual(uc02["status"], STATUS_BLOCKED_DCS)

    def test_recommendation_detail_api(self):
        request = self.factory.get("/api/v1/use-cases/recommendations/UC-02/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseRecommendationDetailView.as_view()(
            request, use_case_id="UC-02"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pilot"]["use_case_id"], "UC-02")
        self.assertEqual(response.data["pilot"]["status"], STATUS_BLOCKED_DCS)

    def test_recommendation_detail_unknown_404(self):
        request = self.factory.get("/api/v1/use-cases/recommendations/UC-99/")
        force_authenticate(request, user=self.viewer)
        response = UseCaseRecommendationDetailView.as_view()(
            request, use_case_id="UC-99"
        )
        self.assertEqual(response.status_code, 404)

    def test_recommendations_requires_company(self):
        orphan = User.objects.create_user(
            email="orphan@example.com",
            password="pass",
            tenant=Tenant.objects.create(name="Orphan", slug="orphan"),
            role=User.Role.VIEWER,
        )
        request = self.factory.get("/api/v1/use-cases/recommendations/")
        force_authenticate(request, user=orphan)
        response = UseCaseRecommendationsView.as_view()(request)
        self.assertEqual(response.status_code, 400)
