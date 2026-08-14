"""PRD-CONN-01 §12 acceptance tests for on-connect bootstrap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.connectors.base import CONNECTOR_BOOTSTRAP_KIND, enqueue_connector_bootstrap
from dataruns.models import Contact, DataRun, Order
from tenants.connector_views import (
    SHOPIFY_STATE_SALT,
    ConnectorBootstrapStatusView,
    ConnectorListCreateView,
    ShopifyOAuthCallbackView,
    ShopifyFetchView,
    ManagoFetchView,
)
from tenants.crypto import decrypt_api_key, encrypt_config
from tenants.manago import ManagoVerifyResult
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant, User
from tenants.shopify import ShopifyToken, ShopifyTokenBundle, TOKEN_MODE_EXPIRING
from tenants.tests.bootstrap_test_helpers import (
    assert_connector_status_matches_summary,
    assert_health_report_shape,
    successful_run_import_side_effect,
)
from tenants.tests.test_shopify_oauth import TEST_SHOPIFY_SETTINGS, _sign_params

BOOTSTRAP_TEST_SETTINGS = {
    **TEST_SHOPIFY_SETTINGS,
    "BOOTSTRAP_DAYS": 30,
    "CELERY_TASK_ALWAYS_EAGER": True,
    "CELERY_TASK_EAGER_PROPAGATES": True,
    "MANAGO_API_BASE_URL": "https://app2.manago.ai",
    "FRONTEND_SHOPIFY_REDIRECT_URL": "https://app.example/integrations",
}


@override_settings(**BOOTSTRAP_TEST_SETTINGS)
class ConnectorBootstrapAcceptanceTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Acme", domain="acme.com"
        )
        self.admin = self._create_user("admin@acme.com", User.Role.ADMIN)
        self.unverified_admin = User.objects.create_user(
            email="unverified@acme.com",
            password="TestPass123!",
            name="Unverified",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=False,
            is_active=True,
        )

    def _create_user(self, email: str, role: str) -> User:
        return User.objects.create_user(
            email=email,
            password="TestPass123!",
            name=email.split("@")[0],
            tenant=self.tenant,
            role=role,
            email_verified=True,
            is_active=True,
        )

    def _manago_config(self) -> dict:
        return {
            "base_url": "https://app2.manago.ai",
            "workspace_id": "workspace-1",
            "api_key": "secret-key",
        }

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("dataruns.connectors.manago_ai.client._resolve_owner")
    @patch("tenants.manago.verify_credentials")
    def test_scenario_1_connect_manago_bootstrap_succeeds(
        self,
        mock_verify,
        mock_resolve_owner,
        mock_run_import,
        mock_send_email,
    ):
        mock_verify.return_value = ManagoVerifyResult(
            valid=True, message="Credentials verified"
        )
        mock_resolve_owner.return_value = "owner-1"

        request = self.factory.post(
            "/api/v1/connectors/",
            {
                "name": "manago_ai",
                "type": "cdp",
                "config": self._manago_config(),
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ConnectorListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["bootstrap"]["task_queued"])
        self.assertEqual(response.data["bootstrap"]["days"], 30)

        connector = Connector.objects.get(company=self.company, name="manago_ai")
        data_run = DataRun.objects.get(pk=response.data["bootstrap"]["data_run_id"])
        self.assertEqual(data_run.metadata.get("kind"), CONNECTOR_BOOTSTRAP_KIND)
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)
        self.assertIsNotNone(data_run.started_at)
        self.assertIsNotNone(data_run.finished_at)

        health_report = data_run.metadata["health_report"]
        assert_health_report_shape(health_report)
        self.assertEqual(health_report["platform"], "manago_ai")
        self.assertIn(connector.status, {"connected", "degraded"})
        if connector.status == "connected":
            self.assertEqual(health_report["summary_status"], "ok")
        else:
            self.assertEqual(health_report["summary_status"], "degraded")
        assert_connector_status_matches_summary(
            connector_status=connector.status,
            summary_status=health_report["summary_status"],
        )

        self.assertEqual(mock_send_email.call_count, 2)
        recipients = [call.kwargs["to"] for call in mock_send_email.call_args_list]
        self.assertEqual(recipients, [self.admin.email, self.admin.email])
        subjects = [call.kwargs["subject"] for call in mock_send_email.call_args_list]
        self.assertTrue(any("connected" in s.lower() for s in subjects))
        self.assertTrue(any("import finished" in s.lower() for s in subjects))
        self.assertTrue(Contact.objects.filter(company=self.company).exists())
        self.assertTrue(Order.objects.filter(company=self.company).exists())

        mock_run_import.assert_called_once()
        _, import_kwargs = mock_run_import.call_args
        self.assertEqual(import_kwargs["days"], 30)
        self.assertEqual(import_kwargs["platform"], "manago_ai")

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("tenants.shopify.fetch_shop")
    @patch("tenants.shopify.exchange_code_for_token")
    def test_scenario_2_connect_shopify_oauth_bootstrap_succeeds(
        self,
        mock_exchange,
        mock_fetch_shop,
        mock_run_import,
        mock_send_email,
    ):
        shop = "acme.myshopify.com"
        mock_exchange.return_value = ShopifyTokenBundle(
            access_token="shpat_secret_token",
            scope="read_customers,read_orders,read_products",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_secret",
            refresh_token_expires_at="2026-10-27T12:00:00+00:00",
        )
        mock_fetch_shop.return_value = {"id": 42, "name": "Acme Store"}

        from django.core import signing

        state = signing.dumps(
            {
                "user_id": str(self.admin.id),
                "company_id": str(self.company.id),
                "shop": shop,
                "return_to": "",
            },
            salt=SHOPIFY_STATE_SALT,
        )
        params = _sign_params(
            {
                "code": "grant-code",
                "shop": shop,
                "state": state,
                "timestamp": "1700000000",
            },
            "test-client-secret",
        )
        response = ShopifyOAuthCallbackView.as_view()(
            self.factory.get("/api/v1/connectors/shopify/callback/", params)
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("shopify=connected", response.url)
        self.assertIn("bootstrap=queued", response.url)
        self.assertIn("data_run_id=", response.url)

        connector = Connector.objects.get(company=self.company, name="shopify")
        self.assertEqual(
            decrypt_api_key(connector.config["access_token"]),
            "shpat_secret_token",
        )
        self.assertEqual(
            decrypt_api_key(connector.config["refresh_token"]),
            "shprt_secret",
        )
        self.assertEqual(connector.config["token_mode"], TOKEN_MODE_EXPIRING)
        snapshot = ConnectorSnapshot.objects.get(connector=connector)
        self.assertNotIn("access_token", snapshot.snapshot_data)
        self.assertNotIn("refresh_token", snapshot.snapshot_data)
        data_run = DataRun.objects.filter(
            metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
            metadata__company_id=str(self.company.id),
        ).latest("created_at")
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)
        assert_health_report_shape(data_run.metadata["health_report"])
        self.assertIn(connector.status, {"connected", "degraded"})
        self.assertEqual(mock_send_email.call_count, 2)
        subjects = [call.kwargs["subject"] for call in mock_send_email.call_args_list]
        self.assertTrue(any("connected" in s.lower() for s in subjects))
        self.assertTrue(any("import finished" in s.lower() for s in subjects))
        self.assertTrue(Contact.objects.filter(company=self.company).exists())
        self.assertTrue(Order.objects.filter(company=self.company).exists())

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import")
    @patch("dataruns.connectors.manago_ai.client._resolve_owner")
    @patch("tenants.manago.verify_credentials")
    def test_scenario_3_invalid_manago_credentials_fail_bootstrap(
        self,
        mock_verify,
        mock_resolve_owner,
        mock_run_import,
        mock_send_email,
    ):
        mock_verify.return_value = ManagoVerifyResult(
            valid=False, message="Invalid API credentials"
        )
        mock_resolve_owner.return_value = "owner-1"

        request = self.factory.post(
            "/api/v1/connectors/",
            {
                "name": "manago_ai",
                "type": "cdp",
                "config": self._manago_config(),
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ConnectorListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        connector = Connector.objects.get(company=self.company, name="manago_ai")
        data_run = DataRun.objects.get(pk=response.data["bootstrap"]["data_run_id"])

        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        self.assertEqual(connector.status, "error")
        mock_run_import.assert_not_called()

        health_report = data_run.metadata["health_report"]
        preflight_issues = health_report["preflight"]["issues"]
        self.assertTrue(
            any(issue["code"] == "AUTH_FAILED" for issue in preflight_issues)
        )
        auth_issue = next(
            issue for issue in preflight_issues if issue["code"] == "AUTH_FAILED"
        )
        self.assertEqual(auth_issue.get("rc_hint"), "Reconnect the connector.")
        self.assertEqual(health_report["summary_status"], "error")
        self.assertTrue(health_report["blocking"])
        assert_connector_status_matches_summary(
            connector_status=connector.status,
            summary_status=health_report["summary_status"],
        )

        self.assertEqual(mock_send_email.call_count, 2)
        subjects = [call.kwargs["subject"].lower() for call in mock_send_email.call_args_list]
        self.assertTrue(any("connected" in s for s in subjects))
        failure_call = next(
            call
            for call in mock_send_email.call_args_list
            if "didn’t finish" in call.kwargs["subject"].lower()
            or "didn't finish" in call.kwargs["subject"].lower()
        )
        self.assertNotIn("AUTH_FAILED", failure_call.kwargs["text"])
        self.assertIn(
            "reconnect",
            failure_call.kwargs["text"].lower(),
        )
    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import")
    @patch("tenants.shopify.fetch_shop")
    def test_scenario_4_missing_shopify_required_scope_blocks_bootstrap(
        self,
        mock_fetch_shop,
        mock_run_import,
        mock_send_email,
    ):
        mock_fetch_shop.return_value = {"id": 42, "name": "Acme Store"}
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": "read_products",
            }
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )

        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ShopifyFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        connector.refresh_from_db()
        self.assertEqual(connector.status, "error")
        mock_run_import.assert_not_called()

        health_report = data_run.metadata["health_report"]
        assert_health_report_shape(health_report)
        scope_issues = [
            issue
            for issue in health_report["preflight"]["issues"]
            if issue["code"] == "SCOPES_MISSING" and issue["severity"] == "error"
        ]
        self.assertTrue(scope_issues)
        self.assertEqual(scope_issues[0].get("rc_hint"), "Grant required scopes.")
        assert_connector_status_matches_summary(
            connector_status=connector.status,
            summary_status=health_report["summary_status"],
        )
        self.assertEqual(mock_send_email.call_count, 1)

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("tenants.shopify.fetch_shop")
    def test_shopify_write_admin_scopes_satisfy_required_preflight(
        self,
        mock_fetch_shop,
        mock_run_import,
        mock_send_email,
    ):
        mock_fetch_shop.return_value = {"id": 42, "name": "Acme Store"}
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": (
                    "write_customers,write_orders,customer_write_orders,"
                    "customer_write_customers"
                ),
            }
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com"},
        )

        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ShopifyFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)
        health_report = data_run.metadata["health_report"]
        scope_errors = [
            issue
            for issue in health_report["preflight"]["issues"]
            if issue["code"] == "SCOPES_MISSING" and issue["severity"] == "error"
        ]
        self.assertEqual(scope_errors, [])
        mock_run_import.assert_called_once()

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_scenario_5_duplicate_bootstrap_reuses_active_data_run(
        self,
        mock_bootstrap_task,
    ):
        mock_bootstrap_task.delay = MagicMock()
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders",
            }
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )

        first = enqueue_connector_bootstrap(company=self.company, connector=connector)
        second = enqueue_connector_bootstrap(company=self.company, connector=connector)

        self.assertEqual(
            DataRun.objects.filter(
                name="connector-bootstrap:shopify",
                metadata__kind=CONNECTOR_BOOTSTRAP_KIND,
                metadata__company_id=str(self.company.id),
            ).count(),
            1,
        )
        self.assertEqual(second.data_run.id, first.data_run.id)
        self.assertTrue(first.task_queued)
        self.assertFalse(second.task_queued)
        mock_bootstrap_task.delay.assert_called_once_with(first.data_run.id)

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_reconnect_supersedes_active_bootstrap_and_enqueues_fresh_run(
        self,
        mock_bootstrap_task,
    ):
        mock_bootstrap_task.delay = MagicMock()
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders",
            }
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )

        first = enqueue_connector_bootstrap(company=self.company, connector=connector)
        reconnect = enqueue_connector_bootstrap(
            company=self.company,
            connector=connector,
            supersede_existing=True,
        )

        first.data_run.refresh_from_db()
        self.assertEqual(first.data_run.status, DataRun.Status.FAILED)
        self.assertTrue(first.data_run.metadata.get("superseded"))
        self.assertNotEqual(reconnect.data_run.id, first.data_run.id)
        self.assertEqual(reconnect.data_run.status, DataRun.Status.PENDING)
        self.assertTrue(reconnect.task_queued)
        self.assertEqual(mock_bootstrap_task.delay.call_count, 2)
        mock_bootstrap_task.delay.assert_called_with(reconnect.data_run.id)

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_scenario_6_manual_fetch_empty_body_defaults_days_and_returns_202(
        self,
        mock_bootstrap_task,
    ):
        mock_bootstrap_task.delay = MagicMock()
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders",
            }
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )

        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ShopifyFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["days"], 30)
        self.assertEqual(response.data["status"], DataRun.Status.PENDING)
        self.assertEqual(response.data["detail"], "Bootstrap fetch queued.")
        mock_bootstrap_task.delay.assert_called_once()

    @patch("dataruns.connectors.base.bootstrap_connector_fetch")
    def test_scenario_6_manago_manual_fetch_empty_body_defaults_days_and_returns_202(
        self,
        mock_bootstrap_task,
    ):
        mock_bootstrap_task.delay = MagicMock()
        config = encrypt_config(
            {
                "base_url": "https://app2.manago.ai",
                "workspace_id": "workspace-1",
                "api_key": "secret-key",
            }
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            config=config,
            status="connected",
        )

        request = self.factory.post(
            "/api/v1/connectors/manago_ai/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ManagoFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["days"], 30)
        self.assertEqual(response.data["platform"], "manago_ai")
        self.assertEqual(response.data["status"], DataRun.Status.PENDING)
        self.assertEqual(response.data["detail"], "Bootstrap fetch queued.")
        mock_bootstrap_task.delay.assert_called_once()

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("tenants.shopify.fetch_shop")
    def test_scenario_7_get_bootstrap_status_returns_populated_health_report(
        self,
        mock_fetch_shop,
        mock_run_import,
        mock_send_email,
    ):
        mock_fetch_shop.return_value = {"id": 42, "name": "Acme Store"}
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_test_token",
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders",
            }
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )

        fetch_request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(fetch_request, user=self.admin)
        fetch_response = ShopifyFetchView.as_view()(fetch_request)
        self.assertEqual(fetch_response.status_code, 202)

        data_run = DataRun.objects.get(pk=fetch_response.data["data_run_id"])
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)

        status_request = self.factory.get(
            f"/api/v1/connectors/{connector.id}/bootstrap/"
        )
        force_authenticate(status_request, user=self.admin)
        status_response = ConnectorBootstrapStatusView.as_view()(
            status_request, pk=connector.id
        )

        self.assertEqual(status_response.status_code, 200)
        expected_fields = (
            "connector_id",
            "connector_name",
            "connector_status",
            "data_run_id",
            "data_run_status",
            "run_id",
            "days",
            "window_start",
            "window_end",
            "health_report",
            "started_at",
            "finished_at",
        )
        for field in expected_fields:
            self.assertIn(field, status_response.data, msg=f"missing {field}")

        health_report = status_response.data["health_report"]
        assert_health_report_shape(health_report)
        self.assertTrue(health_report["fetch"]["ok"])
        self.assertGreaterEqual(health_report["fetch"]["contacts_upserted"], 0)
        self.assertGreaterEqual(health_report["fetch"]["orders_upserted"], 0)
        self.assertGreater(health_report["fetch"]["duration_ms"], 0)
        self.assertIn(health_report["summary_status"], {"ok", "degraded"})
        assert_connector_status_matches_summary(
            connector_status=status_response.data["connector_status"],
            summary_status=health_report["summary_status"],
        )
        self.assertIsNotNone(status_response.data["window_start"])
        self.assertIsNotNone(status_response.data["window_end"])
        self.assertEqual(status_response.data["data_run_status"], "succeeded")
        self.assertIsNotNone(status_response.data["run_id"])

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("dataruns.connectors.manago_ai.client._resolve_owner")
    @patch("tenants.manago.verify_credentials")
    def test_success_email_only_goes_to_verified_active_admins(
        self,
        mock_verify,
        mock_resolve_owner,
        mock_run_import,
        mock_send_email,
    ):
        mock_verify.return_value = ManagoVerifyResult(valid=True, message="ok")
        mock_resolve_owner.return_value = "owner-1"

        request = self.factory.post(
            "/api/v1/connectors/",
            {
                "name": "manago_ai",
                "type": "cdp",
                "config": self._manago_config(),
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        ConnectorListCreateView.as_view()(request)

        recipients = [call.kwargs["to"] for call in mock_send_email.call_args_list]
        self.assertEqual(recipients, [self.admin.email])
        self.assertNotIn(self.unverified_admin.email, recipients)

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("dataruns.connectors.manago_ai.client._resolve_owner")
    @patch("tenants.manago.verify_credentials")
    def test_connector_status_mapping_ok_and_degraded(
        self,
        mock_verify,
        mock_resolve_owner,
        mock_run_import,
        mock_send_email,
    ):
        mock_verify.return_value = ManagoVerifyResult(valid=True, message="ok")
        mock_resolve_owner.return_value = "owner-1"

        def zero_contacts_import(*, platform, company=None, data_run=None, days=None, user=None, **kwargs):
            result = successful_run_import_side_effect(
                platform=platform,
                company=company,
                data_run=data_run,
                days=days,
                user=user,
                **kwargs,
            )
            data_run.metadata["counts"] = {
                "contacts": 0,
                "orders": 1,
                "contact_metrics": 0,
            }
            data_run.save(update_fields=["metadata", "updated_at"])
            result["counts"] = {"contacts": 0, "orders": 1, "contact_metrics": 0}
            return result

        mock_run_import.side_effect = zero_contacts_import

        request = self.factory.post(
            "/api/v1/connectors/",
            {
                "name": "manago_ai",
                "type": "cdp",
                "config": self._manago_config(),
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ConnectorListCreateView.as_view()(request)

        connector = Connector.objects.get(company=self.company, name="manago_ai")
        data_run = DataRun.objects.get(pk=response.data["bootstrap"]["data_run_id"])
        health_report = data_run.metadata["health_report"]

        self.assertEqual(health_report["summary_status"], "degraded")
        self.assertFalse(health_report["blocking"])
        self.assertEqual(connector.status, "degraded")
        assert_connector_status_matches_summary(
            connector_status=connector.status,
            summary_status=health_report["summary_status"],
        )
        self.assertTrue(
            any(
                issue["code"] == "EMPTY_CONTACTS_WINDOW"
                for issue in health_report["postflight"]["issues"]
            )
        )
        empty_contacts = next(
            issue
            for issue in health_report["postflight"]["issues"]
            if issue["code"] == "EMPTY_CONTACTS_WINDOW"
        )
        self.assertEqual(
            empty_contacts.get("rc_hint"),
            "Verify data exists in the selected window.",
        )

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    @patch("tenants.shopify.fetch_shop")
    def test_shopify_bootstrap_refreshes_expired_access_token(
        self,
        mock_fetch_shop,
        mock_refresh,
        mock_run_import,
        mock_send_email,
    ):
        from datetime import datetime, timezone as dt_timezone

        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        mock_fetch_shop.return_value = {"id": 42, "name": "Acme Store"}
        mock_refresh.return_value = ShopifyTokenBundle(
            access_token="shpat_refreshed",
            scope="read_customers,read_orders,read_products",
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at="2026-07-29T13:00:00+00:00",
            refresh_token="shprt_rotated",
            refresh_token_expires_at="2026-10-27T12:00:00+00:00",
        )
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_expired",
                "refresh_token": "shprt_valid",
                "access_token_expires_at": "2026-07-29T11:00:00+00:00",
                "refresh_token_expires_at": "2026-10-27T12:00:00+00:00",
                "token_mode": TOKEN_MODE_EXPIRING,
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders,read_products",
            }
        )
        connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com", "shop_id": 42},
        )

        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        with patch("django.utils.timezone.now", return_value=now):
            response = ShopifyFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)
        connector.refresh_from_db()
        self.assertEqual(
            decrypt_api_key(connector.config["access_token"]),
            "shpat_refreshed",
        )
        mock_refresh.assert_called_once()
        mock_run_import.assert_called_once()

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import")
    @patch("tenants.shopify.fetch_shop")
    def test_shopify_bootstrap_fails_when_refresh_token_expired(
        self,
        mock_fetch_shop,
        mock_run_import,
        mock_send_email,
    ):
        from datetime import datetime, timezone as dt_timezone

        now = datetime(2026, 7, 29, 12, 0, tzinfo=dt_timezone.utc)
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_expired",
                "refresh_token": "shprt_expired",
                "access_token_expires_at": "2026-07-29T11:00:00+00:00",
                "refresh_token_expires_at": "2026-07-29T11:30:00+00:00",
                "token_mode": TOKEN_MODE_EXPIRING,
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders,read_products",
            }
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )

        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        with patch("django.utils.timezone.now", return_value=now):
            response = ShopifyFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.status, DataRun.Status.FAILED)
        connector = Connector.objects.get(company=self.company, name="shopify")
        self.assertEqual(connector.status, "error")
        mock_run_import.assert_not_called()
        auth_issues = [
            issue
            for issue in data_run.metadata["health_report"]["preflight"]["issues"]
            if issue["code"] == "AUTH_FAILED"
        ]
        self.assertTrue(auth_issues)
        # Bootstrap failure email + dedicated auth-expired email (PRD-CONN-05 locked v1).
        self.assertEqual(mock_send_email.call_count, 2)
        from dataruns.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company, action="connector.auth_expired"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                company=self.company, action="connector.bootstrap_failed"
            ).exists()
        )

    @patch("tenants.emails.send_email")
    @patch("dataruns.tasks.run_import", side_effect=successful_run_import_side_effect)
    @patch("dataruns.connectors.shopify_token.refresh_offline_access_token")
    @patch("tenants.shopify.fetch_shop")
    def test_shopify_bootstrap_legacy_connector_skips_refresh(
        self,
        mock_fetch_shop,
        mock_refresh,
        mock_run_import,
        mock_send_email,
    ):
        mock_fetch_shop.return_value = {"id": 42, "name": "Acme Store"}
        config = encrypt_config(
            {
                "shop_domain": "acme.myshopify.com",
                "access_token": "shpat_legacy",
                "api_version": "2026-01",
                "scopes": "read_customers,read_orders,read_products",
            }
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config=config,
            status="connected",
        )

        request = self.factory.post(
            "/api/v1/connectors/shopify/fetch/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = ShopifyFetchView.as_view()(request)

        self.assertEqual(response.status_code, 202)
        data_run = DataRun.objects.get(pk=response.data["data_run_id"])
        self.assertEqual(data_run.status, DataRun.Status.SUCCEEDED)
        mock_refresh.assert_not_called()
        mock_run_import.assert_called_once()
