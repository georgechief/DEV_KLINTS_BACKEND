"""fix_owner gate blocks sandbox execute for non-Klints automated checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from dataruns.writebacks.service import writeback_run
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["CI-01"],
    WRITEBACK_SANDBOX_MAX_ROWS=10,
)
class WritebackFixOwnerGateTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="FO", slug="fo")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Sandbox Co",
            domain="fo.test",
        )
        self.admin = User.objects.create_user(
            email="admin@fo.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
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

    @patch("dataruns.writebacks.pipeline.CheckMaster.objects.filter")
    def test_sandbox_execute_blocked_for_data_lead_fix_owner(self, mock_filter):
        master = MagicMock()
        master.fix_owner = "Data lead"
        mock_filter.return_value.first.return_value = master

        with self.settings(WRITEBACK_SANDBOX_COMPANY_IDS=[str(self.company.id)]):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                max_rows=0,
                actor=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                max_rows=0,
                actor=self.admin,
            )

        self.assertEqual(result.blocked_reason, "fix_owner_not_klints_automated")
