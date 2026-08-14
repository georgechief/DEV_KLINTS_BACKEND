"""Shopify client abandoned-checkouts fetch (Excel LE-08)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.connectors.shopify.client import FetchWindow, ShopifyClient


class ShopifyCheckoutsFetchTests(SimpleTestCase):
    def test_fetch_includes_checkouts_open_and_closed(self):
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
            params = kwargs.get("query_params") or {}
            budget = kwargs.get("rate_budget") or {"calls": 1}
            if resource == "customers":
                return ([{"id": 1, "email": "a@x.com"}], budget)
            if resource == "orders":
                return ([{"id": 10, "total_price": "1.00"}], budget)
            if resource == "products":
                return ([], budget)
            if resource == "checkouts":
                status = params.get("status")
                if status == "open":
                    return (
                        [{"id": 100, "email": "a@x.com", "completed_at": None}],
                        budget,
                    )
                if status == "closed":
                    return (
                        [
                            {
                                "id": 101,
                                "email": "b@x.com",
                                "completed_at": "2026-07-15T12:00:00Z",
                            }
                        ],
                        budget,
                    )
            if "metafields" in resource:
                return ([], budget)
            return ([], budget)

        with patch(
            "dataruns.connectors.shopify.client._fetch_paginated_resource",
            side_effect=fake_paginated,
        ):
            raw = client.fetch(window)

        self.assertEqual(len(raw["checkouts"]), 2)
        self.assertEqual(raw["abandoned_checkouts"], raw["checkouts"])
        self.assertIsNone(raw.get("checkouts_fetch_error"))
        self.assertEqual(client.last_rate_budget.get("checkouts_fetched"), 2)

    def test_checkouts_soft_fail(self):
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
            if resource == "checkouts":
                raise ShopifyClientError("Protected customer data required")
            if resource in {"customers", "orders", "products"}:
                return ([], budget)
            return ([], budget)

        with patch(
            "dataruns.connectors.shopify.client._fetch_paginated_resource",
            side_effect=fake_paginated,
        ):
            raw = client.fetch(window)

        self.assertEqual(raw["checkouts"], [])
        self.assertIn("Protected customer data", raw["checkouts_fetch_error"] or "")
