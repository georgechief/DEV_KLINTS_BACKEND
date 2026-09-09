"""PRD-POLISH-01 Phase 2 — writeback execute audit + denial messages."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.models import AuditLog, WritebackJob
from dataruns.tests.writeback_helpers import (
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from dataruns.writebacks.messages import writeback_execute_denial_detail
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.types import WriteIntent
from dataruns.writebacks.views import WritebackExecuteView
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import DataRun, Run, RunIssue
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(WRITEBACKS_ENABLED=False)
class WritebackPolish01Phase2Tests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("CI-01", "CC-03")
        self.tenant = Tenant.objects.create(name="Polish", slug="polish")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Polish Co",
            domain="polish.test",
        )
        self.admin = User.objects.create_user(
            email="admin@polish.test",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
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

    def test_denial_detail_maps_writebacks_disabled(self):
        detail = writeback_execute_denial_detail("writebacks_disabled")
        self.assertIn("Settings", detail)
        self.assertIn("Workspace", detail)

    def test_denial_detail_maps_consent_namespace(self):
        detail = writeback_execute_denial_detail("consent_namespace_not_clean")
        self.assertIn("SP-07", detail)

    def test_denial_detail_maps_connector(self):
        detail = writeback_execute_denial_detail("connector_not_connected:manago_ai")
        self.assertIn("Manago", detail)
        self.assertIn("connected", detail.lower())

    def test_execute_api_returns_accurate_disabled_detail(self):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        request = self.factory.post(
            "/api/v1/writebacks/execute/",
            {"check_id": "CI-01", "diff_hash": preview.diff_hash},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackExecuteView.as_view()(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "writebacks_disabled")
        self.assertIn("Settings", response.data["detail"])
        self.assertNotEqual(response.data["detail"], "Writebacks are disabled.")

    def test_execute_api_maps_approval_required(self):
        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            request = self.factory.post(
                "/api/v1/writebacks/execute/",
                {"check_id": "CI-01", "diff_hash": preview.diff_hash},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackExecuteView.as_view()(request)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data["reason"], "approval_id_required")
            self.assertIn("Approval", response.data["detail"])

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_successful_execute_emits_executed_audit_only(
        self, mock_ctx, mock_upsert
    ):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )
        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company, action="writeback.executed"
            ).exists()
        )
        self.assertFalse(
            AuditLog.objects.filter(
                company=self.company, action="writeback.execute_failed"
            ).exists()
        )

    @patch("dataruns.writebacks.pipeline._execute_intents")
    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_zero_executed_emits_execute_failed_not_executed(
        self, mock_ctx, mock_upsert, mock_execute_intents
    ):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        failed_intent = WriteIntent(
            check_id="CI-01",
            op_kind="contact_upsert",
            operation="manago.contact_upsert.shopify_only",
            target_system="manago",
            entity_type="contact",
            entity_key="buyer@example.com",
            namespace="native",
            payload={"email": "buyer@example.com"},
            status="error",
            error_reason="adapter_error",
        )
        mock_execute_intents.return_value = ([failed_intent], "failed")

        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )

        self.assertEqual(result.summary.executed, 0)
        self.assertTrue(result.job_id)
        job = WritebackJob.objects.get(pk=result.job_id)
        self.assertEqual(job.status, "failed")
        self.assertFalse(
            AuditLog.objects.filter(
                company=self.company, action="writeback.executed"
            ).exists()
        )
        failed = AuditLog.objects.filter(
            company=self.company, action="writeback.execute_failed"
        ).first()
        self.assertIsNotNone(failed)
        self.assertEqual(failed.tone, AuditLog.Tone.RISK)
