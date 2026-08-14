from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from dataruns.connectors.shopify_token import (
    ShopifyAuthExpiredError,
    ensure_fresh_shopify_token,
)
from tenants.crypto import decrypt_api_key, encrypt_config
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant
from tenants.shopify import (
    TOKEN_MODE_EXPIRING,
    TOKEN_MODE_NON_EXPIRING,
    ShopifyOAuthError,
    ShopifyTokenBundle,
    exchange_code_for_token,
    refresh_offline_access_token,
    snapshot_safe_shopify_config,
    token_bundle_from_oauth_response,
)

TEST_SHOPIFY_SETTINGS = {
    "SHOPIFY_API_KEY": "test-client-id",
    "SHOPIFY_API_SECRET": "test-client-secret",
    "SHOPIFY_SCOPES": "read_orders,read_products",
    "SHOPIFY_OAUTH_REDIRECT_URI": (
        "http://localhost:8000/api/v1/connectors/shopify/callback/"
    ),
    "SHOPIFY_API_VERSION": "2026-01",
}


class TokenBundleParsingTests(SimpleTestCase):
    def test_expiring_response_parses_refresh_metadata(self):
        issued_at = datetime(2026, 7, 29, 10, 0, tzinfo=dt_timezone.utc)
        bundle = token_bundle_from_oauth_response(
            {
                "access_token": "shpat_new",
                "expires_in": 3600,
                "refresh_token": "shprt_new",
                "refresh_token_expires_in": 7776000,
                "scope": "read_orders",
            },
            issued_at=issued_at,
        )

        self.assertEqual(bundle.token_mode, TOKEN_MODE_EXPIRING)
        self.assertEqual(bundle.access_token, "shpat_new")
        self.assertEqual(bundle.refresh_token, "shprt_new")
        self.assertEqual(
            bundle.access_token_expires_at,
            "2026-07-29T11:00:00+00:00",
        )
        self.assertEqual(
            bundle.refresh_token_expires_at,
            "2026-10-27T10:00:00+00:00",
        )

    def test_non_expiring_response_sets_offline_non_expiring(self):
        bundle = token_bundle_from_oauth_response(
            {
                "access_token": "shpat_legacy",
                "scope": "read_orders",
            }
        )

        self.assertEqual(bundle.token_mode, TOKEN_MODE_NON_EXPIRING)
        self.assertIsNone(bundle.refresh_token)
        self.assertIsNone(bundle.access_token_expires_at)


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyExchangeAndRefreshTests(SimpleTestCase):
    @patch("tenants.shopify._post_form")
    def test_exchange_code_for_token_requests_expiring_offline_tokens(self, mock_post):
        mock_post.return_value = {
            "access_token": "shpat_new",
            "expires_in": 3600,
            "refresh_token": "shprt_new",
            "refresh_token_expires_in": 7776000,
            "scope": "read_orders",
        }

        bundle = exchange_code_for_token(
            shop="acme.myshopify.com",
            code="grant-code",
        )

        self.assertEqual(bundle.token_mode, TOKEN_MODE_EXPIRING)
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["expiring"], "1")

    @patch("urllib.request.urlopen")
    def test_refresh_offline_access_token_raises_on_inactive_refresh_401(
        self,
        mock_urlopen,
    ):
        import io
        import urllib.error

        body = json.dumps(
            {
                "error": "invalid_request",
                "error_description": "The refresh_token is inactive",
            }
        ).encode("utf-8")
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://acme.myshopify.com/admin/oauth/access_token",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(body),
        )

        with self.assertRaises(ShopifyOAuthError) as ctx:
            refresh_offline_access_token(
                shop="acme.myshopify.com",
                refresh_token="shprt_inactive",
            )

        self.assertIn("inactive", str(ctx.exception).lower())

    @patch("tenants.shopify._post_form_with_retry")
    def test_refresh_offline_access_token_uses_refresh_grant(self, mock_post):
        mock_post.return_value = {
            "access_token": "shpat_refreshed",
            "expires_in": 3600,
            "refresh_token": "shprt_rotated",
            "refresh_token_expires_in": 7776000,
            "scope": "read_orders",
        }

        bundle = refresh_offline_access_token(
            shop="acme.myshopify.com",
            refresh_token="shprt_old",
        )

        self.assertEqual(bundle.access_token, "shpat_refreshed")
        self.assertEqual(bundle.refresh_token, "shprt_rotated")
        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["grant_type"], "refresh_token")
        self.assertEqual(payload["refresh_token"], "shprt_old")


class EnsureFreshShopifyTokenTests(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )

    def _expiring_config(
        self,
        *,
        access_token: str = "shpat_old",
        refresh_token: str = "shprt_old",
        access_expires_at: datetime,
        refresh_expires_at: datetime,
    ) -> dict:
        return encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "shop_id": 42,
                "api_version": "2026-01",
                "scopes": "read_orders",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "access_token_expires_at": access_expires_at.isoformat(),
                "refresh_token_expires_at": refresh_expires_at.isoformat(),
                "token_mode": TOKEN_MODE_EXPIRING,
            }
        )

    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_refreshes_expired_access_token_and_saves_db(self, mock_refresh):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        mock_refresh.return_value = ShopifyTokenBundle(
            access_token="shpat_new",
            scope="read_orders",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_new",
            refresh_token_expires_at="2026-10-27T12:00:00+00:00",
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=self._expiring_config(
                access_expires_at=now - timedelta(minutes=5),
                refresh_expires_at=now + timedelta(days=30),
            ),
            status="connected",
        )

        with patch("django.utils.timezone.now", return_value=now):
            config = ensure_fresh_shopify_token(connector=connector)

        self.assertEqual(config["access_token"], "shpat_new")
        self.assertEqual(config["refresh_token"], "shprt_new")
        connector.refresh_from_db()
        self.assertEqual(
            decrypt_api_key(connector.config["access_token"]),
            "shpat_new",
        )
        mock_refresh.assert_called_once_with(
            shop="acme.myshopify.com",
            refresh_token="shprt_old",
        )

    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_skips_refresh_when_access_token_still_valid(self, mock_refresh):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=self._expiring_config(
                access_expires_at=now + timedelta(hours=1),
                refresh_expires_at=now + timedelta(days=30),
            ),
            status="connected",
        )

        with patch("django.utils.timezone.now", return_value=now):
            config = ensure_fresh_shopify_token(connector=connector)

        self.assertEqual(config["access_token"], "shpat_old")
        mock_refresh.assert_not_called()

    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_legacy_connector_skips_refresh(self, mock_refresh):
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=encrypt_config(
                {
                    "shop_domain": "acme.myshopify.com",
                    "access_token": "shpat_legacy",
                    "api_version": "2026-01",
                    "scopes": "read_orders",
                }
            ),
            status="connected",
        )

        config = ensure_fresh_shopify_token(connector=connector)

        self.assertEqual(config["access_token"], "shpat_legacy")
        mock_refresh.assert_not_called()

    def test_expired_refresh_token_raises_auth_expired(self):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=self._expiring_config(
                access_expires_at=now - timedelta(minutes=5),
                refresh_expires_at=now - timedelta(minutes=1),
            ),
            status="connected",
        )

        with patch("django.utils.timezone.now", return_value=now):
            with self.assertRaises(ShopifyAuthExpiredError):
                ensure_fresh_shopify_token(connector=connector)

    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_snapshot_never_contains_secrets_after_refresh(self, mock_refresh):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        mock_refresh.return_value = ShopifyTokenBundle(
            access_token="shpat_new",
            scope="read_orders",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_new",
            refresh_token_expires_at="2026-10-27T12:00:00+00:00",
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=self._expiring_config(
                access_expires_at=now - timedelta(minutes=5),
                refresh_expires_at=now + timedelta(days=30),
            ),
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com", "shop_id": 42},
        )

        with patch("django.utils.timezone.now", return_value=now):
            ensure_fresh_shopify_token(connector=connector)

        latest = ConnectorSnapshot.objects.filter(connector=connector).latest("version")
        self.assertNotIn("access_token", latest.snapshot_data)
        self.assertNotIn("refresh_token", latest.snapshot_data)
        self.assertEqual(latest.snapshot_data["token_mode"], TOKEN_MODE_EXPIRING)

    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_concurrent_refresh_only_calls_shopify_once(self, mock_refresh):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        refresh_calls: list[tuple[str, str]] = []
        refresh_lock = threading.Lock()

        def slow_refresh(*, shop, refresh_token):
            with refresh_lock:
                refresh_calls.append((shop, refresh_token))
            time.sleep(0.05)
            return ShopifyTokenBundle(
                access_token="shpat_new",
                scope="read_orders",
                token_mode=TOKEN_MODE_EXPIRING,
                access_token_expires_at="2026-07-29T13:00:00+00:00",
                refresh_token="shprt_new",
                refresh_token_expires_at="2026-10-27T12:00:00+00:00",
            )

        mock_refresh.side_effect = slow_refresh
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=self._expiring_config(
                access_expires_at=now - timedelta(minutes=5),
                refresh_expires_at=now + timedelta(days=30),
            ),
            status="connected",
        )

        errors: list[Exception] = []

        def worker():
            from django.db import connection

            connection.close()
            try:
                with patch("django.utils.timezone.now", return_value=now):
                    ensure_fresh_shopify_token(
                        connector=Connector.objects.get(pk=connector.pk)
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(refresh_calls), 1)
        self.assertLessEqual(len(refresh_calls), 2)
        connector.refresh_from_db()
        self.assertEqual(
            decrypt_api_key(connector.config["access_token"]),
            "shpat_new",
        )


class SnapshotSafeConfigTests(SimpleTestCase):
    def test_snapshot_safe_shopify_config_strips_secrets(self):
        safe = snapshot_safe_shopify_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_secret",
                "refresh_token": "shprt_secret",
                "token_mode": TOKEN_MODE_EXPIRING,
            }
        )
        self.assertEqual(safe["shop_domain"], "acme.myshopify.com")
        self.assertNotIn("access_token", safe)
        self.assertNotIn("refresh_token", safe)
