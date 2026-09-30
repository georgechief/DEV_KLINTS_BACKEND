"""Optional live writeback sandbox suite (PRD-WB-21 Phase D).

Skipped unless env company is set. Uses the same Allow writebacks → preview →
approve → execute → rollback contract as the mocked Phase A harness.

Env (either works):
  WRITEBACK_EXECUTE_COMPANY_ID=<uuid>   preferred (WB-03 naming)
  WRITEBACK_SANDBOX_COMPANY_ID=<uuid>   legacy alias
"""

from __future__ import annotations

import os
import unittest
import uuid

from django.test import TestCase, override_settings

from dataruns.tests.writeback_helpers import (
    PHASE_A_SANDBOX_CHECK_IDS,
    issue_approved_writeback_token,
    run_sandbox_execute,
    run_sandbox_preview,
    run_sandbox_rollback,
    seed_writeback_allowlist,
    writeback_execute_company,
)
from tenants.models import Company, User


def _live_company_id() -> str:
    return (
        os.environ.get("WRITEBACK_EXECUTE_COMPANY_ID", "").strip()
        or os.environ.get("WRITEBACK_SANDBOX_COMPANY_ID", "").strip()
    )


def _live_configured() -> bool:
    return bool(_live_company_id())


@unittest.skipUnless(_live_configured(), "WRITEBACK_EXECUTE_COMPANY_ID / WRITEBACK_SANDBOX_COMPANY_ID not set")
@override_settings(WRITEBACKS_ENABLED=False)
class WritebackSandboxLivePhaseATests(TestCase):
    """PRD-WB-21 Phase D — live dual-connector Phase A (CI-01, CC-03, WB-SHOP-01)."""

    def setUp(self):
        company_id = _live_company_id()
        self.company = Company.objects.get(pk=uuid.UUID(company_id))
        seed_writeback_allowlist(*PHASE_A_SANDBOX_CHECK_IDS)
        self.admin = User.objects.filter(
            tenant_id=self.company.tenant_id,
            role=User.Role.ADMIN,
            is_active=True,
        ).first()
        if self.admin is None:
            self.skipTest("No admin user for live execute company")
        # Restore prior Settings flag in tearDown (do not leave company execute ON).
        self._execute_cm = writeback_execute_company(self.company)
        self._execute_cm.__enter__()

    def tearDown(self):
        cm = getattr(self, "_execute_cm", None)
        if cm is not None:
            cm.__exit__(None, None, None)

    def _live_tier_a(self, check_id: str, *, expect_rollback: bool = True) -> None:
        preview = run_sandbox_preview(
            company=self.company,
            check_id=check_id,
            actor=self.admin,
            max_rows=1,
        )
        if preview.summary.ready < 1:
            self.skipTest(f"No ready intents for live {check_id} (need evidence / contacts)")
        self.assertIsNone(preview.blocked_reason)
        self.assertTrue(
            preview.execute_eligible.sandbox
            or getattr(preview.execute_eligible, "company", False),
            f"{check_id}: execute_eligible.company/sandbox must be True when Allow writebacks ON",
        )

        token = issue_approved_writeback_token(
            company=self.company,
            job_id=preview.job_id,
            requester=self.admin,
            approver=self.admin,
        )
        executed = run_sandbox_execute(
            company=self.company,
            check_id=check_id,
            actor=self.admin,
            diff_hash=preview.diff_hash,
            approval_id=str(token.id),
            max_rows=1,
        )
        self.assertIsNone(executed.blocked_reason, executed.blocked_reason)
        self.assertGreaterEqual(executed.summary.executed, 1)
        self.assertTrue(executed.job_id)

        if expect_rollback:
            rollback = run_sandbox_rollback(
                company=self.company,
                job_id=executed.job_id,
                actor=self.admin,
            )
            self.assertIn(rollback.get("status"), {"rolled_back", "rollback_partial"})
            self.assertGreaterEqual(int(rollback.get("rolled_back") or 0), 1)

    def test_live_cc03_sandbox_pass(self):
        self._live_tier_a("CC-03")

    def test_live_ci01_sandbox_pass(self):
        self._live_tier_a("CI-01")

    def test_live_wb_shop_01_sandbox_pass(self):
        self._live_tier_a("WB-SHOP-01")
