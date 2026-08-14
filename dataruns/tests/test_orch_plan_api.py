"""PRD-ORCH-01 Phase C — GET /api/v1/orchestration/plan/."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.orchestration.plan import build_plan
from dataruns.orchestration.views import OrchestrationPlanView
from tenants.models import Company, Tenant, User


class OrchPlanApiTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Orch Co", slug="orch-plan")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Orch Co",
            domain="orch-plan.example.com",
        )
        self.viewer = User.objects.create_user(
            email="viewer@orch-plan.example.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        self.admin = User.objects.create_user(
            email="admin@orch-plan.example.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()

    def _create_dcs_run(self, *, checks: list[dict], score: float = 70.0) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": score,
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": score,
                    "check_results": checks,
                },
                "check_results": checks,
            },
        )

    def test_no_dcs_returns_empty_reason(self):
        payload = build_plan(company=self.company)
        self.assertEqual(payload["reason"], "no_dcs")
        self.assertEqual(payload["tasks"], [])
        self.assertIsNone(payload["sources"]["dcs_data_run_id"])
        self.assertEqual(payload["summary"]["task_count"], 0)

    def test_scored_no_issues(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-04",
                    "status": "PASS",
                    "severity": "low",
                    "message": "ok",
                }
            ]
        )
        payload = build_plan(company=self.company)
        self.assertEqual(payload["reason"], "no_open_issues")
        self.assertEqual(payload["tasks"], [])
        self.assertIsNotNone(payload["sources"]["dcs_data_run_id"])

    def test_plan_emits_ranked_fix_tasks(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "critical",
                    "message": "Missing purchases",
                    "provenance": {
                        "revenue_impact": 12000.0,
                        "revenue_currency": "EUR",
                    },
                },
                {
                    "check_id": "CI-01",
                    "status": "WARN",
                    "severity": "medium",
                    "message": "Soft identity gap",
                    "provenance": {
                        "revenue_impact": 100.0,
                        "revenue_currency": "EUR",
                    },
                },
                {
                    "check_id": None,
                    "status": "FAIL",
                    "severity": "critical",
                    "message": "Synthetic should skip",
                },
            ]
        )
        payload = build_plan(company=self.company)
        self.assertIsNone(payload["reason"])
        self.assertEqual(payload["summary"]["task_count"], 2)
        self.assertEqual(payload["summary"]["fix_count"], 2)
        task_ids = [t["task_id"] for t in payload["tasks"]]
        self.assertEqual(task_ids, ["FIX-LE-05", "FIX-CI-01"])
        top = payload["tasks"][0]
        self.assertEqual(top["task_type"], "FIX")
        self.assertEqual(top["status"], "READY")
        self.assertEqual(top["href"], "/fix?issue=LE-05")
        self.assertIn("priority_inputs", top)
        self.assertIn("priority_explain", top)
        self.assertIn(top["priority_class"], ("P0", "P1", "P2"))
        self.assertGreaterEqual(top["priority_score"], payload["tasks"][1]["priority_score"])
        self.assertNotIn("evidence", top)
        self.assertIsNone(top["wave"])
        self.assertEqual(top["depends_on"], [])

    def test_api_viewer_ok(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "high",
                    "message": "Issue",
                    "provenance": {"revenue_impact": 500.0, "revenue_currency": "USD"},
                }
            ]
        )
        request = self.factory.get("/api/v1/orchestration/plan/")
        force_authenticate(request, user=self.viewer)
        response = OrchestrationPlanView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["fix_count"], 1)
        self.assertEqual(response.data["tasks"][0]["check_id"], "LE-05")

    def test_api_unauthenticated(self):
        request = self.factory.get("/api/v1/orchestration/plan/")
        response = OrchestrationPlanView.as_view()(request)
        self.assertIn(response.status_code, (401, 403))

    def test_api_url_resolves(self):
        from django.urls import reverse

        self.assertEqual(
            reverse("orchestration-plan"),
            "/api/v1/orchestration/plan/",
        )

    def test_failed_run_only_synthetic_is_no_open_issues(self):
        """Synthetic failed-run row has null check_id → skipped, not 500."""
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.FAILED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "error": "scoring blew up",
                "check_results": [],
            },
        )
        payload = build_plan(company=self.company)
        self.assertEqual(payload["reason"], "no_open_issues")
        self.assertEqual(payload["tasks"], [])
        self.assertIsNotNone(payload["sources"]["dcs_data_run_id"])

    def test_sort_key_tolerates_bad_score(self):
        from dataruns.orchestration.scoring import sort_tasks_by_priority

        ordered = sort_tasks_by_priority(
            [
                {"task_id": "FIX-B", "priority_score": float("nan"), "priority_class": "P0"},
                {"task_id": "FIX-A", "priority_score": 2.0, "priority_class": "P0"},
            ]
        )
        self.assertEqual(ordered[0]["task_id"], "FIX-A")
