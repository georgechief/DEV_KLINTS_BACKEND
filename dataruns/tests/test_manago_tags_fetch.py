"""Manago /api/contact/tags fetch for Excel SP-08."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.connectors.manago_ai.client import FetchWindow, ManagoClient


class ManagoTagsFetchTests(SimpleTestCase):
    def test_fetch_includes_tags_catalog(self):
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
                "dataruns.connectors.manago_ai.client._fetch_email_global_stats",
                return_value=({}, None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._post_manago",
                return_value={
                    "success": True,
                    "tags": [
                        {"tag": "VIP", "numberOfTagged": 12},
                        {"tag": "empty", "numberOfTagged": 0},
                    ],
                },
            ) as post,
        ):
            raw = client.fetch(window)

        self.assertEqual(
            raw["tags"],
            [
                {"tag": "VIP", "numberOfTagged": 12},
                {"tag": "empty", "numberOfTagged": 0},
            ],
        )
        self.assertIsNone(raw.get("tags_fetch_note"))
        post.assert_called()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["path"], "api/contact/tags")
        self.assertEqual(kwargs["payload"]["owner"], "owner@example.com")
        self.assertIs(kwargs["payload"]["showSystemTags"], False)

    def test_tags_soft_fail(self):
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
                "dataruns.connectors.manago_ai.client._fetch_email_global_stats",
                return_value=({}, None),
            ),
            patch(
                "dataruns.connectors.manago_ai.client._post_manago",
                side_effect=ManagoClientError("boom"),
            ),
        ):
            raw = client.fetch(window)

        self.assertEqual(raw["tags"], [])
        self.assertIn("contact_tags_failed", raw["tags_fetch_note"] or "")
