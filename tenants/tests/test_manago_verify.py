import hashlib
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.connector_uniqueness import ERROR_CODE, PLATFORM_MANAGO
from tenants.connector_views import ConnectorVerifyView
from tenants.manago import ManagoVerifyResult, build_auth_payload, resolve_manago_api_base_url
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User

TEST_MANAGO_SETTINGS = {
    "MANAGO_API_BASE_URL": "https://app2.manago.ai",
}


@override_settings(**TEST_MANAGO_SETTINGS)
class ManagoAuthPayloadTests(SimpleTestCase):
    def test_sha_is_sha1_of_api_key_client_id_api_secret(self):
        payload = build_auth_payload(
            client_id="client-123",
            api_secret="secret-456",
        )
        expected = hashlib.sha1(
            f"{payload['apiKey']}client-123secret-456".encode("utf-8")
        ).hexdigest()
        self.assertEqual(payload["clientId"], "client-123")
        self.assertEqual(payload["sha"], expected)
        self.assertEqual(payload["sha"], payload["sha"].lower())
        self.assertIsInstance(payload["requestTime"], int)
        self.assertGreater(payload["requestTime"], 10**12)

    def test_resolve_manago_api_base_url_uses_setting_by_default(self):
        self.assertEqual(
            resolve_manago_api_base_url(),
            "https://app2.manago.ai",
        )

    def test_resolve_manago_api_base_url_honors_stored_connector_config(self):
        self.assertEqual(
            resolve_manago_api_base_url({"base_url": "https://legacy.manago.ai"}),
            "https://legacy.manago.ai",
        )


@override_settings(**TEST_MANAGO_SETTINGS)
class ConnectorVerifyViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ConnectorVerifyView.as_view()
        self.tenant = Tenant(name="Acme", slug="acme")
        self.user = User(
            email="admin@example.com",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )

    @patch("tenants.connector_views.verify_credentials")
    def test_verify_success_response(self, mock_verify):
        mock_verify.return_value = ManagoVerifyResult(
            valid=True,
            message="Credentials verified",
        )
        request = self.factory.post(
            "/api/v1/connectors/verify/",
            {
                "client_id": "c1",
                "api_secret": "s1",
                "endpoint": "https://app3.manago.ai",
            },
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"valid": True, "message": "Credentials verified"},
        )
        mock_verify.assert_called_once_with(
            client_id="c1",
            api_secret="s1",
            endpoint="https://app3.manago.ai",
        )

    def test_verify_requires_fields(self):
        request = self.factory.post(
            "/api/v1/connectors/verify/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = self.view(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("client_id", response.data)
        self.assertIn("api_secret", response.data)
        self.assertIn("endpoint", response.data)


@override_settings(**TEST_MANAGO_SETTINGS)
class ConnectorVerifyWarningTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ConnectorVerifyView.as_view()
        self.tenant_a = Tenant.objects.create(name="Tenant A", slug="tenant-a")
        self.tenant_b = Tenant.objects.create(name="Tenant B", slug="tenant-b")
        self.company_a = Company.objects.create(
            tenant=self.tenant_a,
            name="Company A",
            domain="company-a.com",
        )
        self.company_b = Company.objects.create(
            tenant=self.tenant_b,
            name="Company B",
            domain="company-b.com",
        )
        self.user_b = User.objects.create_user(
            email="admin-b@example.com",
            password="TestPass123!",
            name="Admin B",
            tenant=self.tenant_b,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        connector = Connector.objects.create(
            company=self.company_a,
            name="manago_ai",
            type="cdp",
            config={"workspace_id": "ws_prod"},
            status="connected",
            external_account_key="ws_prod",
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={"workspace_id": "ws_prod"},
        )

    @patch("tenants.connector_views.verify_credentials")
    def test_verify_returns_soft_warning_when_account_already_connected(
        self,
        mock_verify,
    ):
        mock_verify.return_value = ManagoVerifyResult(
            valid=True,
            message="Credentials verified",
        )
        request = self.factory.post(
            "/api/v1/connectors/verify/",
            {
                "client_id": "ws_prod",
                "api_secret": "s1",
                "endpoint": "https://app3.manago.ai",
            },
            format="json",
        )
        force_authenticate(request, user=self.user_b)
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["valid"])
        self.assertEqual(response.data["warning"]["code"], ERROR_CODE)
        self.assertEqual(response.data["warning"]["platform"], PLATFORM_MANAGO)
        self.assertEqual(response.data["warning"]["external_key"], "ws_prod")
        self.assertNotIn("tenant-a", str(response.data))
