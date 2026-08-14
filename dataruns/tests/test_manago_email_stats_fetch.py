"""Manago email globalConversationStatistics fetch (Excel ME-09)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.connectors.manago_ai.client import FetchWindow, ManagoClient


class ManagoEmailStatsFetchTests(SimpleTestCase):
    def test_fetch_includes_email_stats(self):
        window = FetchWindow(
            window_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        client = ManagoClient(
            {
                "workspace_id": "ws-1",
                "api_key": "secret",
                "api_base_url": "https://app.manago.ai/",
            }
        )

        def fake_post(**kwargs):
            path = kwargs["path"]
            if path == "api/contact/tags":
                return {"success": True, "tags": []}
            if path == "api/email/globalConversationStatistics":
                self.assertIn("user", kwargs["payload"])
                self.assertEqual(kwargs["payload"]["user"], "owner@example.com")
                self.assertNotIn("owner", kwargs["payload"])
                return {
                    "sent": 100,
                    "softBounce": 2,
                    "hardBounce": 1,
                    "opened": 40,
                    "clicked": 10,
                    "openedUnique": 30,
                    "clickedUnique": 8,
                    "resigned": 0,
                }
            raise AssertionError(f"unexpected path {path}")

        with (
            patch(
                "dataruns.connectors.manago_ai.client._resolve_owner",
                return_value="owner@example.com",
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_contacts",
                return_value=[],
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_product_catalogs_v3",
                return_value=([], None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_catalog_products",
                return_value=([], None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_workflows",
                return_value=([], None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_workflow_stats",
                return_value=[],
            ),
            patch(
                "dataruns.connectors.manago_ai.client._post_manago",
                side_effect=fake_post,
            ),
        ):
            raw = client.fetch(window)

        stats = raw["email_stats"]
        self.assertEqual(stats["sent"], 100)
        self.assertEqual(stats["bounce_total"], 3)
        self.assertAlmostEqual(stats["bounce_rate"], 0.03)
        self.assertAlmostEqual(stats["hard_bounce_rate"], 0.01)
        self.assertIsNone(raw.get("email_stats_fetch_note"))

    def test_email_stats_soft_fail(self):
        from dataruns.connectors.manago_ai.client import ManagoClientError

        window = FetchWindow(
            window_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        client = ManagoClient(
            {
                "workspace_id": "ws-1",
                "api_key": "secret",
                "api_base_url": "https://app.manago.ai/",
            }
        )

        def fake_post(**kwargs):
            if kwargs["path"] == "api/contact/tags":
                return {"success": True, "tags": []}
            raise ManagoClientError("stats unavailable")

        with (
            patch(
                "dataruns.connectors.manago_ai.client._resolve_owner",
                return_value="owner@example.com",
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_contacts",
                return_value=[],
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_product_catalogs_v3",
                return_value=([], None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_catalog_products",
                return_value=([], None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_workflows",
                return_value=([], None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._fetch_workflow_stats",
                return_value=[],
            ),
            patch(
                "dataruns.connectors.manago_ai.client._post_manago",
                side_effect=fake_post,
            ),
        ):
            raw = client.fetch(window)

        self.assertEqual(raw["email_stats"], {})
        self.assertIn("email_global_stats_failed", raw["email_stats_fetch_note"] or "")
