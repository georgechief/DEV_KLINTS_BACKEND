"""Execute denied when writebacks are globally disabled (PRD-WB-01 §11)."""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import DataRun, Run, RunIssue
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.views import WritebackExecuteView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["CI-01"],
    WRITEBACK_SANDBOX_COMPANY_IDS=[],
)
class WritebackExecuteDisabledTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WBD", slug="wbd")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Prod Co",
            domain="wbd.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wbd.test",
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

    def test_service_execute_blocked_without_sandbox(self):
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

    def test_execute_api_returns_403_with_disabled_message(self):
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
        self.assertEqual(response.data["detail"], "Writebacks are disabled.")
        self.assertEqual(response.data["reason"], "writebacks_disabled")
