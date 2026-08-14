"""BL-017 approval token issue, approve, and prod execute gate tests."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import AuditLog, DataRun, Run, RunIssue, WritebackApprovalToken, WritebackJob
from dataruns.writebacks.approvals.service import approve_token, request_approval
from dataruns.writebacks.approvals.views import (
    WritebackApprovalApproveView,
    WritebackApprovalRequestView,
)
from dataruns.writebacks.gates import execute_allowed
from dataruns.writebacks.service import writeback_run
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=True,
    WRITEBACK_CHECK_ALLOWLIST=["CI-01"],
    WRITEBACK_SANDBOX_COMPANY_IDS=[],
    WRITEBACK_APPROVAL_TTL_MINUTES=60,
)
class WritebackApprovalTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="BL17", slug="bl17")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Prod Co",
            domain="bl17.test",
        )
        self.admin = User.objects.create_user(
            email="admin@bl17.test",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.analyst = User.objects.create_user(
            email="analyst@bl17.test",
            password="TestPass123!",
            name="Analyst",
            tenant=self.tenant,
            role=User.Role.ANALYST,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            config=encrypt_config(
                {
                    "workspace_id": "cid",
                    "api_key": "secret",
                    "owner": "owner@test.com",
                    "endpoint": "https://app2.manago.ai",
                }
            ),
            status="connected",
        )
        self._seed_ci01_issue()

    def _seed_ci01_issue(self):
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain_run.id),
                "dcs_run": {"run_id": str(domain_run.id), "run_state": "SCORED"},
                "check_results": [
                    {
                        "check_id": "CI-01",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Contact count mismatch",
                    }
                ],
            },
        )
        RunIssue.objects.create(
            run=domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="CI-01",
            severity="High",
            details={
                "check_id": "CI-01",
                "status": "FAIL",
                "mismatches": [
                    {
                        "side": "shopify_only",
                        "email": "buyer@example.com",
                        "shopify_customer_id": "gid://shopify/Customer/1",
                    }
                ],
            },
        )

    def test_request_and_approve_token_from_preview_job(self):
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.analyst,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.analyst,
        )
        self.assertEqual(token.status, WritebackApprovalToken.Status.PENDING)
        self.assertEqual(token.diff_hash, preview.diff_hash)
        self.assertEqual(token.object_id, "CI-01")

        approved = approve_token(
            company=self.company,
            approval_id=str(token.id),
            actor=self.admin,
        )
        self.assertEqual(approved.status, WritebackApprovalToken.Status.APPROVED)
        self.assertTrue(
            AuditLog.objects.filter(company=self.company, action="writeback.approval_granted").exists()
        )

    def test_prod_execute_requires_approved_token(self):
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.analyst,
        )
        allowed, reason = execute_allowed(
            company=self.company,
            check_id="CI-01",
            approval_id=None,
            diff_hash=preview.diff_hash,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "approval_id_required")

        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.analyst,
        )
        allowed, reason = execute_allowed(
            company=self.company,
            check_id="CI-01",
            approval_id=str(token.id),
            diff_hash=preview.diff_hash,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "approval_not_approved")

        approve_token(
            company=self.company,
            approval_id=str(token.id),
            actor=self.admin,
        )
        allowed, reason = execute_allowed(
            company=self.company,
            check_id="CI-01",
            approval_id=str(token.id),
            diff_hash=preview.diff_hash,
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_prod_execute_consumes_approval_token(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}

        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.analyst,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.analyst,
        )
        approve_token(
            company=self.company,
            approval_id=str(token.id),
            actor=self.admin,
        )

        result = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="execute",
            expected_diff_hash=preview.diff_hash,
            approval_id=str(token.id),
            actor=self.admin,
        )
        self.assertEqual(result.mode, "execute")
        self.assertEqual(result.summary.executed, 1)

        token.refresh_from_db()
        self.assertIsNotNone(token.consumed_at)
        self.assertTrue(WritebackJob.objects.filter(company=self.company, mode="execute").exists())

    def test_approval_request_api(self):
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.analyst,
        )
        request = self.factory.post(
            "/api/v1/writebacks/approvals/",
            {"job_id": preview.job_id},
            format="json",
        )
        force_authenticate(request, user=self.analyst)
        response = WritebackApprovalRequestView.as_view()(request)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PENDING")
        self.assertEqual(len(response.data["diff_hash"]), 64)

    def test_approval_approve_api(self):
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.analyst,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.analyst,
        )
        request = self.factory.post(
            f"/api/v1/writebacks/approvals/{token.id}/approve/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackApprovalApproveView.as_view()(request, approval_id=str(token.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "APPROVED")
