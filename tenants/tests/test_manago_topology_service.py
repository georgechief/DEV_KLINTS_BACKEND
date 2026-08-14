"""Tests for Manago primary-owner auto-resolution (FD-06 / DCS pipeline)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from dataruns.connectors.base import decrypt_connector_config
from tenants.crypto import encrypt_config
from tenants.manago_topology_service import (
    ensure_manago_primary_owner,
    infer_primary_owner_from_shop_domain,
    preferred_owner_from_config,
)
from tenants.models import Company, Connector, Tenant


class InferPrimaryOwnerTests(TestCase):
    def test_matches_shop_slug_token_uniquely(self):
        owners = ["noreplyklints@gmail.com", "george.chief@icloud.com"]
        inferred = infer_primary_owner_from_shop_domain(
            owners,
            "klints-dev.myshopify.com",
        )
        self.assertEqual(inferred, "noreplyklints@gmail.com")

    def test_returns_none_when_ambiguous(self):
        owners = ["alpha@example.com", "beta@example.com"]
        inferred = infer_primary_owner_from_shop_domain(
            owners,
            "acme.myshopify.com",
        )
        self.assertIsNone(inferred)

    def test_single_owner_not_inferred(self):
        self.assertIsNone(
            infer_primary_owner_from_shop_domain(
                ["only@example.com"],
                "klints.myshopify.com",
            )
        )


class EnsureManagoPrimaryOwnerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.example",
        )
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config({"shop_domain": "klints-dev.myshopify.com"}),
        )
        self.manago = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config=encrypt_config(
                {
                    "base_url": "https://app2.manago.ai",
                    "workspace_id": "workspace-1",
                    "api_key": "secret-key",
                }
            ),
        )

    @patch("dataruns.audit.append_audit_event")
    @patch("tenants.manago_topology_service.list_manago_owners")
    def test_infers_primary_for_multi_owner_shop_match(
        self,
        mock_list,
        mock_audit,
    ):
        mock_list.return_value = [
            "noreplyklints@gmail.com",
            "george.chief@icloud.com",
        ]

        result = ensure_manago_primary_owner(self.company)

        self.assertTrue(result.applied)
        self.assertEqual(result.reason, "inferred_from_shop")
        self.assertEqual(result.primary_owner, "noreplyklints@gmail.com")

        self.manago.refresh_from_db()
        config = decrypt_connector_config(self.manago.config)
        self.assertEqual(preferred_owner_from_config(config), "noreplyklints@gmail.com")
        in_scope = [
            row
            for row in config["topology"]["accounts"]
            if row.get("in_scope")
        ]
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(in_scope[0]["owner"], "noreplyklints@gmail.com")
        mock_audit.assert_called_once()

    @patch("tenants.manago_topology_service.list_manago_owners")
    def test_skips_when_manual_selection_required(self, mock_list):
        mock_list.return_value = ["alpha@example.com", "beta@example.com"]

        result = ensure_manago_primary_owner(self.company)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "needs_manual_selection")
        self.manago.refresh_from_db()
        config = decrypt_connector_config(self.manago.config)
        self.assertIsNone(preferred_owner_from_config(config))
