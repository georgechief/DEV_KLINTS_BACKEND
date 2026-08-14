"""Shopify inventory_levels fetch (Excel BR-02)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.connectors.shopify.client import FetchWindow, ShopifyClient


class ShopifyInventoryLevelsFetchTests(SimpleTestCase):
    def test_fetch_includes_inventory_levels(self):
        window = FetchWindow(
            window_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        client = ShopifyClient(
            {
                "shop_domain": "example.myshopify.com",
                "access_token": "shpat_test",
                "api_version": "2024-10",
            }
        )

        def fake_paginated(**kwargs):
            resource = kwargs["resource"]
            budget = kwargs.get("rate_budget") or {"calls": 1}
            if resource == "customers":
                return ([], budget)
            if resource == "orders":
                return ([], budget)
            if resource == "products":
                return ([], budget)
            if resource == "checkouts":
                return ([], budget)
            if resource == "locations":
                return ([{"id": 11}, {"id": 12}], budget)
            if resource == "inventory_levels":
                return (
                    [
                        {
                            "inventory_item_id": 1,
                            "location_id": 11,
                            "updated_at": "2026-08-03T01:00:00Z",
                        }
                    ],
                    budget,
                )
            return ([], budget)

        with patch(
            "dataruns.connectors.shopify.client._fetch_paginated_resource",
            side_effect=fake_paginated,
        ):
            raw = client.fetch(window)

        self.assertEqual(len(raw["inventory_levels"]), 1)
        self.assertIsNone(raw.get("inventory_levels_fetch_error"))
        self.assertEqual(client.last_rate_budget.get("inventory_levels_fetched"), 1)

    def test_inventory_levels_soft_fail(self):
        from dataruns.connectors.shopify.client import ShopifyClientError

        window = FetchWindow(
            window_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        client = ShopifyClient(
            {
                "shop_domain": "example.myshopify.com",
                "access_token": "shpat_test",
            }
        )

        def fake_paginated(**kwargs):
            resource = kwargs["resource"]
            budget = kwargs.get("rate_budget") or {}
            if resource == "locations":
                raise ShopifyClientError("read_inventory required")
            return ([], budget)

        with patch(
            "dataruns.connectors.shopify.client._fetch_paginated_resource",
            side_effect=fake_paginated,
        ):
            raw = client.fetch(window)

        self.assertEqual(raw["inventory_levels"], [])
        self.assertIn("read_inventory", raw["inventory_levels_fetch_error"] or "")
