"""PRD-WB-07 — atomic once-per-run claim + response hygiene."""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
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
from dataruns.writebacks.exceptions import (
    WritebackAlreadyExecutedForRunError,
    WritebackDcsRunRequiredError,
)
from dataruns.writebacks.pii import (
    mask_entity_key,
    sanitize_rollback_outcome_for_client,
)
from dataruns.writebacks.run_gate import (
    find_blocking_execute_job,
    is_in_flight_execute_job,
    reclaim_stale_executing_jobs,
)
from dataruns.writebacks.serializers import serialize_intent
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.types import WriteIntent
from dataruns.writebacks.views import (
    WritebackExecuteView,
    WritebackPreviewView,
    WritebackRunView,
)
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


def _seed_company(*, slug: str):
    tenant = Tenant.objects.create(name=slug, slug=slug)
    company = Company.objects.create(
        tenant=tenant,
        name=f"{slug} Co",
        domain=f"{slug}.test",
    )
    admin = User.objects.create_user(
        email=f"admin@{slug}.test",
        password="TestPass123!",
        name="Admin",
        tenant=tenant,
        role=User.Role.ADMIN,
        email_verified=True,
        is_active=True,
    )
    Connector.objects.create(
        company=company,
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
    seed_writeback_allowlist("CI-01")
    return tenant, company, admin


def _seed_dcs_and_ci01(*, tenant, company):
    domain_run = Run.objects.create(
        company=company,
        run_type=Run.RunType.FULL,
        status=Run.Status.COMPLETED,
    )
    dcs = DataRun.objects.create(
        tenant=tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        metadata={
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
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
        entity_id=company.id,
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
    return dcs


@override_settings(WRITEBACKS_ENABLED=False, WRITEBACK_SANDBOX_MAX_ROWS=10)
class WritebackWb07HygieneTests(TestCase):
    def setUp(self):
        self.tenant, self.company, self.admin = _seed_company(slug="wb07-hyg")
        self.dcs = _seed_dcs_and_ci01(tenant=self.tenant, company=self.company)
        self.factory = APIRequestFactory()

    def test_serialize_masks_email_entity_key(self):
        intent = WriteIntent(
            check_id="CI-01",
            op_kind="contact_upsert",
            operation="manago.contact_upsert",
            target_system="manago",
            entity_type="contact",
            entity_key="buyer@example.com",
            namespace="",
            template_id=None,
            payload={"email": "buyer@example.com"},
            before={"email": "buyer@example.com"},
            after={"email": "buyer@example.com"},
            rollback_snapshot={},
            source_evidence_ref="",
            status="ready",
        )
        row = serialize_intent(intent)
        self.assertEqual(row["entity_key"], "b***@example.com")
        self.assertEqual(row["before"]["email"], "b***@example.com")
        self.assertEqual(row["after"]["email"], "b***@example.com")
        self.assertEqual(mask_entity_key("ab12cd34"), "ab…34")

    def test_sanitize_rollback_outcome_strips_platform_response(self):
        raw = {
            "ok": True,
            "cleared_backfill_marker": True,
            "response": {
                "success": True,
                "contactId": "mc-secret",
                "email": "buyer@example.com",
            },
            "restored_note": "customer note text",
        }
        cleaned = sanitize_rollback_outcome_for_client(raw)
        self.assertEqual(
            cleaned,
            {"ok": True, "cleared_backfill_marker": True},
        )
        self.assertNotIn("response", cleaned)
        self.assertNotIn("restored_note", cleaned)
        self.assertNotIn("email", cleaned)

    @patch("dataruns.writebacks.adapters.manago.ManagoWriteAdapter.rollback_intent")
    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_rollback_api_strips_platform_response(
        self, mock_ctx, mock_upsert, mock_rollback_intent
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
            executed = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                actor=self.admin,
            )
        mock_rollback_intent.return_value = {
            "ok": True,
            "cleared_backfill_marker": True,
            "response": {
                "success": True,
                "contactId": "mc-1",
                "email": "buyer@example.com",
            },
        }
        request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "rollback", "job_id": executed.job_id},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackRunView.as_view()(request)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertGreaterEqual(response.data.get("rolled_back"), 1)
        row = response.data["results"][0]
        self.assertEqual(row.get("ok"), True)
        self.assertNotIn("response", row)
        self.assertNotIn("email", row)

        job = WritebackJob.objects.get(pk=executed.job_id)
        stored = (job.metadata or {}).get("rollback_results") or []
        self.assertTrue(stored)
        self.assertNotIn("response", stored[0])

    def test_rollback_api_returns_stable_error_codes(self):
        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                actor=self.admin,
            )

        preview_request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "rollback", "job_id": preview.job_id},
            format="json",
        )
        force_authenticate(preview_request, user=self.admin)
        preview_response = WritebackRunView.as_view()(preview_request)
        self.assertEqual(preview_response.status_code, 400, preview_response.data)
        self.assertEqual(
            preview_response.data["code"], "writeback_job_not_rollbackable"
        )
        self.assertNotIn(
            "job status",
            str(preview_response.data.get("detail", "")).lower(),
        )
        self.assertIn("detail", preview_response.data)

        missing_request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "rollback", "job_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        force_authenticate(missing_request, user=self.admin)
        missing_response = WritebackRunView.as_view()(missing_request)
        self.assertEqual(missing_response.status_code, 404, missing_response.data)
        self.assertEqual(
            missing_response.data["code"], "writeback_job_not_found"
        )

    def test_preview_api_returns_masked_entity_key(self):
        with sandbox_company(self.company):
            request = self.factory.post(
                "/api/v1/writebacks/preview/",
                {"check_id": "CI-01", "max_rows": 1},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackPreviewView.as_view()(request)
        self.assertEqual(response.status_code, 200, response.data)
        entity_key = response.data["intents"][0]["entity_key"]
        self.assertEqual(entity_key, "b***@example.com")
        self.assertNotIn("buyer@example.com", entity_key)

    def test_diff_hash_mismatch_omits_hash_fields(self):
        with sandbox_company(self.company):
            request = self.factory.post(
                "/api/v1/writebacks/execute/",
                {"check_id": "CI-01", "diff_hash": "a" * 64},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackExecuteView.as_view()(request)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "diff_hash_mismatch")
        self.assertNotIn("expected", response.data)
        self.assertNotIn("actual", response.data)

    def test_execute_without_dcs_run_denied(self):
        DataRun.objects.filter(pk=self.dcs.id).delete()
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
            with self.assertRaises(WritebackDcsRunRequiredError):
                writeback_run(
                    company=self.company,
                    check_id="CI-01",
                    mode="execute",
                    expected_diff_hash=preview.diff_hash,
                    approval_id=str(token.id),
                    actor=self.admin,
                )
        self.assertFalse(
            WritebackJob.objects.filter(
                company=self.company, mode="execute", status="executed"
            ).exists()
        )

    def test_stale_executing_reclaimed_opens_gate(self):
        job = WritebackJob.objects.create(
            company=self.company,
            check_id="CI-01",
            mode="execute",
            status="executing",
            diff_hash="b" * 64,
            dcs_data_run_id=self.dcs.id,
            summary={"executed": 0},
        )
        WritebackJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        job.refresh_from_db()
        self.assertTrue(is_in_flight_execute_job(job))
        reclaimed = reclaim_stale_executing_jobs(
            company=self.company,
            check_id="CI-01",
            dcs_data_run_id=self.dcs.id,
        )
        self.assertEqual(reclaimed, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIsNone(
            find_blocking_execute_job(
                company=self.company,
                check_id="CI-01",
                dcs_data_run_id=self.dcs.id,
            )
        )


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_SANDBOX_MAX_ROWS=10,
    WRITEBACK_EXECUTING_STALE_MINUTES=15,
)
class WritebackWb07AtomicClaimTests(TransactionTestCase):
    def setUp(self):
        self.tenant, self.company, self.admin = _seed_company(slug="wb07-atom")
        self.dcs = _seed_dcs_and_ci01(tenant=self.tenant, company=self.company)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_claim_then_adapter_raise_leaves_failed_gate_open(
        self, mock_ctx, mock_upsert
    ):
        mock_ctx.return_value = object()
        mock_upsert.side_effect = RuntimeError("boom")

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
            # Adapter catches ManagoClientError; force pipeline path via patch on execute
            with patch(
                "dataruns.writebacks.pipeline._execute_intents",
                side_effect=RuntimeError("adapter_crash"),
            ):
                with self.assertRaises(RuntimeError):
                    writeback_run(
                        company=self.company,
                        check_id="CI-01",
                        mode="execute",
                        expected_diff_hash=preview.diff_hash,
                        approval_id=str(token.id),
                        actor=self.admin,
                    )

        job = WritebackJob.objects.filter(
            company=self.company, check_id="CI-01", mode="execute"
        ).latest("created_at")
        self.assertEqual(job.status, "failed")
        self.assertEqual(int(job.summary.get("executed") or 0), 0)
        self.assertIsNone(
            find_blocking_execute_job(
                company=self.company,
                check_id="CI-01",
                dcs_data_run_id=self.dcs.id,
            )
        )

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_concurrent_double_execute_one_write(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        call_count = {"n": 0}
        lock = threading.Lock()

        def slow_upsert(*args, **kwargs):
            import time

            with lock:
                call_count["n"] += 1
            # Hold the adapter long enough for the sibling request to hit the claim gate.
            time.sleep(0.4)
            return {"success": True, "contactId": "mc-1"}

        mock_upsert.side_effect = slow_upsert

        results: list[object] = []
        errors: list[BaseException] = []

        def worker():
            try:
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
                    results.append(result)
            except BaseException as exc:  # noqa: BLE001 — collect for assert
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        successes = [
            r for r in results if getattr(r, "summary", None) and r.summary.executed > 0
        ]
        already = [
            e for e in errors if isinstance(e, WritebackAlreadyExecutedForRunError)
        ]
        self.assertEqual(len(successes), 1, f"results={results!r} errors={errors!r}")
        self.assertGreaterEqual(len(already), 1, f"errors={errors!r}")
        self.assertLessEqual(call_count["n"], 1)
        executed_jobs = WritebackJob.objects.filter(
            company=self.company,
            check_id="CI-01",
            mode="execute",
            status="executed",
        )
        self.assertEqual(executed_jobs.count(), 1)


@override_settings(
    WRITEBACK_EXECUTING_STALE_MINUTES=15,
    WRITEBACK_PARTIAL_ROLLBACK_MINUTES=15,
)
class WritebackStatusRollbackPolicyTests(TestCase):
    """GAP-01 Slice C / W6-03 — status payload documents manual-only rollback."""

    def setUp(self):
        self.tenant, self.company, self.admin = _seed_company(slug="wb07pol")
        _seed_dcs_and_ci01(tenant=self.tenant, company=self.company)
        self.factory = APIRequestFactory()

    def test_status_includes_manual_rollback_policy(self):
        from dataruns.writebacks.views import WritebackStatusView

        request = self.factory.get(
            "/api/v1/writebacks/status/",
            {"check_id": "CI-01"},
        )
        force_authenticate(request, user=self.admin)
        response = WritebackStatusView.as_view()(request)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["rollback_policy"], "manual_admin_only")
        self.assertFalse(response.data["rollback_auto_on_error"])
        self.assertEqual(response.data["stale_executing_reclaim_minutes"], 15)
        self.assertEqual(response.data["rollback_window_minutes"], 15)
        self.assertEqual(response.data["rollback_window_minutes_purpose"], "metadata_only")

    def test_writeback_status_payload_helper_matches_api(self):
        from dataruns.writebacks.run_gate import writeback_status_payload

        payload = writeback_status_payload(company=self.company, check_id="CI-01")
        self.assertEqual(payload["rollback_policy"], "manual_admin_only")
        self.assertFalse(payload["rollback_auto_on_error"])
        self.assertEqual(payload["stale_executing_reclaim_minutes"], 15)
        self.assertIn("latest_granted_approval", payload)
        self.assertIsNone(payload["latest_granted_approval"])

    def test_status_exposes_granted_unconsumed_approval_for_retry(self):
        """Approve then failed execute leaves APPROVED token — status must surface it."""
        from dataruns.models import WritebackApprovalToken
        from dataruns.writebacks.approvals.service import approve_token, request_approval
        from dataruns.writebacks.run_gate import writeback_status_payload
        from dataruns.writebacks.service import writeback_run
        from dataruns.tests.writeback_helpers import seed_writeback_allowlist

        seed_writeback_allowlist("CI-01")
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.admin,
        )
        approve_token(
            company=self.company,
            approval_id=str(token.id),
            actor=self.admin,
        )
        token.refresh_from_db()
        self.assertEqual(token.status, WritebackApprovalToken.Status.APPROVED)
        self.assertIsNone(token.consumed_at)

        payload = writeback_status_payload(
            company=self.company,
            check_id="CI-01",
            data_run_id=preview.data_run_id,
        )
        self.assertIsNone(payload["latest_pending_approval"])
        granted = payload["latest_granted_approval"]
        self.assertIsNotNone(granted)
        self.assertEqual(granted["status"], WritebackApprovalToken.Status.APPROVED)
        self.assertEqual(granted["approval_id"], str(token.id))
        self.assertEqual(granted["job_id"], str(preview.job_id))
        self.assertEqual(granted["diff_hash"], preview.diff_hash)

    def test_status_omits_granted_when_newer_preview_exists(self):
        """C4 — force new preview must not keep status bound to an older APPROVED grant."""
        from dataruns.models import WritebackApprovalToken
        from dataruns.writebacks.approvals.service import approve_token, request_approval
        from dataruns.writebacks.run_gate import writeback_status_payload
        from dataruns.writebacks.service import writeback_run
        from dataruns.tests.writeback_helpers import seed_writeback_allowlist

        seed_writeback_allowlist("CI-01")
        preview_a = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview_a.job_id),
            actor=self.admin,
        )
        approve_token(
            company=self.company,
            approval_id=str(token.id),
            actor=self.admin,
        )
        preview_b = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        self.assertNotEqual(str(preview_a.job_id), str(preview_b.job_id))

        payload = writeback_status_payload(
            company=self.company,
            check_id="CI-01",
            data_run_id=preview_b.data_run_id,
        )
        self.assertIsNone(payload["latest_pending_approval"])
        self.assertIsNone(payload["latest_granted_approval"])
        self.assertEqual(payload["latest_preview"]["job_id"], str(preview_b.job_id))
        token.refresh_from_db()
        self.assertEqual(token.status, WritebackApprovalToken.Status.REVOKED)
        self.assertEqual(
            (token.metadata or {}).get("revoke_reason"),
            "superseded_by_new_preview",
        )

    def test_status_omits_expired_pending_approval(self):
        """TTL-elapsed PENDING must not hydrate FE (stuck approve/reject/request)."""
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.models import WritebackApprovalToken
        from dataruns.writebacks.approvals.service import request_approval
        from dataruns.writebacks.run_gate import writeback_status_payload
        from dataruns.writebacks.service import writeback_run
        from dataruns.tests.writeback_helpers import seed_writeback_allowlist

        seed_writeback_allowlist("CI-01")
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.admin,
        )
        WritebackApprovalToken.objects.filter(pk=token.id).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        payload = writeback_status_payload(
            company=self.company,
            check_id="CI-01",
            data_run_id=preview.data_run_id,
        )
        self.assertIsNone(payload["latest_pending_approval"])
        self.assertIsNone(payload["latest_granted_approval"])

    def test_status_omits_expired_granted_approval(self):
        """C3 — TTL-elapsed APPROVED must not hydrate FE Approve & write retry."""
        from datetime import timedelta

        from django.utils import timezone

        from dataruns.models import WritebackApprovalToken
        from dataruns.writebacks.approvals.service import approve_token, request_approval
        from dataruns.writebacks.run_gate import writeback_status_payload
        from dataruns.writebacks.service import writeback_run
        from dataruns.tests.writeback_helpers import seed_writeback_allowlist

        seed_writeback_allowlist("CI-01")
        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        token = request_approval(
            company=self.company,
            job_id=str(preview.job_id),
            actor=self.admin,
        )
        approve_token(
            company=self.company,
            approval_id=str(token.id),
            actor=self.admin,
        )
        WritebackApprovalToken.objects.filter(pk=token.id).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        payload = writeback_status_payload(
            company=self.company,
            check_id="CI-01",
            data_run_id=preview.data_run_id,
        )
        self.assertIsNone(payload["latest_pending_approval"])
        self.assertIsNone(payload["latest_granted_approval"])

    @override_settings(WRITEBACK_EXECUTING_STALE_MINUTES=20)
    def test_status_stale_reclaim_minutes_follows_settings(self):
        from dataruns.writebacks.run_gate import writeback_status_payload

        payload = writeback_status_payload(company=self.company, check_id="CI-01")
        self.assertEqual(payload["stale_executing_reclaim_minutes"], 20)
        self.assertFalse(payload["rollback_auto_on_error"])


@override_settings(WRITEBACKS_ENABLED=True)
class WritebackIrreversibleDisclosureTests(TestCase):
    """GAP-01 Slice C / W6-01–02 — preview status carries mapping disclosure metadata."""

    def setUp(self):
        self.tenant, self.company, self.admin = _seed_company(slug="wb07irr")
        _seed_dcs_and_ci01(tenant=self.tenant, company=self.company)
        from dataruns.tests.writeback_helpers import seed_writeback_allowlist

        seed_writeback_allowlist("CI-01")

    def test_preview_job_metadata_and_status_disclosure(self):
        from dataruns.models import WritebackJob
        from dataruns.writebacks.run_gate import writeback_status_payload
        from dataruns.writebacks.service import writeback_run

        preview = writeback_run(
            company=self.company,
            check_id="CI-01",
            mode="dry_run",
            actor=self.admin,
        )
        job = WritebackJob.objects.get(pk=preview.job_id)
        self.assertIn("irreversible", job.metadata)
        self.assertFalse(job.metadata["irreversible"])

        payload = writeback_status_payload(company=self.company, check_id="CI-01")
        latest = payload.get("latest_preview")
        self.assertIsNotNone(latest)
        self.assertFalse(latest["irreversible"])
        self.assertIsNone(latest.get("operator_disclosure"))

    def test_mappings_api_exposes_irreversible_fields(self):
        from dataruns.writebacks.registry import list_mappings
        from dataruns.writebacks.views import WritebackMappingsView
        from rest_framework.test import APIRequestFactory, force_authenticate

        le01 = next((m for m in list_mappings() if m.check_id == "LE-01"), None)
        self.assertIsNotNone(le01)
        self.assertTrue(le01.irreversible)
        self.assertTrue(le01.operator_disclosure)

        wb_shop = next((m for m in list_mappings() if m.check_id == "WB-SHOP-01"), None)
        self.assertIsNotNone(wb_shop)
        self.assertFalse(wb_shop.irreversible)
        self.assertIn("metafield", (wb_shop.operator_disclosure or "").lower())

        factory = APIRequestFactory()
        request = factory.get("/api/v1/writebacks/mappings/")
        force_authenticate(request, user=self.admin)
        response = WritebackMappingsView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data["mappings"] if r["check_id"] == "LE-01")
        self.assertTrue(row["irreversible"])
        self.assertIn("Bulk event backfill", row["operator_disclosure"])

    @override_settings(WRITEBACKS_ENABLED=True)
    def test_wb_shop_preview_stores_operator_disclosure_metadata(self):
        from dataruns.models import WritebackJob
        from dataruns.tests.writeback_helpers import enable_company_sandbox, seed_writeback_allowlist
        from dataruns.writebacks.run_gate import writeback_status_payload
        from dataruns.writebacks.service import writeback_run

        enable_company_sandbox(self.company)
        seed_writeback_allowlist("WB-SHOP-01")
        Connector = __import__("tenants.models", fromlist=["Connector"]).Connector
        from tenants.crypto import encrypt_config

        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=encrypt_config({"shop_domain": "test.myshopify.com", "access_token": "shpat_test"}),
            status="connected",
        )
        preview = writeback_run(
            company=self.company,
            check_id="WB-SHOP-01",
            mode="dry_run",
            actor=self.admin,
        )
        job = WritebackJob.objects.get(pk=preview.job_id)
        self.assertFalse(job.metadata.get("irreversible"))
        self.assertIn("metafield", str(job.metadata.get("operator_disclosure")).lower())

        payload = writeback_status_payload(company=self.company, check_id="WB-SHOP-01")
        latest = payload.get("latest_preview")
        self.assertIsNotNone(latest)
        self.assertIn("metafield", str(latest.get("operator_disclosure")).lower())
