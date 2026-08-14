from unittest.mock import MagicMock, patch
import hashlib
import hmac as hmac_lib

from django.core import signing
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.models import DataRun
from tenants.connector_uniqueness import (
    ERROR_CODE,
    PLATFORM_MANAGO,
    PLATFORM_SHOPIFY,
    AccountAlreadyConnectedError,
    assert_external_account_available,
    find_manago_owner,
    find_shopify_owner,
)
from tenants.connector_views import (
    SHOPIFY_STATE_SALT,
    ConnectorDisconnectView,
    ConnectorListCreateView,
    ShopifyOAuthCallbackView,
    ShopifyOAuthStartView,
)
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User
from tenants.shopify import ShopifyToken

TEST_SHOPIFY_SETTINGS = {
    "SHOPIFY_API_KEY": "test-client-id",
    "SHOPIFY_API_SECRET": "test-client-secret",
    "SHOPIFY_SCOPES": "read_orders,read_products",
    "SHOPIFY_OAUTH_REDIRECT_URI": (
        "http://localhost:8000/api/v1/connectors/shopify/callback/"
    ),
    "SHOPIFY_API_VERSION": "2026-01",
    "FRONTEND_SHOPIFY_REDIRECT_URL": "http://localhost:5173/integrations",
}


def _sign_shopify_callback_params(params: dict, secret: str) -> dict:
    message = "&".join(
        f"{key}={value}" for key, value in sorted(params.items())
    )
    digest = hmac_lib.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {**params, "hmac": digest}


class ConnectorUniquenessTestBase(TestCase):
    def setUp(self):
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

    def _create_shopify_connector(
        self,
        *,
        company,
        status="connected",
        config=None,
        snapshot_data=None,
        versions=None,
    ):
        connector = Connector.objects.create(
            company=company,
            name="shopify",
            type="ecommerce",
            config=config or {},
            status=status,
        )
        if versions is not None:
            for version, data in versions:
                ConnectorSnapshot.objects.create(
                    connector=connector,
                    version=version,
                    snapshot_data=data,
                )
        elif snapshot_data is not None:
            ConnectorSnapshot.objects.create(
                connector=connector,
                version=1,
                snapshot_data=snapshot_data,
            )
        return connector

    def _create_manago_connector(
        self,
        *,
        company,
        status="connected",
        config=None,
        snapshot_data=None,
    ):
        connector = Connector.objects.create(
            company=company,
            name="manago_ai",
            type="cdp",
            config=config or {},
            status=status,
        )
        if snapshot_data is not None:
            ConnectorSnapshot.objects.create(
                connector=connector,
                version=1,
                snapshot_data=snapshot_data,
            )
        return connector


class FindShopifyOwnerTests(ConnectorUniquenessTestBase):
    def test_no_owner_when_no_connectors(self):
        self.assertIsNone(
            find_shopify_owner(shop_domain="acme.myshopify.com")
        )

    def test_connected_owner_found_via_snapshot(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={
                "shop_domain": "acme.myshopify.com",
                "shop_id": 42,
            },
        )
        found = find_shopify_owner(shop_domain="acme.myshopify.com")
        self.assertEqual(found, owner)

    def test_degraded_owner_found(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            status="degraded",
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        found = find_shopify_owner(shop_domain="acme.myshopify.com")
        self.assertEqual(found, owner)

    def test_error_status_ignored(self):
        self._create_shopify_connector(
            company=self.company_a,
            status="error",
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        self.assertIsNone(find_shopify_owner(shop_domain="acme.myshopify.com"))

    def test_config_fallback_when_no_snapshot(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            config={"shop_domain": "acme.myshopify.com", "shop_id": 99},
        )
        found = find_shopify_owner(shop_domain="acme.myshopify.com")
        self.assertEqual(found, owner)

    def test_latest_snapshot_wins(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            versions=[
                (1, {"shop_domain": "old.myshopify.com", "shop_id": 1}),
                (2, {"shop_domain": "acme.myshopify.com", "shop_id": 42}),
            ],
        )
        found = find_shopify_owner(shop_domain="acme.myshopify.com")
        self.assertEqual(found, owner)

    def test_shop_domain_normalized_on_lookup(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        found = find_shopify_owner(shop_domain="Acme")
        self.assertEqual(found, owner)

    def test_shop_id_secondary_lookup(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={"shop_domain": "other.myshopify.com", "shop_id": 42},
        )
        found = find_shopify_owner(
            shop_domain="unrelated.myshopify.com",
            shop_id=42,
        )
        self.assertEqual(found, owner)

    def test_find_shopify_owner_uses_external_account_key_index(self):
        owner = self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={"shop_domain": "acme.myshopify.com", "shop_id": 42},
        )
        owner.external_account_key = "acme.myshopify.com"
        owner.save(update_fields=["external_account_key"])

        found = find_shopify_owner(shop_domain="acme.myshopify.com")

        self.assertEqual(found, owner)


class FindManagoOwnerTests(ConnectorUniquenessTestBase):
    def test_no_owner_when_no_connectors(self):
        self.assertIsNone(find_manago_owner(workspace_id="ws_prod"))

    def test_connected_owner_found_via_snapshot(self):
        owner = self._create_manago_connector(
            company=self.company_a,
            snapshot_data={"workspace_id": "ws_prod"},
        )
        found = find_manago_owner(workspace_id="ws_prod")
        self.assertEqual(found, owner)

    def test_degraded_owner_found(self):
        owner = self._create_manago_connector(
            company=self.company_a,
            status="degraded",
            snapshot_data={"workspace_id": "ws_prod"},
        )
        found = find_manago_owner(workspace_id="ws_prod")
        self.assertEqual(found, owner)

    def test_error_status_ignored(self):
        self._create_manago_connector(
            company=self.company_a,
            status="error",
            snapshot_data={"workspace_id": "ws_prod"},
        )
        self.assertIsNone(find_manago_owner(workspace_id="ws_prod"))

    def test_config_fallback_workspace_id(self):
        owner = self._create_manago_connector(
            company=self.company_a,
            config={"workspace_id": "ws_prod", "base_url": "https://app2.manago.ai"},
        )
        found = find_manago_owner(workspace_id="ws_prod")
        self.assertEqual(found, owner)

    def test_config_fallback_client_id(self):
        owner = self._create_manago_connector(
            company=self.company_a,
            config={"client_id": "legacy-client", "base_url": "https://app2.manago.ai"},
        )
        found = find_manago_owner(workspace_id="legacy-client")
        self.assertEqual(found, owner)

    def test_workspace_id_is_case_sensitive(self):
        self._create_manago_connector(
            company=self.company_a,
            snapshot_data={"workspace_id": "ws_Prod"},
        )
        self.assertIsNone(find_manago_owner(workspace_id="ws_prod"))


class AssertExternalAccountAvailableTests(ConnectorUniquenessTestBase):
    def test_same_company_shopify_allowed(self):
        self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        assert_external_account_available(
            platform=PLATFORM_SHOPIFY,
            external_key="acme.myshopify.com",
            company=self.company_a,
        )

    def test_same_company_manago_allowed(self):
        self._create_manago_connector(
            company=self.company_a,
            snapshot_data={"workspace_id": "ws_prod"},
        )
        assert_external_account_available(
            platform=PLATFORM_MANAGO,
            external_key="ws_prod",
            company=self.company_a,
        )

    def test_other_company_shopify_raises(self):
        self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        with self.assertRaises(AccountAlreadyConnectedError) as ctx:
            assert_external_account_available(
                platform=PLATFORM_SHOPIFY,
                external_key="acme.myshopify.com",
                company=self.company_b,
            )
        exc = ctx.exception
        self.assertEqual(exc.platform, PLATFORM_SHOPIFY)
        self.assertEqual(exc.external_key, "acme.myshopify.com")
        self.assertEqual(exc.code, ERROR_CODE)
        self.assertIn("Shopify", exc.detail)
        self.assertNotIn("Company A", exc.detail)
        self.assertNotIn("tenant-a", exc.detail)

    def test_other_company_manago_raises(self):
        self._create_manago_connector(
            company=self.company_a,
            snapshot_data={"workspace_id": "ws_prod"},
        )
        with self.assertRaises(AccountAlreadyConnectedError) as ctx:
            assert_external_account_available(
                platform=PLATFORM_MANAGO,
                external_key="ws_prod",
                company=self.company_b,
            )
        exc = ctx.exception
        self.assertEqual(exc.platform, PLATFORM_MANAGO)
        self.assertEqual(exc.external_key, "ws_prod")
        self.assertEqual(exc.code, ERROR_CODE)
        self.assertIn("Manago", exc.detail)
        self.assertNotIn("Company A", exc.detail)
        self.assertNotIn("tenant-a", exc.detail)

    def test_unowned_account_allowed(self):
        assert_external_account_available(
            platform=PLATFORM_SHOPIFY,
            external_key="new.myshopify.com",
            company=self.company_b,
        )
        assert_external_account_available(
            platform=PLATFORM_MANAGO,
            external_key="ws_new",
            company=self.company_b,
        )

    def test_error_status_does_not_block_other_company(self):
        self._create_shopify_connector(
            company=self.company_a,
            status="error",
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )
        assert_external_account_available(
            platform=PLATFORM_SHOPIFY,
            external_key="acme.myshopify.com",
            company=self.company_b,
        )


class ManagoCreateUniquenessApiTests(ConnectorUniquenessTestBase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.admin_a = self._create_user(
            "admin-a@company-a.com",
            User.Role.ADMIN,
            tenant=self.tenant_a,
        )
        self.admin_b = self._create_user(
            "admin-b@company-b.com",
            User.Role.ADMIN,
            tenant=self.tenant_b,
        )

    def _create_user(self, email, role, tenant):
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=email.split("@")[0],
            tenant=tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _manago_payload(self, workspace_id="ws_prod"):
        return {
            "name": "manago_ai",
            "type": "cdp",
            "config": {
                "base_url": "https://app2.manago.ai",
                "workspace_id": workspace_id,
                "api_key": "mnago_live_sk_secret",
            },
        }

    def _post_manago(self, user, workspace_id="ws_prod"):
        request = self.factory.post(
            "/api/v1/connectors/",
            self._manago_payload(workspace_id=workspace_id),
            format="json",
        )
        force_authenticate(request, user=user)
        return ConnectorListCreateView.as_view()(request)

    @patch("tenants.connector_views.enqueue_connector_bootstrap")
    def test_company_a_connects_manago_successfully(self, mock_bootstrap):
        mock_bootstrap.return_value = MagicMock(
            data_run=MagicMock(id="bootstrap-run-a", metadata={"days": 30}),
            task_queued=True,
        )

        response = self._post_manago(self.admin_a)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Connector.objects.filter(
                company=self.company_a,
                name="manago_ai",
            ).exists()
        )
        mock_bootstrap.assert_called_once()

    @patch("tenants.connector_views.enqueue_connector_bootstrap")
    def test_company_b_blocked_with_account_already_connected(self, mock_bootstrap):
        self._create_manago_connector(
            company=self.company_a,
            snapshot_data={"workspace_id": "ws_prod"},
        )
        data_runs_before = DataRun.objects.count()

        response = self._post_manago(self.admin_b)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], ERROR_CODE)
        self.assertEqual(response.data["platform"], PLATFORM_MANAGO)
        self.assertEqual(response.data["external_key"], "ws_prod")
        self.assertIn("detail", response.data)
        self.assertIn("Manago", response.data["detail"])
        self.assertNotIn("Company A", response.data["detail"])
        self.assertNotIn("tenant-a", str(response.data))
        self.assertNotIn(self.admin_a.email, str(response.data))
        self.assertFalse(
            Connector.objects.filter(
                company=self.company_b,
                name="manago_ai",
            ).exists()
        )
        self.assertEqual(DataRun.objects.count(), data_runs_before)
        mock_bootstrap.assert_not_called()

    @patch("tenants.connector_views.enqueue_connector_bootstrap")
    def test_same_company_duplicate_uses_existing_message(self, mock_bootstrap):
        self._create_manago_connector(
            company=self.company_a,
            snapshot_data={"workspace_id": "ws_prod"},
        )

        response = self._post_manago(self.admin_a)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data, {"detail": "Connector already connected."})
        self.assertNotIn("code", response.data)
        mock_bootstrap.assert_not_called()


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyStartUniquenessApiTests(ConnectorUniquenessTestBase):
    shop = "acme.myshopify.com"

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.admin_a = self._create_user(
            "admin-a@company-a.com",
            User.Role.ADMIN,
            tenant=self.tenant_a,
        )
        self.admin_b = self._create_user(
            "admin-b@company-b.com",
            User.Role.ADMIN,
            tenant=self.tenant_b,
        )

    def _create_user(self, email, role, tenant):
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=email.split("@")[0],
            tenant=tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _post_shopify_start(self, user, shop="acme"):
        request = self.factory.post(
            "/api/v1/connectors/shopify/start/",
            {"shop": shop},
            format="json",
        )
        force_authenticate(request, user=user)
        return ShopifyOAuthStartView.as_view()(request)

    def test_company_a_shopify_start_succeeds(self):
        response = self._post_shopify_start(self.admin_a)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["shop"], self.shop)
        self.assertIn("authorize_url", response.data)

    @patch("tenants.connector_views.enqueue_connector_bootstrap")
    def test_company_b_blocked_with_account_already_connected(self, _mock_bootstrap):
        self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={
                "shop_domain": self.shop,
                "shop_id": 42,
            },
        )

        response = self._post_shopify_start(self.admin_b)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], ERROR_CODE)
        self.assertEqual(response.data["platform"], PLATFORM_SHOPIFY)
        self.assertEqual(response.data["external_key"], self.shop)
        self.assertIn("Shopify", response.data["detail"])
        self.assertNotIn("Company A", response.data["detail"])
        self.assertNotIn("tenant-a", str(response.data))
        self.assertNotIn(self.admin_a.email, str(response.data))

    def test_same_company_reconnect_allowed_at_start(self):
        self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={
                "shop_domain": self.shop,
                "shop_id": 42,
            },
        )

        response = self._post_shopify_start(self.admin_a)

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorize_url", response.data)

    def test_disconnect_clears_ownership_for_other_company(self):
        connector = self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={
                "shop_domain": self.shop,
                "shop_id": 42,
            },
        )
        blocked = self._post_shopify_start(self.admin_b)
        self.assertEqual(blocked.status_code, 409)

        request = self.factory.delete(f"/api/v1/connectors/{connector.id}/")
        force_authenticate(request, user=self.admin_a)
        disconnect_response = ConnectorDisconnectView.as_view()(
            request,
            pk=str(connector.id),
        )
        self.assertEqual(disconnect_response.status_code, 200)

        allowed = self._post_shopify_start(self.admin_b)
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("authorize_url", allowed.data)


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyCallbackUniquenessApiTests(ConnectorUniquenessTestBase):
    shop = "acme.myshopify.com"

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.admin_a = self._create_user(
            "admin-a@company-a.com",
            User.Role.ADMIN,
            tenant=self.tenant_a,
        )

    def _create_user(self, email, role, tenant):
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=email.split("@")[0],
            tenant=tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _state(self, company, **overrides):
        payload = {
            "user_id": "unused",
            "company_id": str(company.id),
            "shop": self.shop,
            "return_to": "http://localhost:5173/onboarding",
            **overrides,
        }
        return signing.dumps(payload, salt=SHOPIFY_STATE_SALT)

    def _callback_params(self, company, state=None):
        return _sign_shopify_callback_params(
            {
                "code": "grant-code",
                "shop": self.shop,
                "state": state or self._state(company),
                "timestamp": "1700000000",
            },
            "test-client-secret",
        )

    def _get_callback(self, params):
        request = self.factory.get(
            "/api/v1/connectors/shopify/callback/",
            params,
        )
        return ShopifyOAuthCallbackView.as_view()(request)

    @patch("tenants.connector_views.enqueue_connector_bootstrap")
    @patch("tenants.shopify.fetch_shop")
    @patch("tenants.shopify.exchange_code_for_token")
    def test_company_b_callback_redirects_account_already_connected(
        self,
        mock_exchange,
        mock_fetch,
        mock_bootstrap,
    ):
        self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={
                "shop_domain": self.shop,
                "shop_id": 42,
            },
        )
        mock_exchange.return_value = ShopifyToken(
            access_token="shpat_secret_token",
            scope="read_orders,read_products",
        )
        mock_fetch.return_value = {"id": 42, "name": "Acme Store"}
        data_runs_before = DataRun.objects.count()

        response = self._get_callback(self._callback_params(self.company_b))

        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify=error", response.url)
        self.assertIn("reason=account_already_connected", response.url)
        self.assertFalse(
            Connector.objects.filter(
                company=self.company_b,
                name="shopify",
            ).exists()
        )
        self.assertEqual(DataRun.objects.count(), data_runs_before)
        mock_bootstrap.assert_not_called()

    @patch("tenants.connector_views.enqueue_connector_bootstrap")
    @patch("tenants.shopify.fetch_shop")
    @patch("tenants.shopify.exchange_code_for_token")
    def test_company_a_reconnect_own_shop_succeeds(
        self,
        mock_exchange,
        mock_fetch,
        mock_bootstrap,
    ):
        self._create_shopify_connector(
            company=self.company_a,
            snapshot_data={
                "shop_domain": self.shop,
                "shop_id": 42,
            },
        )
        mock_bootstrap.return_value = MagicMock(
            data_run=MagicMock(id="bootstrap-run-a", metadata={"days": 30}),
            task_queued=True,
        )
        mock_exchange.return_value = ShopifyToken(
            access_token="shpat_secret_token",
            scope="read_orders,read_products",
        )
        mock_fetch.return_value = {"id": 42, "name": "Acme Store"}

        response = self._get_callback(self._callback_params(self.company_a))

        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify=connected", response.url)
        self.assertEqual(
            Connector.objects.filter(
                company=self.company_a,
                name="shopify",
            ).count(),
            1,
        )
        mock_bootstrap.assert_called_once()
