"""Tests for Manago primary-owner selection (FD-06 onboarding API)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.connectors.base import decrypt_connector_config
from dataruns.dcs.topology import load_manago_topology
from dataruns.models import AuditLog
from tenants.connector_views import ManagoOwnersView
from tenants.crypto import encrypt_config
from tenants.manago_topology_service import (
    apply_primary_owner,
    preferred_owner_from_config,
    topology_status,
)
from tenants.models import Company, Connector, Tenant, User


class ManagoTopologyServiceTests(SimpleTestCase):
    def test_apply_primary_marks_others_out_of_scope(self):
        config = apply_primary_owner(
            config={"workspace_id": "c1", "api_key": "x"},
            primary_owner="primary@example.com",
            all_owners=["secondary@example.com", "primary@example.com"],
            shop_domain="shop.myshopify.com",
        )
        self.assertEqual(config["owner"], "primary@example.com")
        accounts = config["topology"]["accounts"]
        by_owner = {a["owner"].lower(): a for a in accounts}
        self.assertTrue(by_owner["primary@example.com"]["in_scope"])
        self.assertFalse(by_owner["secondary@example.com"]["in_scope"])
        self.assertEqual(
            by_owner["primary@example.com"]["shop_domain"], "shop.myshopify.com"
        )

    def test_needs_primary_selection_when_multi_and_unset(self):
        status = topology_status(
            config={},
            owners=["a@x.com", "b@x.com"],
        )
        self.assertTrue(status["needs_primary_selection"])
        self.assertIsNone(status["primary_owner"])

    def test_needs_primary_selection_false_when_set(self):
        config = apply_primary_owner(
            config={},
            primary_owner="b@x.com",
            all_owners=["a@x.com", "b@x.com"],
        )
        status = topology_status(config=config, owners=["a@x.com", "b@x.com"])
        self.assertFalse(status["needs_primary_selection"])
        self.assertEqual(status["primary_owner"], "b@x.com")
        self.assertTrue(status["topology_configured"])


class ManagoOwnersViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ManagoOwnersView.as_view()
        self.tenant = Tenant.objects.create(name="Acme", slug="acme-owners")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme-owners.com",
        )
        self.admin = User.objects.create_user(
            email="admin@acme-owners.com",
            password="TestPass123!",
            name="admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        self.viewer = User.objects.create_user(
            email="viewer@acme-owners.com",
            password="TestPass123!",
            name="viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
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
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config(
                {
                    "shop_domain": "acme.myshopify.com",
                    "access_token": "shpat_test",
                }
            ),
        )

    def _get(self, user):
        request = self.factory.get("/api/v1/connectors/manago_ai/owners/")
        force_authenticate(request, user=user)
        return self.view(request)

    def _put(self, user, payload):
        request = self.factory.put(
            "/api/v1/connectors/manago_ai/owners/",
            payload,
            format="json",
        )
        force_authenticate(request, user=user)
        return self.view(request)

    @patch("tenants.connector_views.list_manago_owners")
    def test_get_multi_needs_selection(self, mock_list):
        mock_list.return_value = ["a@x.com", "b@x.com"]
        response = self._get(self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["needs_primary_selection"])
        self.assertEqual(len(response.data["owners"]), 2)

    @patch("tenants.connector_views.list_manago_owners")
    def test_get_single_auto_selects(self, mock_list):
        mock_list.return_value = ["only@x.com"]
        response = self._get(self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["needs_primary_selection"])
        self.assertEqual(response.data["primary_owner"], "only@x.com")
        self.manago.refresh_from_db()
        config = decrypt_connector_config(self.manago.config)
        self.assertEqual(preferred_owner_from_config(config), "only@x.com")
        self.assertTrue(
            AuditLog.objects.filter(
                action="connector.manago_primary_owner_auto_set"
            ).exists()
        )

    @patch("tenants.connector_views.list_manago_owners")
    def test_put_sets_primary(self, mock_list):
        mock_list.return_value = ["a@x.com", "b@x.com"]
        response = self._put(self.admin, {"owner": "b@x.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["primary_owner"], "b@x.com")
        self.assertFalse(response.data["needs_primary_selection"])
        self.manago.refresh_from_db()
        config = decrypt_connector_config(self.manago.config)
        self.assertEqual(config["owner"], "b@x.com")
        in_scope = [
            a for a in config["topology"]["accounts"] if a.get("in_scope")
        ]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["shop_domain"], "acme.myshopify.com")
        self.assertTrue(
            AuditLog.objects.filter(
                action="connector.manago_primary_owner_set"
            ).exists()
        )

        with (
            patch(
                "dataruns.dcs.topology.list_users_by_client",
                return_value={"success": True, "users": ["a@x.com", "b@x.com"]},
            ),
            patch(
                "dataruns.dcs.topology.resolve_manago_credentials",
                return_value=("https://app.manago.ai", "client-1", "secret"),
            ),
        ):
            result = load_manago_topology(config=config)
        self.assertTrue(result.topology_ok)

    @patch("tenants.connector_views.list_manago_owners")
    def test_put_rejects_unknown_owner(self, mock_list):
        mock_list.return_value = ["a@x.com", "b@x.com"]
        response = self._put(self.admin, {"owner": "nope@x.com"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("owner", response.data)

    @patch("tenants.connector_views.list_manago_owners")
    def test_put_forbidden_for_viewer(self, mock_list):
        mock_list.return_value = ["a@x.com", "b@x.com"]
        response = self._put(self.viewer, {"owner": "a@x.com"})
        self.assertEqual(response.status_code, 403)
