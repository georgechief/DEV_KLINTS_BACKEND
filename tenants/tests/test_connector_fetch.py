"""Async connector fetch view tests (PRD-CONN-01 §8.2)."""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.models import DataRun
from tenants.connector_views import ShopifyFetchView
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User

TEST_SHOPIFY_SETTINGS = {
    "SHOPIFY_API_KEY": "test-client-id",
    "SHOPIFY_API_SECRET": "test-client-secret",
    "SHOPIFY_SCOPES": "read_orders,read_products",
    "SHOPIFY_API_VERSION": "2026-01",
    "BOOTSTRAP_DAYS": 30,
}


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyFetchViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ShopifyFetchView.as_view()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Acme", domain="acme.com"
        )
        self.admin = self._create_user("admin@acme.com", User.Role.ADMIN)
        self.viewer = self._create_user("viewer@acme.com", User.Role.VIEWER)
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders",
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

    def _create_user(self, email, role):
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=email.split("@")[0],
            tenant=self.tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _post(self, user, data=None):
        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            data or {},
            format="json",
        )
        force_authenticate(request, user=user)
        return self.view(request)

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_fetch_queues_bootstrap_and_returns_202(self, mock_bootstrap_task):
        mock_bootstrap_task.delay = MagicMock()

        response = self._post(self.admin, {"days": 10})

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["platform"], "shopify")
        self.assertEqual(response.data["status"], DataRun.Status.PENDING)
        self.assertEqual(response.data["days"], 10)
        self.assertIsNone(response.data["run_id"])
        self.assertEqual(response.data["detail"], "Bootstrap fetch queued.")
        mock_bootstrap_task.delay.assert_called_once()

        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.metadata.get("days"), 10)
        self.assertEqual(data_run.metadata.get("triggered_by"), "manual_fetch")

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_default_days_uses_bootstrap_days_setting(self, mock_bootstrap_task):
        mock_bootstrap_task.delay = MagicMock()

        response = self._post(self.admin)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["days"], 30)
        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.metadata.get("days"), 30)

    def test_requires_authentication(self):
        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/", {}, format="json"
        )
        response = self.view(request)
        self.assertEqual(response.status_code, 401)

    def test_viewer_forbidden(self):
        response = self._post(self.viewer)
        self.assertEqual(response.status_code, 403)

    def test_connector_not_connected_returns_404(self):
        self.connector.delete()
        response = self._post(self.admin)
        self.assertEqual(response.status_code, 404)

    def test_invalid_days_returns_400(self):
        response = self._post(self.admin, {"days": 0})
        self.assertEqual(response.status_code, 400)
        response = self._post(self.admin, {"days": 32})
        self.assertEqual(response.status_code, 400)

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_other_tenant_connector_not_used(self, mock_bootstrap_task):
        mock_bootstrap_task.delay = MagicMock()
        other_tenant = Tenant.objects.create(name="Rival", slug="rival")
        other_company = Company.objects.create(
            tenant=other_tenant, name="Rival", domain="rival.com"
        )
        other_admin = User.objects.create_user(
            email="admin@rival.com",
            password="TestPass123!",
            name="Rival Admin",
            tenant=other_tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        Connector.objects.create(
            company=other_company,
            name="shopify",
            type="ecommerce",
            config={},
            status="connected",
        )

        response = self._post(other_admin)
        self.assertEqual(response.status_code, 404)
        mock_bootstrap_task.delay.assert_not_called()
