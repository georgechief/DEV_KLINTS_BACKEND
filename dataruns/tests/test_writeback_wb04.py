"""PRD-WB-04 — once-per-DCS-run writeback gate (+ WB-06 status API)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun, Run, RunIssue, WritebackJob
from dataruns.tests.writeback_helpers import (
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from dataruns.writebacks.exceptions import WritebackAlreadyExecutedForRunError
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.views import WritebackExecuteView, WritebackStatusView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_SANDBOX_MAX_ROWS=10,
)
class WritebackWb04GateTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB04", slug="wb04")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Gate Co",
            domain="wb04.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb04.test",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer@wb04.test",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
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
        self.dcs_run = self._seed_dcs_run()

    def _seed_dcs_run(self) -> DataRun:
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        dcs_run = DataRun.objects.create(
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
        return dcs_run

    def _create_newer_dcs_run(self) -> DataRun:
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
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
                        "email": "buyer2@example.com",
                        "shopify_customer_id": "gid://shopify/Customer/2",
                    }
                ],
            },
        )
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            finished_at=timezone.now(),
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
                        "message": "Still failing",
                    }
                ],
            },
        )

    def _execute_ci01_once(self, mock_ctx, mock_upsert):
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
            result = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )
        return preview, result

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_execute_stores_dcs_data_run_id(self, mock_ctx, mock_upsert):
        _preview, result = self._execute_ci01_once(mock_ctx, mock_upsert)
        self.assertEqual(result.summary.executed, 1)
        self.assertEqual(result.data_run_id, self.dcs_run.id)
        job = WritebackJob.objects.get(pk=result.job_id)
        self.assertEqual(job.dcs_data_run_id, self.dcs_run.id)
        self.assertIsNone(job.rolled_back_at)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_second_execute_same_run_returns_409(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        first_preview, first = self._execute_ci01_once(mock_ctx, mock_upsert)
        self.assertEqual(first.summary.executed, 1)

        with sandbox_company(self.company):
            second_preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=second_preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            with self.assertRaises(WritebackAlreadyExecutedForRunError) as ctx:
                writeback_run(
                    company=self.company,
                    check_id="CI-01",
                    mode="execute",
                    expected_diff_hash=second_preview.diff_hash,
                    approval_id=str(token.id),
                    actor=self.admin,
                )
        self.assertEqual(ctx.exception.code, "writeback_already_executed_for_run")
        self.assertEqual(ctx.exception.data_run_id, self.dcs_run.id)

        request = self.factory.post(
            "/api/v1/writebacks/execute/",
            {
                "check_id": "CI-01",
                "diff_hash": second_preview.diff_hash,
                "approval_id": str(token.id),
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        with sandbox_company(self.company):
            response = WritebackExecuteView.as_view()(request)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "writeback_already_executed_for_run")
        self.assertEqual(response.data["data_run_id"], self.dcs_run.id)
        self.assertEqual(response.data["execute_job_id"], first.job_id)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_new_dcs_run_unlocks_gate(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        self._execute_ci01_once(mock_ctx, mock_upsert)
        newer = self._create_newer_dcs_run()
        self.assertGreater(newer.id, self.dcs_run.id)

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
        self.assertEqual(result.summary.executed, 1)
        self.assertEqual(result.data_run_id, newer.id)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_rollback_unlocks_same_run(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        _preview, first = self._execute_ci01_once(mock_ctx, mock_upsert)

        from dataruns.writebacks.service import writeback_rollback_job

        writeback_rollback_job(
            company=self.company,
            job_id=first.job_id,
            actor=self.admin,
        )
        job = WritebackJob.objects.get(pk=first.job_id)
        self.assertIsNotNone(job.rolled_back_at)

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
        self.assertEqual(result.summary.executed, 1)
        self.assertEqual(result.data_run_id, self.dcs_run.id)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_preview_does_not_lock_execute(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        with sandbox_company(self.company):
            preview_one = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            preview_two = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
            self.assertNotEqual(preview_one.job_id, preview_two.job_id)
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview_two.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="execute",
                expected_diff_hash=preview_two.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )
        self.assertEqual(result.summary.executed, 1)

    def test_company_flag_off_still_blocks_before_gate(self):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
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
    def test_status_locked_after_execute(self, mock_ctx, mock_upsert):
        _preview, result = self._execute_ci01_once(mock_ctx, mock_upsert)
        request = self.factory.get(
            "/api/v1/writebacks/status/",
            {"check_id": "CI-01"},
        )
        force_authenticate(request, user=self.viewer)
        response = WritebackStatusView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["gate"], "locked")
        self.assertEqual(response.data["data_run_id"], self.dcs_run.id)
        self.assertEqual(response.data["rollback_policy"], "manual_admin_only")
        self.assertFalse(response.data["rollback_auto_on_error"])
        self.assertEqual(response.data["latest_execute"]["job_id"], result.job_id)
        intents = response.data["latest_execute"].get("intents") or []
        self.assertGreaterEqual(len(intents), 1)
        self.assertEqual(intents[0].get("status"), "executed")
        self.assertTrue(intents[0].get("entity_key"))

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_status_rolled_back_after_rollback(self, mock_ctx, mock_upsert):
        _preview, result = self._execute_ci01_once(mock_ctx, mock_upsert)
        from dataruns.writebacks.service import writeback_rollback_job

        writeback_rollback_job(
            company=self.company,
            job_id=result.job_id,
            actor=self.admin,
        )
        request = self.factory.get(
            "/api/v1/writebacks/status/",
            {"check_id": "CI-01", "data_run_id": self.dcs_run.id},
        )
        force_authenticate(request, user=self.viewer)
        response = WritebackStatusView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["gate"], "rolled_back")

    @patch("dataruns.writebacks.adapters.manago.ManagoWriteAdapter.rollback_intent")
    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_partial_rollback_retry_unlocks_gate(
        self, mock_ctx, mock_upsert, mock_rollback_intent
    ):
        from dataruns.writebacks.run_gate import find_blocking_execute_job
        from dataruns.writebacks.rollback import WritebackRollbackError
        from dataruns.writebacks.service import writeback_rollback_job

        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}
        _preview, result = self._execute_ci01_once(mock_ctx, mock_upsert)

        mock_rollback_intent.side_effect = RuntimeError("upstream down")
        partial = writeback_rollback_job(
            company=self.company,
            job_id=result.job_id,
            actor=self.admin,
        )
        self.assertEqual(partial["status"], "rollback_partial")
        self.assertEqual(len(partial["errors"]), 1)

        job = WritebackJob.objects.get(pk=result.job_id)
        self.assertIsNone(job.rolled_back_at)
        self.assertEqual(job.status, "rollback_partial")
        self.assertIsNotNone(
            find_blocking_execute_job(
                company=self.company,
                check_id="CI-01",
                dcs_data_run_id=self.dcs_run.id,
            )
        )

        mock_rollback_intent.side_effect = None
        mock_rollback_intent.return_value = {"ok": True}
        completed = writeback_rollback_job(
            company=self.company,
            job_id=result.job_id,
            actor=self.admin,
        )
        self.assertEqual(completed["status"], "rolled_back")

        job.refresh_from_db()
        self.assertIsNotNone(job.rolled_back_at)
        self.assertEqual(job.intents[0]["status"], "rolled_back")
        self.assertIsNone(
            find_blocking_execute_job(
                company=self.company,
                check_id="CI-01",
                dcs_data_run_id=self.dcs_run.id,
            )
        )

        with self.assertRaises(WritebackRollbackError):
            writeback_rollback_job(
                company=self.company,
                job_id=result.job_id,
                actor=self.admin,
            )

    def test_preview_job_stores_dcs_data_run_id(self):
        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )
        job = WritebackJob.objects.get(pk=preview.job_id)
        self.assertEqual(job.dcs_data_run_id, self.dcs_run.id)
        self.assertEqual(preview.data_run_id, self.dcs_run.id)

    def test_status_open_when_no_jobs(self):
        request = self.factory.get(
            "/api/v1/writebacks/status/",
            {"check_id": "CI-01"},
        )
        force_authenticate(request, user=self.viewer)
        response = WritebackStatusView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["gate"], "open")
        self.assertIsNone(response.data["latest_execute"])
        self.assertEqual(response.data["check_id"], "CI-01")
        self.assertEqual(response.data["data_run_id"], self.dcs_run.id)

    def test_status_invalid_check_id_format_404(self):
        request = self.factory.get(
            "/api/v1/writebacks/status/",
            {"check_id": "not a check!!"},
        )
        force_authenticate(request, user=self.viewer)
        response = WritebackStatusView.as_view()(request)
        self.assertEqual(response.status_code, 404)
        self.assertIn("check_id", str(response.data.get("detail", "")).lower())

    def test_zero_executed_job_does_not_lock_gate(self):
        from dataruns.writebacks.run_gate import (
            find_blocking_execute_job,
            resolve_writeback_gate,
        )

        WritebackJob.objects.create(
            company=self.company,
            check_id="CI-01",
            mode="execute",
            status="partial",
            diff_hash="deadbeef",
            summary={"ready": 0, "skipped": 0, "errors": 2, "executed": 0},
            dcs_data_run_id=self.dcs_run.id,
            actor_user=self.admin,
        )
        self.assertIsNone(
            find_blocking_execute_job(
                company=self.company,
                check_id="CI-01",
                dcs_data_run_id=self.dcs_run.id,
            )
        )
        self.assertEqual(
            resolve_writeback_gate(
                company=self.company,
                check_id="CI-01",
                data_run_id=self.dcs_run.id,
            ),
            "open",
        )

    def test_status_no_dcs_run_without_terminal_score(self):
        DataRun.objects.filter(tenant=self.tenant).delete()
        request = self.factory.get(
            "/api/v1/writebacks/status/",
            {"check_id": "CI-01"},
        )
        force_authenticate(request, user=self.viewer)
        response = WritebackStatusView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["gate"], "no_dcs_run")
        self.assertIsNone(response.data["data_run_id"])
        self.assertEqual(response.data["execute_blocked_reason"], "dcs_run_required")
        self.assertIsNone(response.data["latest_execute"])
