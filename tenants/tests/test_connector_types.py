"""Tests for canonical connector type resolution."""

from django.test import SimpleTestCase, TestCase

from tenants.connector_types import (
    CONNECTOR_TYPE_CDP,
    CONNECTOR_TYPE_ECOMMERCE,
    resolve_connector_type,
)
from tenants.models import Company, Connector, Tenant


class ResolveConnectorTypeTests(SimpleTestCase):
    def test_manago_ai_is_cdp(self):
        self.assertEqual(resolve_connector_type("manago_ai"), CONNECTOR_TYPE_CDP)

    def test_shopify_is_ecommerce(self):
        self.assertEqual(resolve_connector_type("shopify"), CONNECTOR_TYPE_ECOMMERCE)


class ConnectorModelTypeNormalizationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )

    def test_save_normalizes_manago_type(self):
        connector = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            config={},
            status="connected",
        )
        connector.refresh_from_db()
        self.assertEqual(connector.type, CONNECTOR_TYPE_CDP)

    def test_save_normalizes_shopify_type(self):
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ai",
            config={},
            status="connected",
        )
        connector.refresh_from_db()
        self.assertEqual(connector.type, CONNECTOR_TYPE_ECOMMERCE)

    def test_partial_save_still_persists_normalized_type(self):
        connector = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            config={},
            status="connected",
        )
        Connector.objects.filter(pk=connector.pk).update(type="crm")
        connector.refresh_from_db()
        self.assertEqual(connector.type, "crm")

        connector.status = "degraded"
        connector.save(update_fields=["status", "updated_at"])
        connector.refresh_from_db()
        self.assertEqual(connector.type, CONNECTOR_TYPE_CDP)
