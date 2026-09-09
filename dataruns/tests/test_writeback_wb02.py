"""PRD-WB-02 §9 — sandbox approve chain, token consume, LE-04 disabled, analyst 403."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.tests.writeback_helpers import (
    enable_company_sandbox,
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import AuditLog, Contact, DataRun, Run, RunIssue, WritebackApprovalToken, WritebackJob
from dataruns.writebacks.approvals.service import approve_token, request_approval
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.views import WritebackPreviewView, WritebackRunView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_SANDBOX_MAX_ROWS=10,
)
class WritebackWb02SandboxApproveChainTests(TestCase):
    """Preview → request approval → approve → sandbox execute consumes token."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB02", slug="wb02")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumira Sandbox",
            domain="wb02.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb02.test",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.analyst = User.objects.create_user(
            email="analyst@wb02.test",
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
        seed_writeback_allowlist("CI-01", "CC-03")
        self.sandbox_settings = sandbox_company(self.company)

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

    def _seed_cc03_sandbox(self):
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
                    {"check_id": "SP-07", "status": "PASS"},
                    {"check_id": "CC-03", "status": "PASS"},
                ],
            },
        )
        Contact.objects.create(
            company=self.company,
            source=Contact.Source.MANAGO_AI,
            external_id="mc-sandbox-1",
            email="consent@example.com",
        )

    def _run_sandbox_approve_chain(self, *, check_id: str, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}

        with self.sandbox_settings:
            preview = writeback_run(
                company=self.company,
                check_id=check_id,
                mode="dry_run",
                max_rows=1,
                actor=self.analyst,
            )
            self.assertGreaterEqual(preview.summary.ready, 1)
            self.assertTrue(preview.job_id)
            self.assertTrue(preview.diff_hash)

            token = request_approval(
                company=self.company,
                job_id=str(preview.job_id),
                actor=self.analyst,
            )
            self.assertEqual(token.status, WritebackApprovalToken.Status.PENDING)
            approve_token(
                company=self.company,
                approval_id=str(token.id),
                actor=self.admin,
            )

            result = writeback_run(
                company=self.company,
                check_id=check_id,
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                max_rows=1,
                actor=self.admin,
            )

        self.assertEqual(result.mode, "execute")
        self.assertGreaterEqual(result.summary.executed, 1)
        token.refresh_from_db()
        self.assertIsNotNone(token.consumed_at)
        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company,
                action="writeback.approval_requested",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company,
                action="writeback.approval_granted",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company,
                action="writeback.executed",
            ).exists()
        )
        self.assertTrue(
            WritebackJob.objects.filter(
                company=self.company,
                check_id=check_id,
                mode="execute",
                status="executed",
            ).exists()
        )
        return result

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_sandbox_ci01_approve_chain_consumes_token(self, mock_ctx, mock_upsert):
        self._seed_ci01_issue()
        self._run_sandbox_approve_chain(
            check_id="CI-01",
            mock_ctx=mock_ctx,
            mock_upsert=mock_upsert,
        )

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_sandbox_cc03_approve_chain_consumes_token(self, mock_ctx, mock_upsert):
        self._seed_cc03_sandbox()
        self._run_sandbox_approve_chain(
            check_id="CC-03",
            mock_ctx=mock_ctx,
            mock_upsert=mock_upsert,
        )

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_cc03_preview_execute_hash_matches_when_max_rows_omitted(
        self, mock_ctx, mock_upsert
    ):
        """Fix UI omits max_rows. Preview must cap the same way as execute or 409."""
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        self._seed_cc03_sandbox()
        Contact.objects.create(
            company=self.company,
            source=Contact.Source.MANAGO_AI,
            external_id="mc-sandbox-2",
            email="consent2@example.com",
        )
        Contact.objects.create(
            company=self.company,
            source=Contact.Source.MANAGO_AI,
            external_id="mc-sandbox-3",
            email="consent3@example.com",
        )
        with self.sandbox_settings:
            preview = writeback_run(
                company=self.company,
                check_id="CC-03",
                mode="dry_run",
                actor=self.admin,
            )
            self.assertEqual(preview.summary.ready, 1)
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="CC-03",
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )
        self.assertIsNone(result.blocked_reason)
        self.assertEqual(result.summary.executed, 1)

    def test_le04_preview_api_returns_404(self):
        with self.sandbox_settings:
            request = self.factory.post(
                "/api/v1/writebacks/run/",
                {"action": "preview", "check_id": "LE-04", "max_rows": 1},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackRunView.as_view()(request)
            self.assertEqual(response.status_code, 404)
            self.assertIn("mapping", response.data["detail"].lower())

            alias = self.factory.post(
                "/api/v1/writebacks/preview/",
                {"check_id": "LE-04", "max_rows": 1},
                format="json",
            )
            force_authenticate(alias, user=self.admin)
            alias_response = WritebackPreviewView.as_view()(alias)
            self.assertEqual(alias_response.status_code, 404)

    def test_analyst_execute_via_run_returns_403(self):
        self._seed_ci01_issue()
        with self.sandbox_settings:
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.analyst,
            )
            request = self.factory.post(
                "/api/v1/writebacks/run/",
                {
                    "action": "execute",
                    "check_id": "CI-01",
                    "diff_hash": preview.diff_hash,
                },
                format="json",
            )
            force_authenticate(request, user=self.analyst)
            response = WritebackRunView.as_view()(request)
            self.assertEqual(response.status_code, 403)

    def test_execute_diff_hash_mismatch_returns_409(self):
        self._seed_ci01_issue()
        with self.sandbox_settings:
            request = self.factory.post(
                "/api/v1/writebacks/run/",
                {
                    "action": "execute",
                    "check_id": "CI-01",
                    "diff_hash": "f" * 64,
                },
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackRunView.as_view()(request)
            self.assertEqual(response.status_code, 409)
