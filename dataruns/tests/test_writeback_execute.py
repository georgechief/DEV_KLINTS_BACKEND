"""Writeback execute + rollback tests with mocked Manago transport."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import AuditLog, DataRun, Run, RunIssue, WritebackJob
from dataruns.writebacks.exceptions import DiffHashMismatchError
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.views import WritebackExecuteView, WritebackRollbackView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["CI-01", "CC-03"],
    WRITEBACK_SANDBOX_MAX_ROWS=10,
)
class WritebackExecuteTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WBX", slug="wbx")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Sandbox Co",
            domain="wbx.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wbx.test",
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

    def _settings_with_sandbox(self):
        return self.settings(WRITEBACK_SANDBOX_COMPANY_IDS=[str(self.company.id)])

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

    def test_execute_denied_without_sandbox(self):
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        with self.assertRaises(DiffHashMismatchError):
            writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="execute",
                expected_diff_hash="0" * 64,
                actor=self.admin,
            )

        result = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="execute",
            expected_diff_hash=preview.diff_hash,
            actor=self.admin,
        )
        self.assertEqual(result.blocked_reason, "writebacks_disabled")

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_sandbox_execute_success(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}

        with self._settings_with_sandbox():
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                actor=self.admin,
            )

        self.assertEqual(result.mode, "sandbox_execute")
        self.assertEqual(result.summary.executed, 1)
        self.assertTrue(mock_upsert.called)
        job = WritebackJob.objects.get(pk=result.job_id)
        self.assertEqual(job.status, "executed")
        self.assertTrue(
            AuditLog.objects.filter(company=self.company, action="writeback.executed").exists()
        )

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_execute_api_diff_hash_mismatch_409(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}

        with self._settings_with_sandbox():
            request = self.factory.post(
                "/api/v1/writebacks/execute/",
                {"check_id": "CI-01", "diff_hash": "f" * 64},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackExecuteView.as_view()(request)
            self.assertEqual(response.status_code, 409)

    @patch("dataruns.writebacks.adapters.manago.remove_contact_tag")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_rollback_detail_set_job(self, mock_ctx, mock_remove):
        mock_ctx.return_value = object()

        with self._settings_with_sandbox():
            job = WritebackJob.objects.create(
                company=self.company,
                check_id="CC-03",
                mode="sandbox_execute",
                status="executed",
                diff_hash="a" * 64,
                intents=[
                    {
                        "check_id": "CC-03",
                        "op_kind": "detail_set",
                        "operation": "manago.detail_set.klints_consent_evidence",
                        "target_system": "manago",
                        "entity_type": "contact",
                        "entity_key": "consent@example.com",
                        "namespace": "klints_",
                        "payload": {
                            "email": "consent@example.com",
                            "contactId": "mc-9",
                            "properties": {"klints_consent_evidence": "shopify_verified"},
                        },
                        "rollback_snapshot": {"klints_consent_evidence": None},
                        "rollback_strategy": "revert_detail",
                        "status": "executed",
                    }
                ],
                summary={"executed": 1},
                sandbox=True,
            )

            with patch("dataruns.writebacks.adapters.manago.upsert_contacts") as mock_upsert:
                mock_upsert.return_value = {"success": True}
                request = self.factory.post(
                    "/api/v1/writebacks/rollback/",
                    {"job_id": str(job.id)},
                    format="json",
                )
                force_authenticate(request, user=self.admin)
                response = WritebackRollbackView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, "rolled_back")
        self.assertTrue(mock_upsert.called)

    @patch("dataruns.writebacks.adapters.manago.remove_contact_tag")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_rollback_tag_add_job(self, mock_ctx, mock_remove):
        mock_ctx.return_value = object()

        with self._settings_with_sandbox():
            job = WritebackJob.objects.create(
                company=self.company,
                check_id="LE-04",
                mode="sandbox_execute",
                status="executed",
                diff_hash="b" * 64,
                intents=[
                    {
                        "check_id": "LE-04",
                        "op_kind": "tag_add",
                        "operation": "manago.tag_add.duplicate_review",
                        "target_system": "manago",
                        "entity_type": "contact",
                        "entity_key": "order-123",
                        "namespace": "klints:",
                        "rollback_strategy": "remove_tag",
                        "payload": {
                            "email": "buyer@example.com",
                            "contactId": "mc-2",
                            "tag": "klints:duplicate_review",
                        },
                        "rollback_snapshot": {"tag": "klints:duplicate_review", "present": False},
                        "status": "executed",
                    }
                ],
                summary={"executed": 1},
                sandbox=True,
            )

            request = self.factory.post(
                "/api/v1/writebacks/rollback/",
                {"job_id": str(job.id)},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackRollbackView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, "rolled_back")
        self.assertTrue(mock_remove.called)
