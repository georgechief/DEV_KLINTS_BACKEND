"""fix_owner gate blocks sandbox execute for non-Klints automated checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun, Run
from dataruns.tests.writeback_helpers import (
    enable_company_sandbox,
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)

from dataruns.writebacks.service import writeback_run
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_SANDBOX_MAX_ROWS=10,
)
class WritebackFixOwnerGateTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("CI-01")
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
        # PRD-WB-07 §3.4 — execute requires a terminal DCS run.
        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        DataRun.objects.create(
            tenant=tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(domain_run.id),
                "dcs_run": {"run_id": str(domain_run.id), "run_state": "SCORED"},
            },
        )

    @patch("dataruns.writebacks.pipeline.CheckMaster.objects.filter")
    def test_sandbox_execute_allows_non_klints_fix_owner(self, mock_filter):
        """WB-01B sandbox proof (CC-03) may execute even when pack owner is Data lead."""
        master = MagicMock()
        master.fix_owner = "Data lead"
        mock_filter.return_value.first.return_value = master

        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CI-01",
                mode="dry_run",
                max_rows=0,
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
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                max_rows=0,
                actor=self.admin,
            )

        self.assertIsNone(result.blocked_reason)

    @patch("dataruns.writebacks.pipeline.CheckMaster.objects.filter")
    def test_non_sandbox_execute_blocked_for_data_lead_fix_owner(self, mock_filter):
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        master = MagicMock()
        master.fix_owner = "Data lead"
        mock_filter.return_value.first.return_value = master

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
            mode="execute",
            expected_diff_hash=preview.diff_hash,
            max_rows=0,
            actor=self.admin,
        )

        self.assertEqual(result.blocked_reason, "writebacks_disabled")
