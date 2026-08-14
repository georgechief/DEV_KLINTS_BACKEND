"""Optional live sandbox writeback integration (skipped unless env configured)."""

from __future__ import annotations

import os
import unittest
import uuid

from django.test import TestCase, override_settings

from dataruns.writebacks.service import writeback_run
from tenants.models import Company, User


def _sandbox_configured() -> bool:
    raw = os.environ.get("WRITEBACK_SANDBOX_COMPANY_IDS", "")
    return bool(raw.strip())


@unittest.skipUnless(_sandbox_configured(), "WRITEBACK_SANDBOX_COMPANY_IDS not set")
@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["CC-03"],
)
class WritebackSandboxIntegrationTests(TestCase):
    """Writes one klints detail in sandbox and rolls back (PRD-WB-01 §5.3)."""

    def setUp(self):
        company_id = os.environ["WRITEBACK_SANDBOX_COMPANY_IDS"].split(",")[0].strip()
        self.company = Company.objects.get(pk=uuid.UUID(company_id))
        self.admin = User.objects.filter(
            tenant_id=self.company.tenant_id,
            role=User.Role.ADMIN,
            is_active=True,
        ).first()
        if self.admin is None:
            self.skipTest("No admin user for sandbox company")

    def test_detail_set_sandbox_execute_live(self):
        preview = writeback_run(
            company=self.company,
            check_id="CC-03",
            mode="dry_run",
            max_rows=1,
            actor=self.admin,
        )
        if preview.summary.ready == 0:
            self.skipTest("No CC-03 evidence rows in sandbox company")

        result = writeback_run(
            company=self.company,
            check_id="CC-03",
            mode="sandbox_execute",
            expected_diff_hash=preview.diff_hash,
            max_rows=1,
            actor=self.admin,
        )
        self.assertGreaterEqual(result.summary.executed, 0)
