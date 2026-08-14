import hashlib
import hmac as hmac_lib
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from tenants.connector_views import (
    SHOPIFY_STATE_SALT,
    ShopifyOAuthCallbackView,
    ShopifyOAuthStartView,
)
from tenants.crypto import decrypt_api_key
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User
from tenants.shopify import (
    ShopifyOAuthError,
    ShopifyToken,
    ShopifyTokenBundle,
    TOKEN_MODE_EXPIRING,
    build_authorize_url,
    normalize_shop_domain,
    verify_callback_hmac,
)

TEST_SHOPIFY_SETTINGS = {
    "SHOPIFY_API_KEY": "test-client-id",
    "SHOPIFY_API_SECRET": "test-client-secret",
    "SHOPIFY_SCOPES": "read_orders,read_products",
    "SHOPIFY_OAUTH_REDIRECT_URI": (
        "http://localhost:8000/api/v1/connectors/shopify/callback/"
    ),
}


def _sign_params(params: dict, secret: str) -> dict:
    message = "&".join(
        f"{key}={value}" for key, value in sorted(params.items())
    )
    digest = hmac_lib.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {**params, "hmac": digest}


class NormalizeShopDomainTests(SimpleTestCase):
    def test_accepts_bare_handle(self):
        self.assertEqual(
            normalize_shop_domain("acme"), "acme.myshopify.com"
        )

    def test_accepts_full_domain_with_scheme(self):
        self.assertEqual(
            normalize_shop_domain("https://Acme-Store.myshopify.com/"),
            "acme-store.myshopify.com",
        )

    def test_rejects_other_domains(self):
        with self.assertRaises(ShopifyOAuthError):
            normalize_shop_domain("evil.example.com")

    def test_rejects_empty(self):
        with self.assertRaises(ShopifyOAuthError):
            normalize_shop_domain("")


@override_settings(**TEST_SHOPIFY_SETTINGS)
class AuthorizeUrlAndHmacTests(SimpleTestCase):
    def test_authorize_url_contains_oauth_params(self):
        url = build_authorize_url(shop="acme.myshopify.com", state="st4te")
        self.assertTrue(
            url.startswith("https://acme.myshopify.com/admin/oauth/authorize?")
        )
        self.assertIn("client_id=test-client-id", url)
        self.assertIn("scope=read_orders%2Cread_products", url)
        self.assertIn("state=st4te", url)
        self.assertIn("redirect_uri=", url)

    def test_valid_hmac_passes(self):
        params = _sign_params(
            {"code": "c", "shop": "acme.myshopify.com", "state": "s"},
            "test-client-secret",
        )
        self.assertTrue(verify_callback_hmac(params))

    def test_tampered_params_fail(self):
        params = _sign_params(
            {"code": "c", "shop": "acme.myshopify.com", "state": "s"},
            "test-client-secret",
        )
        params["shop"] = "other.myshopify.com"
        self.assertFalse(verify_callback_hmac(params))

    def test_missing_hmac_fails(self):
        self.assertFalse(verify_callback_hmac({"code": "c"}))


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyOAuthStartViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ShopifyOAuthStartView.as_view()
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

    def _post(self, user, data):
        request = self.factory.post(
            "/api/v1/connectors/shopify/start/", data, format="json"
        )
        force_authenticate(request, user=user)
        return self.view(request)

    def test_returns_authorize_url_with_signed_state(self):
        response = self._post(self.admin, {"shop": "acme"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["shop"], "acme.myshopify.com")
        self.assertIn(
            "https://acme.myshopify.com/admin/oauth/authorize?",
            response.data["authorize_url"],
        )

    def test_viewer_forbidden(self):
        viewer = User.objects.create_user(
            email="viewer@acme.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )
        response = self._post(viewer, {"shop": "acme"})
        self.assertEqual(response.status_code, 403)

    def test_invalid_shop_rejected(self):
        response = self._post(self.admin, {"shop": "nope.example.com"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("shop", response.data)

    @override_settings(SHOPIFY_API_KEY="", SHOPIFY_API_SECRET="")
    def test_unconfigured_returns_503(self):
        response = self._post(self.admin, {"shop": "acme"})
        self.assertEqual(response.status_code, 503)


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyOAuthCallbackViewTests(TestCase):
    shop = "acme.myshopify.com"

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ShopifyOAuthCallbackView.as_view()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Acme", domain="acme.com"
        )

    def _state(self, **overrides):
        payload = {
            "user_id": "unused",
            "company_id": str(self.company.id),
            "shop": self.shop,
            "return_to": "",
            **overrides,
        }
        return signing.dumps(payload, salt=SHOPIFY_STATE_SALT)

    def _get(self, params):
        request = self.factory.get(
            "/api/v1/connectors/shopify/callback/", params
        )
        return self.view(request)

    def _callback_params(self, state=None):
        return _sign_params(
            {
                "code": "grant-code",
                "shop": self.shop,
                "state": state or self._state(),
                "timestamp": "1700000000",
            },
            "test-client-secret",
        )

    @patch("tenants.shopify.fetch_shop")
    @patch("tenants.shopify.exchange_code_for_token")
    def test_success_creates_connector_and_snapshot(
        self, mock_exchange, mock_fetch
    ):
        mock_exchange.return_value = ShopifyTokenBundle(
            access_token="shpat_secret_token",
            scope="read_orders,read_products",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_secret",
            refresh_token_expires_at="2026-10-27T12:00:00+00:00",
        )
        mock_fetch.return_value = {"id": 42, "name": "Acme Store"}

        response = self._get(self._callback_params())

        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify=connected", response.url)

        connector = Connector.objects.get(company=self.company, name="shopify")
        self.assertEqual(connector.type, "ecommerce")
        self.assertEqual(connector.status, "connected")
        self.assertEqual(connector.config["shop_domain"], self.shop)
        self.assertNotEqual(
            connector.config["access_token"], "shpat_secret_token"
        )
        self.assertEqual(
            decrypt_api_key(connector.config["access_token"]),
            "shpat_secret_token",
        )
        self.assertEqual(connector.config["token_mode"], TOKEN_MODE_EXPIRING)
        self.assertEqual(
            decrypt_api_key(connector.config["refresh_token"]),
            "shprt_secret",
        )

        snapshot = ConnectorSnapshot.objects.get(connector=connector)
        self.assertEqual(snapshot.version, 1)
        self.assertNotIn("access_token", snapshot.snapshot_data)
        self.assertNotIn("refresh_token", snapshot.snapshot_data)
        self.assertEqual(snapshot.snapshot_data["shop_id"], 42)

    @patch("tenants.shopify.fetch_shop")
    @patch("tenants.shopify.exchange_code_for_token")
    def test_reconnect_updates_existing_connector(
        self, mock_exchange, mock_fetch
    ):
        mock_exchange.return_value = ShopifyTokenBundle(
            access_token="shpat_first",
            scope="read_orders",
        )
        mock_fetch.return_value = {"id": 42, "name": "Acme Store"}
        self._get(self._callback_params())

        mock_exchange.return_value = ShopifyTokenBundle(
            access_token="shpat_second",
            scope="read_orders",
        )
        response = self._get(self._callback_params(state=self._state()))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Connector.objects.filter(
                company=self.company, name="shopify"
            ).count(),
            1,
        )
        connector = Connector.objects.get(company=self.company, name="shopify")
        self.assertEqual(
            decrypt_api_key(connector.config["access_token"]), "shpat_second"
        )
        versions = list(
            ConnectorSnapshot.objects.filter(connector=connector)
            .order_by("version")
            .values_list("version", flat=True)
        )
        self.assertEqual(versions, [1, 2])

    def test_invalid_state_redirects_with_error(self):
        params = self._callback_params(state="garbage")
        response = self._get(params)
        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify=error", response.url)
        self.assertIn("reason=invalid_state", response.url)
        self.assertFalse(Connector.objects.exists())

    def test_invalid_hmac_redirects_with_error(self):
        params = self._callback_params()
        params["hmac"] = "0" * 64
        response = self._get(params)
        self.assertEqual(response.status_code, 302)
        self.assertIn("reason=invalid_hmac", response.url)
        self.assertFalse(Connector.objects.exists())

    def test_shop_mismatch_redirects_with_error(self):
        params = self._callback_params(
            state=self._state(shop="other.myshopify.com")
        )
        response = self._get(params)
        self.assertEqual(response.status_code, 302)
        self.assertIn("reason=shop_mismatch", response.url)
        self.assertFalse(Connector.objects.exists())
