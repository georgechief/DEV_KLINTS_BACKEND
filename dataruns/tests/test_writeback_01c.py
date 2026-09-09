"""PRD-WB-01C — possible/not sheet + unified POST /writebacks/run/."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.tests.writeback_helpers import (
    enable_company_sandbox,
    issue_approved_writeback_token,
    sandbox_company,
    seed_writeback_allowlist,
)
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.models import DataRun, Run, RunIssue
from dataruns.writebacks.possible_sheet import SHEET_COLUMNS, load_possible_sheet, possible_sheet_payload
from dataruns.writebacks.registry import MappingDisabled, get_check_mapping
from dataruns.writebacks.views import (
    WritebackPossibleView,
    WritebackPreviewView,
    WritebackRunView,
)
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


class WritebackPossibleSheetTests(TestCase):
    def test_csv_columns_match_prd(self):
        _source, rows = load_possible_sheet()
        self.assertGreaterEqual(len(rows), 10)
        self.assertEqual(tuple(rows[0].keys()), SHEET_COLUMNS)

    def test_enabled_mappings_have_field_rows(self):
        _source, rows = load_possible_sheet()
        by_check: dict[str, list[dict]] = {}
        for row in rows:
            by_check.setdefault(row["check_id"], []).append(row)

        cc03 = by_check["CC-03"][0]
        self.assertEqual(cc03["field_or_key"], "klints_consent_evidence")
        self.assertEqual(cc03["write_possible_today"], "yes")
        self.assertEqual(cc03["updates_existing"], "yes")
        self.assertEqual(cc03["rollback_possible_today"], "yes")
        self.assertTrue(cc03["registry_enabled"])

        ci01_fields = {row["field_or_key"] for row in by_check["CI-01"]}
        self.assertIn("email", ci01_fields)
        self.assertIn("klints_backfill", ci01_fields)

        shop = by_check["WB-SHOP-01"][0]
        self.assertEqual(shop["field_or_key"], "note")
        self.assertEqual(shop["write_possible_today"], "yes")
        self.assertEqual(shop["updates_existing"], "yes")

    def test_honest_no_and_disabled_rows(self):
        _source, rows = load_possible_sheet()
        by_check = {row["check_id"]: row for row in rows}

        self.assertEqual(by_check["LE-04"]["write_possible_today"], "disabled")
        self.assertFalse(by_check["LE-04"]["registry_enabled"])
        with self.assertRaises(MappingDisabled):
            get_check_mapping("LE-04")

        for topic in ("SHOPIFY-ORDER", "SHOPIFY-TRANSACTION", "MANAGO-ORDER"):
            self.assertEqual(by_check[topic]["write_possible_today"], "no")

        payload = possible_sheet_payload()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["count"], len(rows))
        self.assertTrue(payload["source"].endswith("WRITEBACK_POSSIBLE_NOT_SHEET.csv"))


@override_settings(WRITEBACKS_ENABLED=False)
class WritebackPossibleApiTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="WB01C", slug="wb01c-possible")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Possible Co",
            domain="wb01c-possible.test",
        )
        self.viewer = User.objects.create_user(
            email="viewer@wb01c.test",
            password="TestPass123!",
            name="Viewer",
            tenant=tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()

    def test_get_possible_returns_csv_rows(self):
        request = self.factory.get("/api/v1/writebacks/possible/")
        force_authenticate(request, user=self.viewer)
        response = WritebackPossibleView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["schema_version"], 1)
        self.assertGreaterEqual(response.data["count"], 10)
        check_ids = {row["check_id"] for row in response.data["rows"]}
        self.assertIn("CC-03", check_ids)
        self.assertIn("LE-04", check_ids)
        self.assertIn("SHOPIFY-ORDER", check_ids)


@override_settings(
    WRITEBACKS_ENABLED=False,
)
class WritebackRunApiTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("CI-01")
        tenant = Tenant.objects.create(name="WB01C-RUN", slug="wb01c-run")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Run Co",
            domain="wb01c-run.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb01c-run.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.analyst = User.objects.create_user(
            email="analyst@wb01c-run.test",
            password="TestPass123!",
            name="Analyst",
            tenant=tenant,
            role=User.Role.ANALYST,
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

    def test_run_rejects_unknown_action(self):
        request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "approve", "check_id": "CI-01"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackRunView.as_view()(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["required_keys"], ["action"])

    def test_run_execute_requires_diff_hash(self):
        request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "execute", "check_id": "CI-01"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackRunView.as_view()(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["action"], "execute")
        self.assertEqual(response.data["required_keys"], ["diff_hash"])

    def test_run_rollback_requires_job_id(self):
        request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "rollback"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackRunView.as_view()(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["required_keys"], ["job_id"])

    def test_run_preview_matches_preview_alias(self):
        run_request = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "preview", "check_id": "CI-01", "max_rows": 5},
            format="json",
        )
        force_authenticate(run_request, user=self.admin)
        run_response = WritebackRunView.as_view()(run_request)
        self.assertEqual(run_response.status_code, 200, run_response.data)
        self.assertEqual(run_response.data["action"], "preview")
        self.assertEqual(run_response.data["check_id"], "CI-01")
        self.assertEqual(run_response.data["mode"], "dry_run")
        self.assertEqual(len(run_response.data["diff_hash"]), 64)
        self.assertEqual(run_response.data["summary"]["ready"], 1)

        alias_request = self.factory.post(
            "/api/v1/writebacks/preview/",
            {"check_id": "CI-01", "max_rows": 5},
            format="json",
        )
        force_authenticate(alias_request, user=self.admin)
        alias_response = WritebackPreviewView.as_view()(alias_request)
        self.assertEqual(alias_response.status_code, 200)
        self.assertEqual(alias_response.data["action"], "preview")
        self.assertEqual(alias_response.data["summary"]["ready"], 1)

    def test_analyst_can_preview_but_not_execute_via_run(self):
        preview = self.factory.post(
            "/api/v1/writebacks/run/",
            {"action": "preview", "check_id": "CI-01"},
            format="json",
        )
        force_authenticate(preview, user=self.analyst)
        preview_response = WritebackRunView.as_view()(preview)
        self.assertEqual(preview_response.status_code, 200, preview_response.data)

        execute = self.factory.post(
            "/api/v1/writebacks/run/",
            {
                "action": "execute",
                "check_id": "CI-01",
                "diff_hash": preview_response.data["diff_hash"],
            },
            format="json",
        )
        force_authenticate(execute, user=self.analyst)
        execute_response = WritebackRunView.as_view()(execute)
        self.assertEqual(execute_response.status_code, 403)

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_run_execute_sandbox_and_rollback(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True, "contactId": "mc-1"}

        with sandbox_company(self.company):
            preview = self.factory.post(
                "/api/v1/writebacks/run/",
                {"action": "preview", "check_id": "CI-01", "max_rows": 1},
                format="json",
            )
            force_authenticate(preview, user=self.admin)
            preview_response = WritebackRunView.as_view()(preview)
            self.assertEqual(preview_response.status_code, 200, preview_response.data)

            # WB-04: company Allow writebacks requires an approved token before execute.
            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview_response.data["job_id"],
                requester=self.admin,
                approver=self.admin,
            )
            execute = self.factory.post(
                "/api/v1/writebacks/run/",
                {
                    "action": "execute",
                    "check_id": "CI-01",
                    "diff_hash": preview_response.data["diff_hash"],
                    "approval_id": str(token.id),
                    "max_rows": 1,
                },
                format="json",
            )
            force_authenticate(execute, user=self.admin)
            execute_response = WritebackRunView.as_view()(execute)

        self.assertEqual(execute_response.status_code, 200, execute_response.data)
        self.assertEqual(execute_response.data["action"], "execute")
        self.assertEqual(execute_response.data["mode"], "execute")
        self.assertEqual(execute_response.data["summary"]["executed"], 1)
        self.assertTrue(execute_response.data["rollback"]["supported"])
        self.assertFalse(execute_response.data["execute_eligible"]["production"])
        job_id = execute_response.data["job_id"]

        with sandbox_company(self.company):
            rollback = self.factory.post(
                "/api/v1/writebacks/run/",
                {"action": "rollback", "job_id": job_id},
                format="json",
            )
            force_authenticate(rollback, user=self.admin)
            rollback_response = WritebackRunView.as_view()(rollback)

        self.assertEqual(rollback_response.status_code, 200, rollback_response.data)
        self.assertEqual(rollback_response.data["action"], "rollback")
        self.assertEqual(rollback_response.data["check_id"], "CI-01")
        self.assertEqual(rollback_response.data["status"], "rolled_back")
        self.assertEqual(rollback_response.data["rolled_back"], 1)
