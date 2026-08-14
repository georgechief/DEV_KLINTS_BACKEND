"""Writeback preview API tests (PRD-WB-01 §5)."""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import AuditLog, DataRun, Run, RunIssue, WritebackJob
from dataruns.writebacks.views import (
    WritebackKindsView,
    WritebackMappingsView,
    WritebackPreviewView,
)
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["CI-01"],
    WRITEBACK_SANDBOX_COMPANY_IDS=[],
)
class WritebackPreviewApiTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="WB", slug="wb-api")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="WB Co",
            domain="wb-api.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb-api.test",
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

    def test_mappings_list(self):
        request = self.factory.get("/api/v1/writebacks/mappings/")
        force_authenticate(request, user=self.admin)
        response = WritebackMappingsView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["count"], 3)
        enabled = [row for row in response.data["mappings"] if row["check_id"] == "CI-01"]
        self.assertTrue(enabled)
        self.assertTrue(enabled[0]["enabled"])

    def test_kinds_list(self):
        request = self.factory.get("/api/v1/writebacks/kinds/")
        force_authenticate(request, user=self.admin)
        response = WritebackKindsView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        kinds = {row["op_kind"] for row in response.data["kinds"]}
        self.assertIn("contact_upsert", kinds)

    def test_preview_ci01_returns_diff_hash_and_job(self):
        request = self.factory.post(
            "/api/v1/writebacks/preview/",
            {"check_id": "CI-01", "max_rows": 5},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackPreviewView.as_view()(request)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["check_id"], "CI-01")
        self.assertEqual(len(response.data["diff_hash"]), 64)
        self.assertEqual(response.data["summary"]["ready"], 1)
        self.assertIsNotNone(response.data["job_id"])
        self.assertTrue(WritebackJob.objects.filter(pk=response.data["job_id"]).exists())
        self.assertTrue(
            AuditLog.objects.filter(company=self.company, action="writeback.previewed").exists()
        )
        intent = response.data["intents"][0]
        self.assertEqual(intent["op_kind"], "contact_upsert")
        self.assertEqual(intent["entity_key"], "b***@example.com")

    def test_preview_unknown_check_404(self):
        request = self.factory.post(
            "/api/v1/writebacks/preview/",
            {"check_id": "ZZ-99"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackPreviewView.as_view()(request)
        self.assertEqual(response.status_code, 404)
