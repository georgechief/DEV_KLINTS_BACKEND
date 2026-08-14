import uuid

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.connector_views import ConnectorDisconnectView
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User


class ConnectorDisconnectViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ConnectorDisconnectView.as_view()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Acme", domain="acme.com"
        )
        self.admin = self._create_user("admin@acme.com", User.Role.ADMIN)
        self.shopify = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "acme.myshopify.com"},
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=self.shopify,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )

    def _create_user(self, email, role, tenant=None):
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=email.split("@")[0],
            tenant=tenant or self.tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _delete(self, user, connector_id):
        request = self.factory.delete(f"/api/v1/connectors/{connector_id}/")
        force_authenticate(request, user=user)
        return self.view(request, pk=connector_id)

    def test_admin_disconnects_shopify(self):
        response = self._delete(self.admin, self.shopify.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "detail": "Connector disconnected.",
                "id": str(self.shopify.id),
                "name": "shopify",
                "needs_connector": True,
            },
        )
        self.assertFalse(Connector.objects.filter(pk=self.shopify.id).exists())
        self.assertFalse(
            ConnectorSnapshot.objects.filter(connector_id=self.shopify.id).exists()
        )

    def test_disconnect_manago_reports_remaining_connected(self):
        manago = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            config={"base_url": "https://api.manago.ai"},
            status="connected",
        )
        response = self._delete(self.admin, manago.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "manago_ai")
        # Shopify connector is still connected, so no reconnect prompt needed.
        self.assertFalse(response.data["needs_connector"])
        self.assertTrue(Connector.objects.filter(pk=self.shopify.id).exists())

    def test_viewer_forbidden(self):
        viewer = self._create_user("viewer@acme.com", User.Role.VIEWER)
        response = self._delete(viewer, self.shopify.id)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Connector.objects.filter(pk=self.shopify.id).exists())

    def test_other_company_connector_not_found(self):
        other_tenant = Tenant.objects.create(name="Rival", slug="rival")
        other_company = Company.objects.create(
            tenant=other_tenant, name="Rival", domain="rival.com"
        )
        other_connector = Connector.objects.create(
            company=other_company,
            name="shopify",
            type="ecommerce",
            config={},
            status="connected",
        )
        response = self._delete(self.admin, other_connector.id)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            Connector.objects.filter(pk=other_connector.id).exists()
        )

    def test_unknown_id_not_found(self):
        response = self._delete(self.admin, uuid.uuid4())
        self.assertEqual(response.status_code, 404)
