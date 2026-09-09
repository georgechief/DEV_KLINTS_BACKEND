"""PRD-WB-01B — LE-04 disabled, WB-SHOP-01 Shopify sandbox mapping + rollback."""

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
from dataruns.models import Contact, DataRun, Run, RunIssue, WritebackJob
from dataruns.writebacks.adapters.shopify import ShopifyWriteAdapter
from dataruns.writebacks.capabilities import list_supported_op_kinds
from dataruns.writebacks.registry import MappingDisabled, get_check_mapping, list_mapping_entries
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.transform import collect_evidence_rows
from dataruns.writebacks.types import WriteIntent
from dataruns.writebacks.views import WritebackRollbackView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


class Writeback01BRegistryTests(TestCase):
    def test_le04_disabled_in_registry(self):
        entries = {row["check_id"]: row for row in list_mapping_entries()}
        self.assertFalse(entries["LE-04"].get("enabled"))
        self.assertEqual(entries["LE-04"].get("template_id"), "T6")
        with self.assertRaises(MappingDisabled):
            get_check_mapping("LE-04")

    def test_wb_shop_01_enabled(self):
        mapping = get_check_mapping("WB-SHOP-01")
        self.assertEqual(mapping["check_id"], "WB-SHOP-01")
        self.assertEqual(mapping["operations"][0]["op_kind"], "shopify_customer_update")

    def test_shopify_customer_update_marked_implemented(self):
        kinds = {row["op_kind"]: row["adapter_status"] for row in list_supported_op_kinds()}
        self.assertEqual(kinds["shopify_customer_update"], "implemented")


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_SANDBOX_MAX_ROWS=1,
)
class Writeback01BShopifyPipelineTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("WB-SHOP-01")
        tenant = Tenant.objects.create(name="WB01B", slug="wb01b")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Sandbox Co",
            domain="wb01b.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb01b.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="commerce",
            config=encrypt_config(
                {
                    "shop_domain": "demo.myshopify.com",
                    "access_token": "shpat_test",
                    "api_version": "2024-10",
                }
            ),
            status="connected",
        )
        Contact.objects.create(
            company=self.company,
            source=Contact.Source.SHOPIFY,
            external_id="gid://shopify/Customer/4242",
            email="buyer@example.com",
        )

    def test_collect_evidence_from_shopify_contacts(self):
        rows = collect_evidence_rows(
            company=self.company,
            check_id="WB-SHOP-01",
            max_rows=1,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["shopify_customer_id"], "4242")
        self.assertEqual(rows[0]["side"], "sandbox_customer_note")

    @patch("dataruns.writebacks.adapters.shopify.update_customer")
    @patch("dataruns.writebacks.adapters.shopify.get_customer")
    @patch("dataruns.writebacks.adapters.shopify.resolve_shopify_write_context")
    def test_sandbox_execute_and_rollback(self, mock_ctx, mock_get, mock_update):
        mock_ctx.return_value = object()
        mock_get.return_value = {"id": 4242, "note": "prior note"}
        mock_update.return_value = {"customer": {"id": 4242, "note": "klints_wb_test"}}

        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="WB-SHOP-01",
                mode="dry_run",
                max_rows=1,
                actor=self.admin,
            )
            self.assertGreaterEqual(preview.summary.ready, 1)
            self.assertEqual(preview.intents[0].payload.get("note"), "klints_wb_test")

            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="WB-SHOP-01",
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                max_rows=1,
                actor=self.admin,
            )
            self.assertEqual(result.summary.executed, 1)
            self.assertIsNotNone(result.job_id)
            self.assertEqual(
                result.intents[0].rollback_snapshot.get("note"),
                "prior note",
            )

            factory = APIRequestFactory()
            request = factory.post(
                "/api/v1/writebacks/rollback/",
                {"job_id": result.job_id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackRollbackView.as_view()(request)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mock_update.call_count >= 2)
            # Last call restores prior note
            restore_kwargs = mock_update.call_args.kwargs
            self.assertEqual(restore_kwargs["payload"].get("note"), "prior note")


class ShopifyCustomerRollbackAdapterTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="SH2", slug="sh2")
        self.company = Company.objects.create(tenant=tenant, name="Co", domain="sh2.test")

    @patch("dataruns.writebacks.adapters.shopify.update_customer")
    @patch("dataruns.writebacks.adapters.shopify.get_customer")
    @patch("dataruns.writebacks.adapters.shopify.resolve_shopify_write_context")
    def test_execute_captures_prior_note_and_rollback_restores(self, mock_ctx, mock_get, mock_update):
        mock_ctx.return_value = object()
        mock_get.return_value = {"id": 1, "note": ""}
        mock_update.return_value = {"customer": {"id": 1}}
        adapter = ShopifyWriteAdapter()
        intent = WriteIntent(
            check_id="WB-SHOP-01",
            op_kind="shopify_customer_update",
            operation="shopify.customer_update.note_wb_test",
            target_system="shopify",
            entity_type="customer",
            entity_key="buyer@example.com",
            payload={"id": "1", "note": "klints_wb_test"},
            status="ready",
            capability_id="SHOPIFY.CUSTOMER.UPDATE",
            rollback_strategy="restore_prior_field",
        )
        results = adapter.execute(self.company, [intent], approval_id=None, idempotency_key="k1")
        self.assertEqual(results[0].status, "executed")
        self.assertIsNone(results[0].rollback_snapshot.get("note"))

        outcome = adapter.rollback_intent(self.company, results[0])
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["restored_note"], "")


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_SANDBOX_MAX_ROWS=1,
)
class Writeback01BManagoCc03PipelineTests(TestCase):
    def setUp(self):
        seed_writeback_allowlist("CC-03")
        tenant = Tenant.objects.create(name="WB01B-M", slug="wb01b-m")
        self.company = Company.objects.create(
            tenant=tenant,
            name="Sandbox Co",
            domain="wb01b-m.test",
        )
        self.admin = User.objects.create_user(
            email="admin@wb01b-m.test",
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
        Contact.objects.create(
            company=self.company,
            source=Contact.Source.MANAGO_AI,
            external_id="mc-sandbox-1",
            email="consent@example.com",
        )
        self.domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        self.data_run = DataRun.objects.create(
            tenant=tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "run_id": str(self.domain_run.id),
                "dcs_run": {"run_id": str(self.domain_run.id), "run_state": "SCORED"},
                "check_results": [
                    {"check_id": "SP-07", "status": "PASS"},
                    {"check_id": "CC-03", "status": "PASS"},
                ],
            },
        )

    def test_collect_evidence_falls_back_to_manago_contact_when_cc03_pass(self):
        with sandbox_company(self.company):
            rows = collect_evidence_rows(
                company=self.company,
                check_id="CC-03",
                max_rows=1,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["side"], "shopify_holds_evidence")
        self.assertEqual(rows[0]["person.email"], "consent@example.com")
        self.assertEqual(rows[0]["manago_contact_id"], "mc-sandbox-1")

    def test_non_sandbox_does_not_synthesize_cc03_rows(self):
        rows = collect_evidence_rows(
            company=self.company,
            check_id="CC-03",
            max_rows=1,
        )
        self.assertEqual(rows, [])

    def test_worklist_shopify_holds_evidence_preferred_over_sandbox_fallback(self):
        self.data_run.metadata = {
            "kind": DCS_SCORE_KIND,
            "company_id": str(self.company.id),
            "run_id": str(self.domain_run.id),
            "dcs_run": {"run_id": str(self.domain_run.id), "run_state": "SCORED"},
            "check_results": [
                {"check_id": "SP-07", "status": "PASS"},
                {"check_id": "CC-03", "status": "FAIL"},
            ],
        }
        self.data_run.save(update_fields=["metadata"])
        RunIssue.objects.create(
            run=self.domain_run,
            entity_type="dcs_check",
            entity_id=self.company.id,
            issue_type="CC-03",
            severity="High",
            details={
                "check_id": "CC-03",
                "status": "FAIL",
                "mismatches": [
                    {"side": "weak_provenance", "person.email": "weak@example.com"},
                    {
                        "side": "shopify_holds_evidence",
                        "person.email": "worklist@example.com",
                        "manago_contact_id": "mc-worklist",
                    },
                ],
            },
        )
        with sandbox_company(self.company):
            rows = collect_evidence_rows(
                company=self.company,
                check_id="CC-03",
                max_rows=1,
            )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        email = row.get("person.email")
        if not email and isinstance(row.get("value"), dict):
            email = row["value"].get("person.email")
        self.assertEqual(email, "worklist@example.com")

    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    def test_sandbox_execute_and_rollback(self, mock_ctx, mock_upsert):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}

        with sandbox_company(self.company):
            preview = writeback_run(
                company=self.company,
                check_id="CC-03",
                mode="dry_run",
                max_rows=1,
                actor=self.admin,
            )
            self.assertGreaterEqual(preview.summary.ready, 1)
            self.assertEqual(
                preview.intents[0].after.get("klints_consent_evidence"),
                "shopify_verified",
            )

            token = issue_approved_writeback_token(
                company=self.company,
                job_id=preview.job_id,
                requester=self.admin,
                approver=self.admin,
            )
            result = writeback_run(
                company=self.company,
                check_id="CC-03",
                mode="sandbox_execute",
                expected_diff_hash=preview.diff_hash,
                approval_id=str(token.id),
                max_rows=1,
                actor=self.admin,
            )
            self.assertEqual(result.summary.executed, 1)
            self.assertIsNotNone(result.job_id)
            job = WritebackJob.objects.get(pk=result.job_id)
            self.assertEqual(job.status, "executed")

            factory = APIRequestFactory()
            request = factory.post(
                "/api/v1/writebacks/rollback/",
                {"job_id": result.job_id},
                format="json",
            )
            force_authenticate(request, user=self.admin)
            response = WritebackRollbackView.as_view()(request)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mock_upsert.call_count >= 2)
