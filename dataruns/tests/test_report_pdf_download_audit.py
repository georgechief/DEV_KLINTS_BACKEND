"""PRD-RPT-01 Phase B — PDF stream + download audit."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.audit import audit_meta_short_string
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import AssessmentReport, AuditLog, DataRun
from dataruns.reports.compose import compose_assessment_report
from dataruns.reports.ip import extract_client_ip
from dataruns.reports.render_pdf import render_assessment_pdf
from dataruns.reports.views import AssessmentReportPdfView
from tenants.models import Company, Tenant, User


class _FakeRequest:
    def __init__(self, meta: dict):
        self.META = meta


class ReportPdfDownloadAuditTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Pdf Co", slug="pdf-co")
        self.other_tenant = Tenant.objects.create(name="Other Pdf", slug="other-pdf")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Pdf Co",
            domain="pdf.example.com",
        )
        Company.objects.create(
            tenant=self.other_tenant,
            name="Other Pdf",
            domain="other-pdf.example.com",
        )
        self.admin = User.objects.create_user(
            email="admin@pdf.example.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer@pdf.example.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        self.other_admin = User.objects.create_user(
            email="admin@other-pdf.example.com",
            password="TestPass123!",
            name="Other",
            tenant=self.other_tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()
        self.now = timezone.now()

    def _create_dcs_run(self) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=self.now,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 71.0,
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 71.0,
                    "check_results": [
                        {
                            "check_id": "LE-05",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "Missing purchases",
                        },
                        {
                            "check_id": "LE-04",
                            "status": "PASS",
                            "severity": "low",
                        },
                    ],
                },
                "check_results": [
                    {
                        "check_id": "LE-05",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Missing purchases",
                    },
                    {
                        "check_id": "LE-04",
                        "status": "PASS",
                        "severity": "low",
                    },
                ],
                "business_impact": {
                    "currency": "EUR",
                    "estimate": 4200.0,
                },
            },
        )

    def _compose(self):
        self._create_dcs_run()
        return compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={
                "since": (self.now - timedelta(days=14)).isoformat(),
                "until": self.now.isoformat(),
                "include_architecture": False,
            },
        )

    def test_extract_prefers_public_forwarded_ip(self):
        request = _FakeRequest(
            {"HTTP_X_FORWARDED_FOR": "10.0.0.1, 8.8.8.8", "REMOTE_ADDR": "127.0.0.1"}
        )
        ip_address, resolution = extract_client_ip(request)
        self.assertEqual(ip_address, "8.8.8.8")
        self.assertEqual(resolution, "x_forwarded_for")

    def test_extract_falls_back_to_remote_addr(self):
        request = _FakeRequest({"REMOTE_ADDR": "127.0.0.1"})
        ip_address, resolution = extract_client_ip(request)
        self.assertEqual(ip_address, "127.0.0.1")
        self.assertEqual(resolution, "remote_addr")

    def test_extract_private_xff_falls_back_to_remote_addr(self):
        request = _FakeRequest(
            {
                "HTTP_X_FORWARDED_FOR": "10.0.0.1, 192.168.1.20",
                "REMOTE_ADDR": "203.0.113.50",
            }
        )
        ip_address, resolution = extract_client_ip(request)
        self.assertEqual(ip_address, "203.0.113.50")
        self.assertEqual(resolution, "remote_addr")

    def test_extract_private_xff_without_remote_keeps_first_hop(self):
        request = _FakeRequest({"HTTP_X_FORWARDED_FOR": "10.0.0.1"})
        ip_address, resolution = extract_client_ip(request)
        self.assertEqual(ip_address, "10.0.0.1")
        self.assertEqual(resolution, "x_forwarded_for")

    def test_extract_unknown_when_missing(self):
        ip_address, resolution = extract_client_ip(_FakeRequest({}))
        self.assertIsNone(ip_address)
        self.assertEqual(resolution, "unknown")

    def test_pdf_streams_and_audits_download(self):
        report = self._compose()
        request = self.factory.get(
            f"/api/v1/assessment-reports/{report.id}/pdf/",
            HTTP_X_FORWARDED_FOR="8.8.8.8",
            HTTP_USER_AGENT="KlintsTest/1.0",
        )
        force_authenticate(request, user=self.admin)
        response = AssessmentReportPdfView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("klints-assessment-pdf-co-", response["Content-Disposition"])
        body = b"".join(response.streaming_content) if hasattr(response, "streaming_content") else response.content
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertGreater(len(body), 500)

        event = AuditLog.objects.get(company=self.company, action="report.downloaded")
        self.assertEqual(event.performed_by, self.admin.email)
        self.assertEqual(event.metadata["email"], self.admin.email)
        self.assertEqual(event.metadata["report_id"], str(report.id))
        self.assertEqual(event.metadata["payload_hash"], report.payload_hash)
        self.assertEqual(event.metadata["ip_address"], "8.8.8.8")
        self.assertEqual(event.metadata["ip_resolution"], "x_forwarded_for")
        self.assertTrue(event.metadata["downloaded_at"])
        self.assertTrue(event.metadata["downloaded_at"].endswith("Z"))
        self.assertTrue(event.created_at)
        self.assertEqual(event.actor_user_id, self.admin.id)
        meta = audit_meta_short_string(event.metadata)
        self.assertIn(self.admin.email, meta)
        self.assertIn("8.8.8.8", meta)
        self.assertIn(str(report.id), meta)

    def test_redownload_rerenders_from_stored_payload(self):
        report = self._compose()
        first = render_assessment_pdf(report.payload)
        second = render_assessment_pdf(report.payload)
        self.assertTrue(first.startswith(b"%PDF"))
        self.assertEqual(first, second)

        request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/pdf/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        force_authenticate(request, user=self.admin)
        with patch(
            "dataruns.reports.views.render_assessment_pdf",
            wraps=render_assessment_pdf,
        ) as mocked:
            response = AssessmentReportPdfView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once()
        called_payload = mocked.call_args.args[0]
        self.assertEqual(called_payload["payload_hash"], report.payload_hash)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company, action="report.downloaded"
            ).count(),
            1,
        )

    def test_render_failure_audits_and_returns_no_pdf(self):
        report = self._compose()
        request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/pdf/")
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        force_authenticate(request, user=self.admin)
        with patch(
            "dataruns.reports.views.render_assessment_pdf",
            side_effect=RuntimeError("boom"),
        ):
            response = AssessmentReportPdfView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["code"], "render_failed")
        self.assertNotIn("application/pdf", response.get("Content-Type", ""))
        event = AuditLog.objects.get(
            company=self.company, action="report.download_failed"
        )
        self.assertEqual(event.metadata["email"], self.admin.email)
        self.assertEqual(event.metadata["error_code"], "render_failed")
        self.assertEqual(event.metadata["ip_address"], "127.0.0.1")
        self.assertTrue(event.metadata["downloaded_at"])
        self.assertFalse(
            AuditLog.objects.filter(
                company=self.company, action="report.downloaded"
            ).exists()
        )

    def test_cross_tenant_pdf_404(self):
        report = self._compose()
        request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/pdf/")
        force_authenticate(request, user=self.other_admin)
        response = AssessmentReportPdfView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            AuditLog.objects.filter(action="report.downloaded").exists()
        )

    def test_viewer_cannot_download_pdf(self):
        report = self._compose()
        request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/pdf/")
        force_authenticate(request, user=self.viewer)
        response = AssessmentReportPdfView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 403)

    def test_empty_payload_returns_409(self):
        dcs_run = self._create_dcs_run()
        report = AssessmentReport.objects.create(
            company=self.company,
            dcs_data_run=dcs_run,
            payload={"content": {}},
            payload_hash="deadbeef",
            template_version="KLINTS-REPORT-1.0.0",
            created_by=self.admin,
            status=AssessmentReport.Status.READY,
        )
        request = self.factory.get(f"/api/v1/assessment-reports/{report.id}/pdf/")
        force_authenticate(request, user=self.admin)
        response = AssessmentReportPdfView.as_view()(request, report_id=report.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "not_ready")
        self.assertFalse(
            AuditLog.objects.filter(
                company=self.company, action="report.downloaded"
            ).exists()
        )

    def test_long_unbreakable_token_and_unicode_render(self):
        report = self._compose()
        payload = report.payload
        payload["content"]["top_issues"] = [
            {
                "check_id": "LE-05",
                "severity": "high",
                "summary": "x" * 4000 + " — " + "https://example.com/" + ("a" * 200),
            }
        ]
        payload["content"]["render_context"]["aggregate_notice"] = (
            "Aggregate report — no contact-level PII …"
        )
        pdf_bytes = render_assessment_pdf(payload)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_pdf_url_resolves(self):
        from django.urls import reverse

        self.assertTrue(
            reverse("assessment-report-pdf", args=["00000000-0000-0000-0000-000000000001"]).endswith(
                "/pdf/"
            )
        )
