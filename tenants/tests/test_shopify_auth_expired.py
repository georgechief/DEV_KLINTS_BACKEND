"""CONN-05: Shopify terminal auth failure handling tests."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase, override_settings

from dataruns.connectors.shopify_token import (
    AUTH_FAILURE_REASON_EXPIRED,
    AUTH_FAILURE_REASON_FAILED,
    AUTH_FAILURE_REASON_INACTIVE,
    ShopifyAuthExpiredError,
    classify_shopify_terminal_auth_failure,
    ensure_fresh_shopify_token,
    mark_shopify_auth_expired,
)
from dataruns.dcs.fresh_import import DcsFreshImportError, refresh_connected_platforms_for_dcs
from dataruns.models import AuditLog, DataRun
from tenants.crypto import encrypt_config, masked_config
from tenants.models import Company, Connector, Tenant, User
from tenants.shopify import (
    TOKEN_MODE_EXPIRING,
    ShopifyOAuthError,
    ShopifyTokenBundle,
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


@override_settings(**TEST_SHOPIFY_SETTINGS)
class ShopifyAuthExpiredHelperTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
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
        self.connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config(
                {
                    "shop_domain": "acme.myshopify.com",
                    "access_token": "shpat_old",
                    "refresh_token": "shprt_old",
                    "access_token_expires_at": "2026-07-29T11:00:00+00:00",
                    "refresh_token_expires_at": "2026-10-30T04:54:58+00:00",
                    "token_mode": TOKEN_MODE_EXPIRING,
                    "api_version": "2026-01",
                    "scopes": "read_orders",
                }
            ),
        )

    def test_classify_inactive_refresh_as_terminal(self):
        exc = ShopifyOAuthError(
            "Shopify refresh token is inactive; reconnect required."
        )
        self.assertEqual(
            classify_shopify_terminal_auth_failure(exc),
            AUTH_FAILURE_REASON_INACTIVE,
        )

    def test_classify_local_expiry_as_terminal(self):
        exc = ShopifyAuthExpiredError(
            "Shopify refresh token expired; reconnect required."
        )
        self.assertEqual(
            classify_shopify_terminal_auth_failure(exc),
            AUTH_FAILURE_REASON_EXPIRED,
        )

    def test_classify_401_as_terminal(self):
        exc = ShopifyOAuthError("Shopify returned HTTP 401.")
        self.assertEqual(
            classify_shopify_terminal_auth_failure(exc),
            AUTH_FAILURE_REASON_FAILED,
        )

    def test_classify_503_as_retryable(self):
        exc = ShopifyOAuthError("Shopify returned HTTP 503.")
        self.assertIsNone(classify_shopify_terminal_auth_failure(exc))

    @patch("tenants.emails.send_email")
    def test_mark_auth_expired_transitions_status_and_audits(self, mock_send_email):
        transitioned = mark_shopify_auth_expired(
            connector=self.connector,
            company=self.company,
            reason_code=AUTH_FAILURE_REASON_INACTIVE,
            source="dcs_fresh_import",
            error_message="inactive",
        )
        self.assertTrue(transitioned)
        self.connector.refresh_from_db()
        self.assertEqual(self.connector.status, "error")
        from dataruns.connectors.base import decrypt_connector_config

        decrypted = decrypt_connector_config(self.connector.config)
        self.assertEqual(decrypted["auth_failure_reason"], AUTH_FAILURE_REASON_INACTIVE)
        self.assertIn("auth_failure_at", decrypted)

        audit = AuditLog.objects.filter(
            company=self.company, action="connector.auth_expired"
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.tone, AuditLog.Tone.RISK)
        self.assertEqual(mock_send_email.call_count, 1)

    @patch("tenants.emails.send_email")
    def test_mark_auth_expired_dedupes_when_already_error(self, mock_send_email):
        self.connector.status = "error"
        self.connector.save(update_fields=["status", "updated_at"])
        transitioned = mark_shopify_auth_expired(
            connector=self.connector,
            company=self.company,
            reason_code=AUTH_FAILURE_REASON_INACTIVE,
            source="dcs_fresh_import",
            error_message="inactive",
        )
        self.assertFalse(transitioned)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company, action="connector.auth_expired"
            ).count(),
            0,
        )
        mock_send_email.assert_not_called()

    @patch("tenants.emails.send_email")
    def test_masked_config_exposes_auth_failure_reason(self, mock_send_email):
        mark_shopify_auth_expired(
            connector=self.connector,
            company=self.company,
            reason_code=AUTH_FAILURE_REASON_INACTIVE,
            source="bootstrap",
            error_message="inactive",
        )
        self.connector.refresh_from_db()
        api_config = masked_config(self.connector.config)
        self.assertEqual(api_config["auth_failure_reason"], AUTH_FAILURE_REASON_INACTIVE)
        self.assertIn("auth_failure_at", api_config)

    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_successful_refresh_clears_auth_failure_metadata(self, mock_refresh):
        mark_shopify_auth_expired(
            connector=self.connector,
            company=self.company,
            reason_code=AUTH_FAILURE_REASON_INACTIVE,
            source="bootstrap",
            error_message="inactive",
        )
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        mock_refresh.return_value = ShopifyTokenBundle(
            access_token="shpat_new",
            scope="read_orders",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_new",
            refresh_token_expires_at="2026-10-30T04:54:58+00:00",
        )
        with patch("django.utils.timezone.now", return_value=now):
            config = ensure_fresh_shopify_token(connector=self.connector)
        self.assertNotIn("auth_failure_reason", config)
        self.assertNotIn("auth_failure_at", config)
        self.assertEqual(config["refresh_token"], "shprt_new")

    @patch("tenants.emails.send_email")
    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_dcs_fresh_import_marks_connector_on_inactive_refresh(
        self, mock_refresh, mock_send_email
    ):
        mock_refresh.side_effect = ShopifyOAuthError(
            "Shopify refresh token is inactive; reconnect required."
        )
        dcs_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-score",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": "dcs_score",
                "company_id": str(self.company.id),
            },
        )
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        with patch("django.utils.timezone.now", return_value=now):
            with self.assertRaises(DcsFreshImportError):
                refresh_connected_platforms_for_dcs(
                    company=self.company,
                    dcs_data_run=dcs_run,
                    days=30,
                )
        self.connector.refresh_from_db()
        self.assertEqual(self.connector.status, "error")
        self.assertEqual(mock_send_email.call_count, 1)

    @patch("tenants.emails.send_email")
    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_refresh_rotation_persists_new_refresh_token(self, mock_refresh, _mock_email):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        mock_refresh.return_value = ShopifyTokenBundle(
            access_token="shpat_new",
            scope="read_orders",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_rotated",
            refresh_token_expires_at="2026-10-30T04:54:58+00:00",
        )
        with patch("django.utils.timezone.now", return_value=now):
            config = ensure_fresh_shopify_token(connector=self.connector)
        self.assertEqual(config["refresh_token"], "shprt_rotated")
        self.connector.refresh_from_db()
        from dataruns.connectors.base import decrypt_connector_config

        stored = decrypt_connector_config(self.connector.config)
        self.assertEqual(stored["refresh_token"], "shprt_rotated")

    @patch("tenants.emails.send_email")
    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_dcs_fresh_import_503_leaves_connector_connected(
        self, mock_refresh, mock_send_email
    ):
        mock_refresh.side_effect = ShopifyOAuthError("Shopify returned HTTP 503.")
        dcs_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-score",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": "dcs_score",
                "company_id": str(self.company.id),
            },
        )
        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        with patch("django.utils.timezone.now", return_value=now):
            with self.assertRaises(DcsFreshImportError):
                refresh_connected_platforms_for_dcs(
                    company=self.company,
                    dcs_data_run=dcs_run,
                    days=30,
                )
        self.connector.refresh_from_db()
        self.assertEqual(self.connector.status, "connected")
        mock_send_email.assert_not_called()
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company, action="connector.auth_expired"
            ).count(),
            0,
        )

    @patch("dataruns.dcs.orchestrate.run_dcs_pipeline")
    @patch("tenants.emails.send_email")
    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    def test_live_revalidate_marks_connector_on_terminal_refresh_failure(
        self, mock_refresh, mock_send_email, mock_pipeline
    ):
        from dataruns.dcs.constants import DCS_SCORE_KIND
        from dataruns.tasks import run_dcs_score

        mock_refresh.side_effect = ShopifyOAuthError(
            "Shopify refresh token is inactive; reconnect required."
        )
        dcs_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-score",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "live_revalidate": True,
            },
        )
        result = run_dcs_score.run(dcs_run.id)
        self.assertFalse(result["ok"])
        self.connector.refresh_from_db()
        self.assertEqual(self.connector.status, "error")
        mock_send_email.assert_called_once()
        mock_pipeline.assert_not_called()
        dcs_run.refresh_from_db()
        self.assertEqual(dcs_run.status, DataRun.Status.FAILED)
        self.assertTrue(dcs_run.metadata.get("auth_failed"))
