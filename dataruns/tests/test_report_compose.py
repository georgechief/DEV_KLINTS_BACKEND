"""PRD-RPT-01 Phase A — compose, resolve, payload, audit."""

from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.architecture.constants import (
    ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
    ARCHITECTURE_ASSESSMENT_KIND,
)
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import AssessmentReport, AuditLog, DataRun
from dataruns.reports.compose import ComposeReportError, compose_assessment_report
from dataruns.reports.payload import scan_payload_for_pii
from dataruns.reports.resolve import RunResolutionError, resolve_dcs_run_for_compose
from dataruns.reports.views import AssessmentReportDetailView, AssessmentReportListCreateView
from tenants.models import Company, Tenant, User


class ReportComposeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Report Co", slug="report-co")
        self.other_tenant = Tenant.objects.create(name="Other Co", slug="other-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Report Co",
            domain="report.example.com",
        )
        self.other_company = Company.objects.create(
            tenant=self.other_tenant,
            name="Other Co",
            domain="other.example.com",
        )
        self.admin = User.objects.create_user(
            email="admin@report.example.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.other_admin = User.objects.create_user(
            email="admin@other.example.com",
            password="TestPass123!",
            name="Other",
            tenant=self.other_tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()
        self.now = timezone.now()

    def _create_dcs_run(
        self,
        *,
        company: Company | None = None,
        tenant=None,
        checks: list[dict],
        score: float = 72.5,
        finished_at=None,
        status=DataRun.Status.SUCCEEDED,
    ) -> DataRun:
        company = company or self.company
        tenant = tenant or company.tenant
        return DataRun.objects.create(
            tenant=tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=status,
            finished_at=finished_at or self.now,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(company.id),
                "headline_score": score,
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": score,
                    "check_results": checks,
                },
                "check_results": checks,
                "business_impact": {
                    "currency": "EUR",
                    "estimate": 12000.0,
                    "confidence": "MEDIUM",
                },
            },
        )

    def test_resolve_latest_scored_run_in_period(self):
        older = self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}],
            score=60.0,
            finished_at=self.now - timedelta(days=10),
        )
        newer = self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "critical",
                    "message": "Missing purchases",
                    "provenance": {
                        "revenue_impact": 5000.0,
                        "revenue_currency": "EUR",
                    },
                }
            ],
            score=70.0,
            finished_at=self.now - timedelta(days=2),
        )
        since = (self.now - timedelta(days=14)).isoformat()
        until = self.now.isoformat()
        resolved = resolve_dcs_run_for_compose(
            company=self.company,
            since_raw=since,
            until_raw=until,
        )
        self.assertEqual(resolved.id, newer.id)
        self.assertNotEqual(resolved.id, older.id)

    def test_resolve_no_run_in_period_raises(self):
        self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}],
            finished_at=self.now - timedelta(days=40),
        )
        with self.assertRaises(RunResolutionError) as ctx:
            resolve_dcs_run_for_compose(
                company=self.company,
                since_raw=(self.now - timedelta(days=7)).isoformat(),
                until_raw=self.now.isoformat(),
            )
        self.assertEqual(ctx.exception.code, "no_run_in_period")

    def test_compose_persists_payload_and_audit(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "critical",
                    "message": "Missing purchases",
                    "provenance": {
                        "revenue_impact": 9000.0,
                        "revenue_currency": "EUR",
                    },
                },
                {"check_id": "LE-04", "status": "PASS", "severity": "low"},
            ]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=14)).isoformat(),
                "until": self.now.isoformat(),
                "include_architecture": False,
                "include_plan": True,
            },
        )
        self.assertEqual(report.status, AssessmentReport.Status.READY)
        self.assertTrue(report.payload_hash)
        self.assertEqual(report.payload["payload_hash"], report.payload_hash)
        self.assertEqual(report.payload["variant"], "PAID_FULL")
        self.assertEqual(report.payload["content"]["locked_sections"], [])
        self.assertEqual(len(report.payload["content"]["top_issues"]), 1)
        self.assertEqual(report.payload["content"]["execution_plan"]["count"], 1)
        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company,
                action="report.composed",
            ).exists()
        )

    def test_payload_has_required_sections_and_no_pii_keys(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "CI-01",
                    "status": "WARN",
                    "severity": "medium",
                    "message": "Soft identity gap",
                    "provenance": {
                        "revenue_impact": 100.0,
                        "revenue_currency": "EUR",
                    },
                }
            ]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=7)).isoformat(),
                "until": self.now.isoformat(),
            },
        )
        content = report.payload["content"]
        self.assertIn("dcs", content)
        self.assertIn("issue_summary", content)
        self.assertIn("architecture", content)
        self.assertIn("business_impact", content)
        self.assertIn("check_register", content)
        self.assertIn("remediation", content)
        self.assertIn("execution_plan", content)
        self.assertEqual(scan_payload_for_pii(report.payload), [])

    def test_plan_matches_composed_run_not_latest_elsewhere(self):
        older = self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "critical",
                    "message": "Older issue",
                    "provenance": {
                        "revenue_impact": 10000.0,
                        "revenue_currency": "EUR",
                    },
                }
            ],
            score=55.0,
            finished_at=self.now - timedelta(days=8),
        )
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "CI-01",
                    "status": "WARN",
                    "severity": "medium",
                    "message": "Latest issue",
                    "provenance": {
                        "revenue_impact": 50.0,
                        "revenue_currency": "EUR",
                    },
                }
            ],
            score=80.0,
            finished_at=self.now - timedelta(days=1),
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "dcs_run_id": older.id,
                "include_plan": True,
            },
        )
        self.assertEqual(report.dcs_data_run_id, older.id)
        tasks = report.payload["content"]["execution_plan"]["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["check_id"], "LE-05")

    def test_compose_links_architecture_for_source_run(self):
        dcs_run = self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}]
        )
        af_run = DataRun.objects.create(
            tenant=self.tenant,
            name=ARCHITECTURE_ASSESSMENT_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": ARCHITECTURE_ASSESSMENT_KIND,
                "company_id": str(self.company.id),
            },
        )
        assessment = ArchitectureAssessment.objects.create(
            company=self.company,
            tenant=self.tenant,
            data_run=af_run,
            source_dcs_data_run=dcs_run,
            status=ArchitectureAssessment.Status.SUCCEEDED,
            mode=ArchitectureAssessment.Mode.AUGMENT,
            weighted_score=81.0,
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": dcs_run.id, "include_architecture": True},
        )
        self.assertEqual(report.architecture_assessment_id, assessment.id)
        self.assertTrue(report.payload["content"]["architecture"]["assessed"])

    def test_api_compose_422_when_no_run(self):
        request = self.factory.post(
            "/api/v1/assessment-reports/",
            {
                "period": {"from": "2026-08-01", "to": "2026-08-11"},
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = AssessmentReportListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["code"], "no_run_in_period")

    def test_api_detail_cross_tenant_404(self):
        dcs_run = self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": dcs_run.id},
        )
        request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/")
        force_authenticate(request, user=self.other_admin)
        response = AssessmentReportDetailView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 404)

    def test_api_list_and_detail_ok(self):
        dcs_run = self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "high",
                    "message": "Issue",
                    "provenance": {
                        "revenue_impact": 500.0,
                        "revenue_currency": "EUR",
                    },
                }
            ]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": dcs_run.id},
        )
        list_request = self.factory.get("/api/v1/assessment-reports/")
        force_authenticate(list_request, user=self.admin)
        list_response = AssessmentReportListCreateView.as_view()(list_request)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)

        detail_request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/")
        force_authenticate(detail_request, user=self.admin)
        detail_response = AssessmentReportDetailView.as_view()(
            detail_request,
            report_id=report.id,
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["report_id"], str(report.id))
        self.assertEqual(
            detail_response.data["payload"]["payload_hash"],
            report.payload_hash,
        )

    def test_recompose_produces_stable_hash_for_same_inputs(self):
        dcs_run = self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}]
        )
        first = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": dcs_run.id, "include_architecture": False},
        )
        second = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": dcs_run.id, "include_architecture": False},
        )
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(
            first.payload["content"]["dcs"]["headline_score"],
            second.payload["content"]["dcs"]["headline_score"],
        )

    def test_since_until_sets_period_labels(self):
        self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}]
        )
        since = self.now - timedelta(days=14)
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": since.isoformat(),
                "until": self.now.isoformat(),
                "include_architecture": False,
            },
        )
        self.assertEqual(
            report.payload["content"]["render_context"]["period_from"],
            since.astimezone(dt_timezone.utc).date().isoformat(),
        )
        self.assertEqual(
            report.payload["content"]["render_context"]["period_to"],
            self.now.astimezone(dt_timezone.utc).date().isoformat(),
        )
        self.assertIsNotNone(report.period_from)
        self.assertIsNotNone(report.window_since)

    def test_dcs_run_id_does_not_invent_period_window(self):
        dcs_run = self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": dcs_run.id, "include_architecture": False},
        )
        self.assertIsNone(report.period_from)
        self.assertIsNone(report.window_since)
        self.assertIsNone(report.payload["content"]["render_context"]["period_from"])

    def test_invalid_period_does_not_fall_back_to_default_window(self):
        self._create_dcs_run(
            checks=[{"check_id": "LE-04", "status": "PASS", "severity": "low"}]
        )
        with self.assertRaises(ComposeReportError) as ctx:
            compose_assessment_report(
                company=self.company,
                user=self.admin,
                body={"period": {"from": "not-a-date", "to": "also-bad"}},
            )
        self.assertEqual(ctx.exception.code, "invalid_period")

    def test_check_register_includes_pass_and_coverage(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "high",
                    "message": "Broken",
                },
                {"check_id": "LE-04", "status": "PASS", "severity": "low"},
                {"check_id": "FD-03", "status": "NOT_CONNECTED", "severity": "medium"},
            ]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=7)).isoformat(),
                "until": self.now.isoformat(),
                "include_architecture": False,
            },
        )
        register = report.payload["content"]["check_register"]
        self.assertEqual(len(register["open_checks"]), 1)
        self.assertEqual(register["open_checks"][0]["check_id"], "LE-05")
        self.assertEqual(register["healthy_checks"][0]["check_id"], "LE-04")
        self.assertEqual(register["coverage_checks"][0]["check_id"], "FD-03")

    def test_include_plan_false_omits_tasks(self):
        self._create_dcs_run(
            checks=[
                {
                    "check_id": "LE-05",
                    "status": "FAIL",
                    "severity": "high",
                    "message": "Broken",
                    "provenance": {"revenue_impact": 10.0, "revenue_currency": "EUR"},
                }
            ]
        )
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=7)).isoformat(),
                "until": self.now.isoformat(),
                "include_plan": False,
                "include_architecture": False,
            },
        )
        self.assertEqual(
            report.payload["content"]["execution_plan"]["empty_reason"],
            "excluded",
        )
        self.assertEqual(report.payload["content"]["execution_plan"]["count"], 0)

    def test_api_viewer_cannot_compose(self):
        viewer = User.objects.create_user(
            email="viewer@report.example.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        request = self.factory.post(
            "/api/v1/assessment-reports/",
            {"period": {"from": "2026-08-01", "to": "2026-08-11"}},
            format="json",
        )
        force_authenticate(request, user=viewer)
        response = AssessmentReportListCreateView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    def test_api_unauthenticated(self):
        request = self.factory.post("/api/v1/assessment-reports/", {}, format="json")
        response = AssessmentReportListCreateView.as_view()(request)
        self.assertIn(response.status_code, (401, 403))
