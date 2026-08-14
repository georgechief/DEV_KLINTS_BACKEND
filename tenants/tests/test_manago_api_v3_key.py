"""Tests for Manago API v3 key storage (PRD-CONN-06)."""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.connectors.base import decrypt_connector_config
from dataruns.models import AuditLog
from tenants.connector_views import ConnectorListCreateView, ManagoApiV3KeyView
from tenants.crypto import (
    encrypt_config,
    has_api_v3_key_in_config,
    mask_api_key,
    masked_config,
)
from tenants.models import Company, Connector, Tenant, User

SAMPLE_V3_KEY = "SHOPIFY_test_catalog_key_12345"


class ManagoApiV3KeyCryptoTests(TestCase):
    def test_encrypt_and_mask_api_v3_key(self):
        encrypted = encrypt_config({"api_v3_key": SAMPLE_V3_KEY})
        self.assertNotEqual(encrypted["api_v3_key"], SAMPLE_V3_KEY)
        self.assertEqual(
            masked_config(encrypted)["api_v3_key"],
            mask_api_key(SAMPLE_V3_KEY),
        )

    def test_decrypt_connector_config_decrypts_api_v3_key(self):
        encrypted = encrypt_config(
            {
                "base_url": "https://app.manago.ai",
                "workspace_id": "client-1",
                "api_key": "secret-v2",
                "api_v3_key": SAMPLE_V3_KEY,
            }
        )
        decrypted = decrypt_connector_config(encrypted)
        self.assertEqual(decrypted["api_v3_key"], SAMPLE_V3_KEY)
        self.assertEqual(decrypted["api_key"], "secret-v2")

    def test_has_api_v3_key_in_config_false_when_missing(self):
        self.assertFalse(has_api_v3_key_in_config({}))
        self.assertFalse(has_api_v3_key_in_config({"api_key": "x"}))


class ManagoApiV3KeyViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.put_view = ManagoApiV3KeyView.as_view()
        self.delete_view = ManagoApiV3KeyView.as_view()
        self.list_view = ConnectorListCreateView.as_view()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.other_tenant = Tenant.objects.create(name="Beta", slug="beta")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )
        self.other_company = Company.objects.create(
            tenant=self.other_tenant,
            name="Beta",
            domain="beta.com",
        )
        self.admin = self._create_user("admin@acme.com", User.Role.ADMIN)
        self.analyst = self._create_user("analyst@acme.com", User.Role.ANALYST)
        self.viewer = self._create_user("viewer@acme.com", User.Role.VIEWER)
        self.other_admin = self._create_user(
            "admin@beta.com",
            User.Role.ADMIN,
            tenant=self.other_tenant,
        )
        self.manago = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config=encrypt_config(
                {
                    "base_url": "https://app.manago.ai",
                    "workspace_id": "client-1",
                    "api_key": "secret-v2",
                }
            ),
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

    def _put(self, user, payload):
        request = self.factory.put(
            "/api/v1/connectors/manago_ai/api-v3-key/",
            payload,
            format="json",
        )
        force_authenticate(request, user=user)
        return self.put_view(request)

    def _delete(self, user):
        request = self.factory.delete("/api/v1/connectors/manago_ai/api-v3-key/")
        force_authenticate(request, user=user)
        return self.delete_view(request)

    def test_put_rejects_short_key(self):
        response = self._put(self.admin, {"api_v3_key": "short"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("api_v3_key", response.data)
        self.assertFalse(has_api_v3_key_in_config(self.manago.config))

    def test_delete_audits_when_key_was_present(self):
        self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        response = self._delete(self.admin)
        self.assertEqual(response.status_code, 200)
        audit = AuditLog.objects.filter(
            company=self.company,
            action="connector.manago_api_v3_key_removed",
        ).first()
        self.assertIsNotNone(audit)
        self.assertNotIn(SAMPLE_V3_KEY, str(audit.metadata))

    def test_put_saves_encrypted_key_and_returns_masked_response(self):
        response = self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "platform": "manago_ai",
                "has_api_v3_key": True,
                "api_v3_key_masked": mask_api_key(SAMPLE_V3_KEY),
            },
        )

        self.manago.refresh_from_db()
        stored = decrypt_connector_config(self.manago.config)
        self.assertEqual(stored["api_v3_key"], SAMPLE_V3_KEY)
        self.assertEqual(stored["api_key"], "secret-v2")
        self.assertNotIn(SAMPLE_V3_KEY, str(self.manago.config))

        audit = AuditLog.objects.filter(
            company=self.company,
            action="connector.manago_api_v3_key_set",
        ).first()
        self.assertIsNotNone(audit)
        self.assertNotIn(SAMPLE_V3_KEY, audit.summary)
        self.assertNotIn(SAMPLE_V3_KEY, str(audit.metadata))

    def test_put_rejects_empty_key(self):
        response = self._put(self.admin, {"api_v3_key": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("api_v3_key", response.data)

    def test_put_trims_key(self):
        response = self._put(self.admin, {"api_v3_key": f"  {SAMPLE_V3_KEY}  "})
        self.assertEqual(response.status_code, 200)
        self.manago.refresh_from_db()
        self.assertEqual(
            decrypt_connector_config(self.manago.config)["api_v3_key"],
            SAMPLE_V3_KEY,
        )

    def test_put_replace_overwrites_previous_key(self):
        self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        replacement = "SHOPIFY_replaced_key_99999"
        response = self._put(self.analyst, {"api_v3_key": replacement})
        self.assertEqual(response.status_code, 200)
        self.manago.refresh_from_db()
        self.assertEqual(
            decrypt_connector_config(self.manago.config)["api_v3_key"],
            replacement,
        )

    def test_put_allowed_when_connector_status_error(self):
        self.manago.status = "error"
        self.manago.save(update_fields=["status", "updated_at"])
        response = self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["has_api_v3_key"])

    def test_put_not_found_when_manago_missing(self):
        self.manago.delete()
        response = self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        self.assertEqual(response.status_code, 404)

    def test_viewer_forbidden_on_put(self):
        response = self._put(self.viewer, {"api_v3_key": SAMPLE_V3_KEY})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(has_api_v3_key_in_config(self.manago.config))

    def test_delete_clears_key(self):
        self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        response = self._delete(self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "platform": "manago_ai",
                "has_api_v3_key": False,
            },
        )
        self.manago.refresh_from_db()
        self.assertFalse(has_api_v3_key_in_config(self.manago.config))
        self.assertNotIn("api_v3_key", decrypt_connector_config(self.manago.config))

    def test_viewer_forbidden_on_delete(self):
        self._put(self.admin, {"api_v3_key": SAMPLE_V3_KEY})
        self.manago.refresh_from_db()
        response = self._delete(self.viewer)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(has_api_v3_key_in_config(self.manago.config))

    def test_company_isolation(self):
        Connector.objects.create(
            company=self.other_company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config=encrypt_config({"base_url": "https://app.manago.ai"}),
        )
        response = self._put(self.other_admin, {"api_v3_key": SAMPLE_V3_KEY})
        self.assertEqual(response.status_code, 200)
        self.manago.refresh_from_db()
        self.assertFalse(has_api_v3_key_in_config(self.manago.config))


class ManagoApiV3KeyListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ConnectorListCreateView.as_view()
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

    def test_list_includes_has_api_v3_key_for_manago(self):
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config=encrypt_config(
                {
                    "base_url": "https://app.manago.ai",
                    "workspace_id": "client-1",
                    "api_key": "secret-v2",
                    "api_v3_key": SAMPLE_V3_KEY,
                }
            ),
        )
        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        manago = response.data["results"][0]
        self.assertTrue(manago["has_api_v3_key"])
        self.assertEqual(manago["config"]["api_v3_key"], mask_api_key(SAMPLE_V3_KEY))
        self.assertNotIn(SAMPLE_V3_KEY, str(response.data))

    def test_list_omits_has_api_v3_key_for_shopify(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config={"shop_domain": "acme.myshopify.com"},
        )
        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        shopify = response.data["results"][0]
        self.assertNotIn("has_api_v3_key", shopify)

    def test_list_has_api_v3_key_false_when_missing(self):
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config=encrypt_config(
                {
                    "base_url": "https://app.manago.ai",
                    "workspace_id": "client-1",
                    "api_key": "secret-v2",
                }
            ),
        )
        request = self.factory.get("/api/v1/connectors/")
        force_authenticate(request, user=self.admin)
        response = self.view(request)

        self.assertFalse(response.data["results"][0]["has_api_v3_key"])
