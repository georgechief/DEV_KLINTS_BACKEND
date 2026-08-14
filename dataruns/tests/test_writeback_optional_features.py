"""Optional WB-01 polish: export api shape, individual tier, contact rollback, Shopify."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.connectors.export_data import run_export
from dataruns.models import Contact, Order, Run, WritebackJob
from dataruns.writebacks.approvals.exceptions import ApprovalTokenError
from dataruns.writebacks.approvals.service import request_approval
from dataruns.writebacks.adapters.shopify import ShopifyWriteAdapter
from dataruns.writebacks.service import writeback_run
from dataruns.writebacks.types import WriteIntent
from dataruns.writebacks.views import WritebackRollbackView
from dataruns.writebacks.stub_factory import build_stub_spec
from rest_framework.test import APIRequestFactory, force_authenticate
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User


class ExportApiShapeTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="EXP", slug="exp")
        self.company = Company.objects.create(tenant=tenant, name="Co", domain="exp.test")
        self.user = User.objects.create_user(
            email="u@exp.test",
            password="TestPass123!",
            name="U",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.contact = Contact.objects.create(
            company=self.company,
            external_id="c-1",
            email="buyer@example.com",
            phone="+48123456789",
        )
        self.run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        Order.objects.create(
            company=self.company,
            contact=self.contact,
            external_id="o-1",
            amount=Decimal("10.00"),
            currency="PLN",
            status="paid",
        )

    def test_run_export_api_shape_uses_reverse_map(self):
        payload = run_export("manago_ai", self.user, self.run.id, shape="api")
        self.assertEqual(payload["shape"], "api")
        self.assertEqual(payload["contacts"][0].get("email"), "buyer@example.com")


class StubFactoryTests(TestCase):
    def test_build_stub_spec_defaults(self):
        spec = build_stub_spec(check_id="CI-05", check_name="External ID", template_id="T2")
        self.assertEqual(spec["check_id"], "CI-05")
        self.assertFalse(spec["enabled"])
        self.assertEqual(spec["approval_tier"], "individual")


@override_settings(
    WRITEBACKS_ENABLED=False,
    WRITEBACK_CHECK_ALLOWLIST=["CC-03"],
)
class IndividualApprovalTierTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="IND", slug="ind")
        self.company = Company.objects.create(tenant=tenant, name="Co", domain="ind.test")
        self.admin = User.objects.create_user(
            email="admin@ind.test",
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
            config=encrypt_config({"workspace_id": "x", "api_key": "y", "owner": "o@test.com"}),
            status="connected",
        )

    def test_request_approval_rejects_multi_intent_individual_job(self):
        job = WritebackJob.objects.create(
            company=self.company,
            check_id="CC-03",
            mode="dry_run",
            status="previewed",
            diff_hash="a" * 64,
            approval_tier="individual",
            summary={"ready": 2},
            intents=[],
            sandbox=False,
        )
        with self.assertRaises(ApprovalTokenError) as ctx:
            request_approval(company=self.company, job_id=str(job.id), actor=self.admin)
        self.assertEqual(ctx.exception.code, "individual_tier_single_intent_required")


class ContactUpsertRollbackTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="RB", slug="rb")
        self.company = Company.objects.create(tenant=tenant, name="Co", domain="rb.test")
        self.admin = User.objects.create_user(
            email="admin@rb.test",
            password="TestPass123!",
            name="Admin",
            tenant=tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.factory = APIRequestFactory()

    @patch("dataruns.writebacks.adapters.manago.resolve_manago_write_context")
    @patch("dataruns.writebacks.adapters.manago.upsert_contacts")
    def test_rollback_contact_upsert_clears_backfill_marker(self, mock_upsert, mock_ctx):
        mock_ctx.return_value = object()
        mock_upsert.return_value = {"success": True}
        job = WritebackJob.objects.create(
            company=self.company,
            check_id="CI-01",
            mode="sandbox_execute",
            status="executed",
            diff_hash="c" * 64,
            intents=[
                {
                    "check_id": "CI-01",
                    "op_kind": "contact_upsert",
                    "operation": "manago.contact_upsert",
                    "target_system": "manago",
                    "entity_type": "contact",
                    "entity_key": "buyer@example.com",
                    "namespace": "native",
                    "rollback_strategy": "tagged_backfill_delete",
                    "payload": {"email": "buyer@example.com"},
                    "rollback_snapshot": {"email": "buyer@example.com", "existed": False},
                    "status": "executed",
                }
            ],
            summary={"executed": 1},
            sandbox=True,
        )
        request = self.factory.post(
            "/api/v1/writebacks/rollback/",
            {"job_id": str(job.id)},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = WritebackRollbackView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_upsert.called)


class ShopifyAdapterTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="SH", slug="sh")
        self.company = Company.objects.create(tenant=tenant, name="Co", domain="sh.test")

    @patch("dataruns.writebacks.adapters.shopify.update_customer")
    @patch("dataruns.writebacks.adapters.shopify.resolve_shopify_write_context")
    def test_shopify_customer_update_execute(self, mock_ctx, mock_update):
        mock_ctx.return_value = object()
        mock_update.return_value = {"customer": {"id": 1}}
        adapter = ShopifyWriteAdapter()
        intent = WriteIntent(
            check_id="CI-12",
            op_kind="shopify_customer_update",
            operation="shopify.customer_update",
            target_system="shopify",
            entity_type="customer",
            entity_key="gid://shopify/Customer/1",
            payload={"id": "123", "email": "buyer@example.com"},
            status="ready",
        )
        results = adapter.execute(self.company, [intent], approval_id=None, idempotency_key="k1")
        self.assertEqual(results[0].status, "executed")
        self.assertTrue(mock_update.called)
