"""Connector import pipeline tests (run_import)."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from dataruns.connectors.base import CONNECTOR_BOOTSTRAP_KIND
from dataruns.connectors.import_data import (
    BootstrapSupersededError,
    ImportFailedError,
    run_import,
)
from dataruns.models import Contact, ContactMetric, DataRun, Order, Run, RunConnector
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User
from tenants.tests.bootstrap_test_helpers import shopify_raw_payload

TEST_SHOPIFY_SETTINGS = {
    "SHOPIFY_API_KEY": "test-client-id",
    "SHOPIFY_API_SECRET": "test-client-secret",
    "SHOPIFY_SCOPES": "read_orders,read_products",
    "SHOPIFY_API_VERSION": "2026-01",
    "BOOTSTRAP_DAYS": 30,
}


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyRunImportTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Acme", domain="acme.com"
        )
        self.admin = User.objects.create_user(
            email="admin@acme.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
            }
        )
        self.connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=self.connector,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        self.customers = shopify_raw_payload()["customers"]
        self.orders = shopify_raw_payload()["orders"]

    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_run_import_creates_run_snapshot_contacts_orders_metrics(
        self, mock_fetch
    ):
        mock_fetch.return_value = shopify_raw_payload()

        result = run_import(platform="shopify", user=self.admin, days=10)

        self.assertEqual(result["connector"], "shopify")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["counts"]["contacts"], 1)
        self.assertEqual(result["counts"]["orders"], 1)
        self.assertEqual(result["counts"]["contact_metrics"], 1)

        run = Run.objects.get(pk=result["run_id"])
        self.assertEqual(run.status, Run.Status.COMPLETED)
        self.assertIsNotNone(run.completed_at)

        snapshot = ConnectorSnapshot.objects.get(pk=result["snapshot_id"])
        self.assertEqual(snapshot.version, 2)
        self.assertNotIn("access_token", snapshot.snapshot_data)
        self.assertTrue(
            RunConnector.objects.filter(
                run=run, connector_snapshot=snapshot
            ).exists()
        )

        contact = Contact.objects.get(
            company=self.company, source="shopify", external_id="101"
        )
        self.assertEqual(contact.email, "alice@example.com")
        self.assertEqual(contact.source, "shopify")

        order = Order.objects.get(
            company=self.company, source="shopify", external_id="501"
        )
        self.assertEqual(order.contact_id, contact.id)
        self.assertEqual(order.source, "shopify")
        self.assertEqual(str(order.amount), "25.500000")
        self.assertEqual(order.status, Order.Status.PAID)

        metric = ContactMetric.objects.get(run=run, contact=contact)
        self.assertEqual(metric.total_orders, 1)
        self.assertEqual(str(metric.total_revenue), "25.500000")
        self.assertEqual(metric.lifecycle_stage, "new")

    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_second_import_upserts_same_external_id(self, mock_fetch):
        mock_fetch.return_value = shopify_raw_payload()
        run_import(platform="shopify", user=self.admin)
        run_import(platform="shopify", user=self.admin)

        self.assertEqual(Contact.objects.filter(company=self.company).count(), 1)
        self.assertEqual(Order.objects.filter(company=self.company).count(), 1)

        contact = Contact.objects.get(
            company=self.company, source="shopify", external_id="101"
        )
        contact.email = "updated@example.com"
        contact.save(update_fields=["email"])

        updated_customers = [
            {
                "id": 101,
                "email": "alice@example.com",
                "phone": "+222",
            }
        ]
        mock_fetch.return_value = {
            "customers": updated_customers,
            "orders": self.orders,
            "transactions": [],
        }
        run_import(platform="shopify", user=self.admin)

        contact.refresh_from_db()
        self.assertEqual(contact.email, "alice@example.com")
        self.assertEqual(contact.phone, "+222")

    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_guest_order_contact_uses_email_external_id(self, mock_fetch):
        mock_fetch.return_value = {
            "customers": [],
            "orders": [
                {
                    "id": 900,
                    "email": "Guest@Example.com",
                    "total_price": "10.00",
                    "currency": "EUR",
                    "financial_status": "paid",
                    "created_at": "2026-07-15T10:00:00Z",
                }
            ],
            "transactions": [],
        }

        run_import(platform="shopify", user=self.admin)

        contact = Contact.objects.get(
            company=self.company,
            source="shopify",
            external_id="email:guest@example.com",
        )
        self.assertEqual(contact.email, "Guest@Example.com")
        order = Order.objects.get(
            company=self.company, source="shopify", external_id="900"
        )
        self.assertEqual(order.contact_id, contact.id)

    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_upstream_failure_marks_data_run_failed(self, mock_fetch):
        from dataruns.connectors.shopify.client import ShopifyClientError

        mock_fetch.side_effect = ShopifyClientError("Shopify unavailable")
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": "connector_bootstrap",
                "platform": "shopify",
                "company_id": str(self.company.id),
                "days": 10,
            },
        )

        with self.assertRaises(ImportFailedError):
            run_import(
                platform="shopify",
                company=self.company,
                data_run=data_run,
                days=10,
            )

        data_run.refresh_from_db()
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        self.assertIn("Shopify unavailable", data_run.metadata.get("error", ""))

        run = Run.objects.get(company=self.company)
        self.assertEqual(run.status, Run.Status.COMPLETED)
        self.assertFalse(Contact.objects.filter(company=self.company).exists())

    @patch("dataruns.connectors.import_data.persist_normalized_records")
    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_persist_failure_marks_data_run_failed(
        self, mock_fetch, mock_persist
    ):
        mock_fetch.return_value = shopify_raw_payload()
        mock_persist.side_effect = RuntimeError("persist failed")

        with self.assertRaises(ImportFailedError):
            run_import(platform="shopify", user=self.admin)

        data_run = DataRun.objects.filter(tenant=self.tenant).latest("created_at")
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        self.assertIn("persist failed", data_run.metadata.get("error", ""))
        self.assertFalse(Contact.objects.filter(company=self.company).exists())

    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_default_days_uses_bootstrap_days(self, mock_fetch):
        mock_fetch.return_value = {"customers": [], "orders": [], "transactions": []}

        before = timezone.now()
        result = run_import(platform="shopify", user=self.admin)
        after = timezone.now()

        from datetime import datetime, timedelta

        window_start = datetime.fromisoformat(
            result["window_start"].replace("Z", "+00:00")
        )
        window_end = datetime.fromisoformat(
            result["window_end"].replace("Z", "+00:00")
        )
        delta = window_end - window_start
        self.assertGreaterEqual(delta, timedelta(days=30) - timedelta(seconds=1))
        self.assertLessEqual(window_end, after + timedelta(seconds=1))
        self.assertGreaterEqual(window_end, before - timedelta(seconds=1))

    @patch("dataruns.connectors.shopify.client.ShopifyClient.fetch")
    def test_superseded_bootstrap_aborts_before_terminal_persistence(self, mock_fetch):
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "connector_id": str(self.connector.id),
                "days": 10,
            },
        )

        def fetch_and_supersede(*_args, **_kwargs):
            data_run.status = DataRun.Status.FAILED
            data_run.finished_at = timezone.now()
            data_run.metadata = {
                **(data_run.metadata or {}),
                "superseded": True,
                "superseded_reason": "credentials_changed",
                "error": "Bootstrap superseded by connector credential update.",
            }
            data_run.save(
                update_fields=["status", "finished_at", "metadata", "updated_at"]
            )
            return shopify_raw_payload()

        mock_fetch.side_effect = fetch_and_supersede

        with self.assertRaises(BootstrapSupersededError):
            run_import(
                platform="shopify",
                company=self.company,
                data_run=data_run,
                days=10,
            )

        data_run.refresh_from_db()
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        self.assertTrue(data_run.metadata.get("superseded"))
        self.assertNotIn("counts", data_run.metadata)
        self.assertNotIn("snapshot_id", data_run.metadata)
        self.assertFalse(Contact.objects.filter(company=self.company).exists())
        self.assertFalse(Order.objects.filter(company=self.company).exists())
        self.assertFalse(Run.objects.filter(company=self.company).exists())
        self.assertEqual(
            ConnectorSnapshot.objects.filter(connector=self.connector).count(),
            1,
        )


class PlatformScopedUniquenessTests(TestCase):
    """Shopify and Manago must never overwrite each other on colliding IDs."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="EU Co", slug="eu-co")
        self.company = Company.objects.create(
            tenant=self.tenant, name="EU Co", domain="eu.example"
        )

    def test_same_external_id_different_platforms_are_separate_rows(self):
        from dataruns.connectors.import_data import persist_normalized_records

        shopify_payload = {
            "contacts": [
                {"external_id": "101", "email": "shop@example.com", "phone": "+1"}
            ],
            "orders": [
                {
                    "external_id": "501",
                    "contact_external_id": "101",
                    "amount": "10.00",
                    "currency": "EUR",
                    "status": "paid",
                }
            ],
        }
        manago_payload = {
            "contacts": [
                {"external_id": "101", "email": "manago@example.com", "phone": "+2"}
            ],
            "orders": [
                {
                    "external_id": "501",
                    "contact_external_id": "101",
                    "amount": "20.00",
                    "currency": "EUR",
                    "status": "paid",
                }
            ],
        }

        persist_normalized_records(
            company=self.company, normalized=shopify_payload, platform="shopify"
        )
        persist_normalized_records(
            company=self.company, normalized=manago_payload, platform="manago_ai"
        )

        self.assertEqual(Contact.objects.filter(company=self.company).count(), 2)
        self.assertEqual(Order.objects.filter(company=self.company).count(), 2)

        shop_contact = Contact.objects.get(
            company=self.company, source="shopify", external_id="101"
        )
        manago_contact = Contact.objects.get(
            company=self.company, source="manago_ai", external_id="101"
        )
        self.assertEqual(shop_contact.email, "shop@example.com")
        self.assertEqual(manago_contact.email, "manago@example.com")
        self.assertNotEqual(shop_contact.id, manago_contact.id)

        shop_order = Order.objects.get(
            company=self.company, source="shopify", external_id="501"
        )
        manago_order = Order.objects.get(
            company=self.company, source="manago_ai", external_id="501"
        )
        self.assertEqual(shop_order.contact_id, shop_contact.id)
        self.assertEqual(manago_order.contact_id, manago_contact.id)
        self.assertEqual(str(shop_order.amount), "10.000000")
        self.assertEqual(str(manago_order.amount), "20.000000")

    def test_order_does_not_attach_to_other_platform_contact(self):
        from dataruns.connectors.import_data import persist_normalized_records

        Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="alice@example.com",
            email="alice@example.com",
        )
        counts = persist_normalized_records(
            company=self.company,
            normalized={
                "contacts": [],
                "orders": [
                    {
                        "external_id": "tx-1",
                        "contact_external_id": "alice@example.com",
                        "amount": "5.00",
                        "currency": "EUR",
                        "status": "paid",
                    }
                ],
            },
            platform="manago_ai",
        )
        self.assertEqual(counts["orders"], 0)
        self.assertFalse(
            Order.objects.filter(company=self.company, source="manago_ai").exists()
        )
