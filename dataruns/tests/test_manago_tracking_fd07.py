"""Unit tests for Manago recentActivity → FD-07 tracking signals."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from dataruns.dcs.manago_tracking import (
    derive_tracking_from_recent_activity,
    load_manago_tracking_evidence,
)
from dataruns.dcs.executors.foundation import (
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_fd_07,
)
from tenants.manago_fetch import ManagoFetchError


class DeriveTrackingTests(unittest.TestCase):
    def test_visits_and_monitored_pass_signals(self):
        response = {
            "success": True,
            "recentActivities": {
                "from": 1,
                "to": 2,
                "monitoredContacts": 12,
                "totalContacts": 100,
                "customers": [
                    {
                        "contactId": "abc-123",
                        "email": "a@example.com",
                        "url": "https://shop.example.com/p/1",
                        "time": 1,
                    }
                ],
                "partners": [],
                "prospects": [],
                "anonymous": [],
            },
        }
        evidence = derive_tracking_from_recent_activity(response)
        self.assertTrue(evidence.tracking_measurable)
        self.assertTrue(evidence.visit_events_recent)
        self.assertTrue(evidence.smclient_cookie_seen)
        self.assertTrue(evidence.tracking_active)
        self.assertEqual(evidence.detail["visit_count"], 1)
        self.assertEqual(evidence.detail["monitored_contacts"], 12)
        self.assertIn("shop.example.com", evidence.storefront_domains or [])

    def test_zero_activity_is_explicit_false(self):
        response = {
            "success": True,
            "recentActivities": {
                "monitoredContacts": 0,
                "totalContacts": 50,
                "customers": [],
                "partners": [],
                "prospects": [],
                "anonymous": [],
                "visitStats": [
                    {
                        "partnersVisits": 0,
                        "prospectsVisits": 0,
                        "customersVisits": 0,
                        "otherVisits": 0,
                    }
                ],
            },
        }
        evidence = derive_tracking_from_recent_activity(response)
        self.assertTrue(evidence.tracking_measurable)
        self.assertFalse(evidence.visit_events_recent)
        self.assertFalse(evidence.smclient_cookie_seen)
        self.assertFalse(evidence.tracking_active)

    def test_visit_stats_only_counts_as_visits(self):
        response = {
            "success": True,
            "recentActivities": {
                "monitoredContacts": 0,
                "customers": [],
                "visitStats": [{"customersVisits": 3, "otherVisits": 1}],
            },
        }
        evidence = derive_tracking_from_recent_activity(response)
        self.assertTrue(evidence.visit_events_recent)
        self.assertFalse(evidence.smclient_cookie_seen)
        self.assertTrue(evidence.tracking_active)

    def test_success_false_not_measurable(self):
        evidence = derive_tracking_from_recent_activity(
            {"success": False, "message": ["auth"]}
        )
        self.assertFalse(evidence.tracking_measurable)
        self.assertIsNone(evidence.visit_events_recent)

    def test_recent_activity_singular_key(self):
        response = {
            "success": True,
            "recentActivity": {
                "monitoredContacts": 1,
                "anonymous": [{"url": "/x", "time": 1}],
            },
        }
        evidence = derive_tracking_from_recent_activity(response)
        self.assertTrue(evidence.visit_events_recent)
        self.assertTrue(evidence.smclient_cookie_seen)


class LoadTrackingTests(unittest.TestCase):
    def test_fetch_error_yields_unmeasurable(self):
        def boom(**kwargs):
            raise ManagoFetchError("down")

        evidence = load_manago_tracking_evidence(
            config={"workspace_id": "w", "api_key": "k"},
            fetch_recent_activity=boom,
            now=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )
        self.assertFalse(evidence.tracking_measurable)
        self.assertIn("down", evidence.detail.get("error", ""))

    def test_load_calls_fetch_with_window(self):
        captured: dict = {}

        def fake_fetch(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "recentActivities": {
                    "monitoredContacts": 2,
                    "customers": [{"contactId": "c1", "url": "https://a.test/"}],
                },
            }

        evidence = load_manago_tracking_evidence(
            config={"workspace_id": "w", "api_key": "enc"},
            lookback_days=7,
            fetch_recent_activity=fake_fetch,
            now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(evidence.tracking_active)
        self.assertEqual(captured["timeout"], 20.0)
        delta = captured["window_end"] - captured["window_start"]
        self.assertEqual(delta.days, 7)


class Fd07WithTrackingSignalsTests(unittest.TestCase):
    def test_signals_alone_can_pass_without_scrape(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                visit_events_recent=True,
                smclient_cookie_seen=True,
                tracking_active=True,
                tracking_measurable=True,
            ),
            company_website_domain=None,
            skip_website_scrape=True,
            tenant_id="t",
            run_id="r",
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "PASS")

    def test_explicit_false_signals_fail_without_markers(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                visit_events_recent=False,
                smclient_cookie_seen=False,
                tracking_active=False,
                tracking_measurable=True,
            ),
            company_website_domain=None,
            skip_website_scrape=True,
            tenant_id="t",
            run_id="r",
        )
        result = evaluate_fd_07(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-12")


class DbContextApplyTrackingTests(unittest.TestCase):
    @patch("dataruns.dcs.db_context.load_manago_tracking_evidence")
    def test_apply_merges_payload(self, mock_load):
        from dataruns.dcs.db_context import _apply_manago_tracking_evidence
        from dataruns.dcs.manago_tracking import ManagoTrackingEvidence

        mock_load.return_value = ManagoTrackingEvidence(
            visit_events_recent=True,
            smclient_cookie_seen=True,
            tracking_active=True,
            tracking_measurable=True,
            storefront_domains=["shop.test"],
            detail={"visit_count": 1},
        )
        payload = {
            "connected": True,
            "_config": {"workspace_id": "w", "api_key": "x"},
        }
        _apply_manago_tracking_evidence(payload)
        self.assertTrue(payload["visit_events_recent"])
        self.assertTrue(payload["smclient_cookie_seen"])
        self.assertEqual(payload["storefront_domains"], ["shop.test"])
        self.assertEqual(payload["_tracking_detail"]["visit_count"], 1)

    def test_apply_skips_when_not_connected(self):
        from dataruns.dcs.db_context import _apply_manago_tracking_evidence

        payload = {"connected": False, "_config": {"workspace_id": "w"}}
        _apply_manago_tracking_evidence(payload)
        self.assertNotIn("visit_events_recent", payload)


if __name__ == "__main__":
    unittest.main()
