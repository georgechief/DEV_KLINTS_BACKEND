"""DRIFT join metrics — LE-13 checkout volume + SP-08 API tags."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from dataruns.dcs.drift_join import build_drift_snapshot


def _as_of() -> datetime:
    return datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


class DriftJoinLe13CheckoutVolumeTests(SimpleTestCase):
    def test_shopify_volume_includes_checkouts(self):
        as_of = _as_of()
        day_in_7 = (as_of - timedelta(days=2)).strftime("%Y-%m-%dT10:00:00Z")
        day_in_prior = (as_of - timedelta(days=14)).strftime("%Y-%m-%dT10:00:00Z")

        manago = {
            "contacts": [],
            "transactions": [
                {
                    "contactExtEventType": "PURCHASE",
                    "date": day_in_7,
                    "value": 10,
                }
            ],
            "events": [],
            "tags": [],
        }
        shopify = {
            "orders": [
                {
                    "id": 1,
                    "created_at": day_in_7,
                    "financial_status": "paid",
                    "total_price": "20.00",
                }
            ],
            "customers": [],
            "checkouts": [
                {"id": 100, "created_at": day_in_7, "completed_at": None},
                {"id": 101, "created_at": day_in_prior, "completed_at": None},
            ],
        }

        def fake_raw(*, company, platform):
            if platform == "manago_ai":
                return manago
            return shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["le13_shopify_orders_7d"], 1)
        self.assertEqual(out["le13_shopify_checkouts_7d"], 1)
        self.assertEqual(out["le13_shopify_7d"], 2)
        self.assertEqual(out["le13_shopify_prior_21d"], 1)


class DriftJoinSp08ApiTagsTests(SimpleTestCase):
    def test_uses_api_number_of_tagged(self):
        as_of = _as_of()
        manago = {
            "contacts": [
                {"contactId": "c1", "email": "a@x.com", "optedOut": False},
                {"contactId": "c2", "email": "b@x.com", "optedOut": False},
            ],
            "transactions": [],
            "events": [],
            "tags": [
                {"tag": "VIP", "numberOfTagged": 2},
                {"tag": "everyone", "numberOfTagged": 2},
                {"tag": "unused", "numberOfTagged": 0},
            ],
        }
        shopify = {"orders": [], "customers": [], "checkouts": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertTrue(out["sp08_from_api_tags"])
        self.assertEqual(out["sp08_tag_count"], 3)
        self.assertEqual(out["sp08_api_zero_tag_count"], 1)
        # API numberOfTagged must not use window contact count for all-contacts.
        self.assertEqual(out["sp08_all_contacts_tags"], [])
        # Unused catalog tags must not count as FAIL zero-population.
        self.assertEqual(out["sp08_zero_population"], 0)
        pops = {r["tag"]: r["count"] for r in out["sp08_tag_populations_sample"]}
        self.assertEqual(pops.get("tag:VIP"), 2)
        self.assertNotIn("tag:unused", pops)

    def test_api_large_tag_not_all_contacts_vs_window(self):
        as_of = _as_of()
        manago = {
            "contacts": [{"contactId": "c1", "email": "a@x.com"}],
            "transactions": [],
            "events": [],
            "tags": [{"tag": "VIP", "numberOfTagged": 5000}],
        }
        shopify = {"orders": [], "customers": [], "checkouts": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["sp08_all_contacts_tag_count"], 0)

    def test_funnel_all_contacts_still_flagged_with_api_tags(self):
        as_of = _as_of()
        manago = {
            "contacts": [
                {
                    "contactId": "c1",
                    "email": "a@x.com",
                    "contactFunnels": [{"name": "EveryoneFunnel"}],
                },
                {
                    "contactId": "c2",
                    "email": "b@x.com",
                    "contactFunnels": [{"name": "EveryoneFunnel"}],
                },
            ],
            "transactions": [],
            "events": [],
            "tags": [{"tag": "VIP", "numberOfTagged": 9}],
        }
        shopify = {"orders": [], "customers": [], "checkouts": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertIn("funnel:EveryoneFunnel", out["sp08_all_contacts_tags"])
        self.assertNotIn("tag:VIP", out["sp08_all_contacts_tags"])

    def test_skip_shift_when_prior_source_mismatches(self):
        as_of = _as_of()
        manago = {
            "contacts": [{"contactId": "c1"}],
            "transactions": [],
            "events": [],
            "tags": [{"tag": "VIP", "numberOfTagged": 5000}],
        }
        shopify = {"orders": [], "customers": [], "checkouts": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={
                    "sp08_from_api_tags": False,
                    "sp08_tag_populations_sample": [
                        {"tag": "tag:VIP", "segment": "tag:VIP", "count": 1}
                    ],
                },
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertTrue(out["sp08_shift_unavailable"])
        self.assertEqual(out["sp08_shifted_count"], 0)


class DriftJoinCartDedupTests(SimpleTestCase):
    def test_nested_and_events_blob_do_not_double_count(self):
        as_of = _as_of()
        day = (as_of - timedelta(days=20)).strftime("%Y-%m-%dT10:00:00Z")
        cart = {
            "contactExtEventType": "CART",
            "date": day,
            "externalId": "cart-1",
            "contactId": "c1",
            "email": "a@x.com",
        }
        manago = {
            "contacts": [
                {
                    "contactId": "c1",
                    "email": "a@x.com",
                    "contactExtEvents": [cart],
                }
            ],
            "transactions": [],
            "events": [cart],
            "tags": [],
        }
        shopify = {"orders": [], "customers": [], "checkouts": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["le08_cart_events"], 1)
        self.assertEqual(out["le08_open_stale_carts"], 1)

    def test_fallback_to_nested_when_blob_has_no_carts(self):
        as_of = _as_of()
        day = (as_of - timedelta(days=20)).strftime("%Y-%m-%dT10:00:00Z")
        manago = {
            "contacts": [
                {
                    "contactId": "c1",
                    "email": "a@x.com",
                    "contactExtEvents": [
                        {
                            "contactExtEventType": "CART",
                            "date": day,
                            "externalId": "cart-2",
                        }
                    ],
                }
            ],
            "transactions": [],
            "events": [
                {
                    "contactExtEventType": "VISIT",
                    "date": day,
                    "contactId": "c1",
                }
            ],
            "tags": [],
        }
        shopify = {"orders": [], "customers": [], "checkouts": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["le08_cart_events"], 1)


class DriftJoinLe13CompletedCheckoutTests(SimpleTestCase):
    def test_completed_checkouts_excluded_from_volume(self):
        as_of = _as_of()
        day_in_7 = (as_of - timedelta(days=2)).strftime("%Y-%m-%dT10:00:00Z")
        manago = {
            "contacts": [],
            "transactions": [],
            "events": [],
            "tags": [],
        }
        shopify = {
            "orders": [
                {
                    "id": 1,
                    "created_at": day_in_7,
                    "financial_status": "paid",
                    "total_price": "20.00",
                }
            ],
            "customers": [],
            "checkouts": [
                {
                    "id": 100,
                    "created_at": day_in_7,
                    "completed_at": day_in_7,
                },
                {"id": 101, "created_at": day_in_7, "completed_at": None},
            ],
        }

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch(
                "dataruns.dcs.drift_join._latest_connector_raw",
                side_effect=fake_raw,
            ),
            patch(
                "dataruns.dcs.drift_join._prior_drift_for_company",
                return_value={},
            ),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["le13_shopify_orders_7d"], 1)
        self.assertEqual(out["le13_shopify_checkouts_7d"], 1)
        self.assertEqual(out["le13_shopify_7d"], 2)

class DriftJoinBatch2Tests(SimpleTestCase):
    def test_ci14_visit_identity_match(self):
        as_of = _as_of()
        manago = {
            "contacts": [],
            "transactions": [],
            "events": [
                {"contactExtEventType": "VISIT", "contactId": "c1", "date": "2026-08-01T10:00:00Z"},
                {"contactExtEventType": "VISIT", "date": "2026-08-01T11:00:00Z"},
            ],
            "tags": [],
        }
        shopify = {"orders": [], "customers": [], "checkouts": [], "products": []}

        def fake_raw(*, company, platform):
            if platform == "manago_ai":
                return manago
            return shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch("dataruns.dcs.drift_join._latest_connector_raw", side_effect=fake_raw),
            patch("dataruns.dcs.drift_join._prior_drift_for_company", return_value={}),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["ci14_visit_total"], 2)
        self.assertEqual(out["ci14_visit_identified"], 1)
        self.assertEqual(out["ci14_identity_match_rate"], 0.5)

    def test_le11_race_loss_order(self):
        as_of = _as_of()
        order_ts = (as_of - timedelta(days=1)).strftime("%Y-%m-%dT10:00:00Z")
        cust_ts = (as_of - timedelta(days=1) + timedelta(minutes=30)).strftime(
            "%Y-%m-%dT10:30:00Z"
        )
        manago = {"contacts": [], "transactions": [], "events": [], "tags": []}
        shopify = {
            "orders": [
                {
                    "id": 99,
                    "email": "new@x.com",
                    "created_at": order_ts,
                    "financial_status": "paid",
                    "customer": {"id": 7, "created_at": cust_ts},
                }
            ],
            "customers": [{"id": 7, "created_at": cust_ts}],
            "checkouts": [],
            "products": [],
        }

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch("dataruns.dcs.drift_join._latest_connector_raw", side_effect=fake_raw),
            patch("dataruns.dcs.drift_join._prior_drift_for_company", return_value={}),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["le11_race_loss_orders"], 1)
        self.assertEqual(out["le11_race_loss_share"], 1.0)

    def test_me09_email_stats_and_br02_inventory_levels(self):
        as_of = _as_of()
        fresh = (as_of - timedelta(hours=2)).strftime("%Y-%m-%dT10:00:00Z")
        stale = (as_of - timedelta(hours=48)).strftime("%Y-%m-%dT10:00:00Z")
        manago = {
            "contacts": [{"email": "a@x.com", "invalid": False}],
            "transactions": [],
            "events": [],
            "tags": [],
            "email_stats": {
                "sent": 200,
                "bounce_rate": 0.04,
                "hard_bounce_rate": 0.01,
            },
            "products": [{"id": 1, "updatedOn": fresh}],
        }
        shopify = {
            "orders": [],
            "customers": [],
            "checkouts": [],
            "products": [],
            "inventory_levels": [
                {"inventory_item_id": 1, "updated_at": fresh},
                {"inventory_item_id": 2, "updated_at": stale},
            ],
        }

        def fake_raw(*, company, platform):
            if platform == "manago_ai":
                return manago
            if platform == "erp":
                return {}
            return shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch("dataruns.dcs.drift_join._latest_connector_raw", side_effect=fake_raw),
            patch("dataruns.dcs.drift_join._prior_drift_for_company", return_value={}),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertTrue(out["me09_stats_available"])
        self.assertEqual(out["me09_bounce_rate"], 0.04)
        self.assertEqual(out["br02_inventory_source"], "inventory_levels")
        self.assertEqual(out["br02_shopify_inventory_n"], 2)
        self.assertEqual(out["br02_shopify_stale_share"], 0.5)

    def test_br12_erp_heartbeat_domains(self):
        as_of = _as_of()
        sync_ts = (as_of - timedelta(hours=6)).strftime("%Y-%m-%dT06:00:00Z")
        manago = {"contacts": [], "transactions": [], "events": [], "tags": []}
        shopify = {"orders": [], "customers": [], "checkouts": [], "products": []}
        erp = {
            "sync_domains": {
                "stock": {"last_success_at": sync_ts},
                "prices": {"last_sync_at": sync_ts},
            }
        }

        def fake_raw(*, company, platform):
            if platform == "manago_ai":
                return manago
            if platform == "erp":
                return erp
            return shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch("dataruns.dcs.drift_join._latest_connector_raw", side_effect=fake_raw),
            patch("dataruns.dcs.drift_join._prior_drift_for_company", return_value={}),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertEqual(out["br12_domain_count"], 2)
        self.assertEqual(out["br12_heartbeat_source"], "erp_domains")
        self.assertTrue(out["br12_erp_raw_present"])
        self.assertAlmostEqual(out["br12_domain_ages_hours"]["stock"], 6.0, places=1)

    def test_sp12_dict_date_property_write(self):
        as_of = _as_of()
        stale_ts = (as_of - timedelta(days=200)).strftime("%Y-%m-%dT10:00:00Z")
        manago = {
            "contacts": [
                {
                    "email": "a@x.com",
                    "modifiedOn": as_of.strftime("%Y-%m-%dT12:00:00Z"),
                    "dictionaryProperties": [
                        {"name": "last_purchase", "type": "DATE", "value": stale_ts}
                    ],
                }
            ],
            "transactions": [],
            "events": [],
            "tags": [],
            "workflows": [],
        }
        shopify = {"orders": [], "customers": [], "checkouts": [], "products": []}

        def fake_raw(*, company, platform):
            return manago if platform == "manago_ai" else shopify

        with (
            patch("dataruns.dcs.drift_join._utcnow", return_value=as_of),
            patch("dataruns.dcs.drift_join._latest_connector_raw", side_effect=fake_raw),
            patch("dataruns.dcs.drift_join._prior_drift_for_company", return_value={}),
        ):
            out = build_drift_snapshot(company=MagicMock())["drift"]

        self.assertGreaterEqual(out["sp12_decision_field_count"], 1)
        self.assertGreaterEqual(out["sp12_stale_field_count"], 1)
        self.assertTrue(
            any(
                s.get("field") == "dict:last_purchase"
                for s in (out.get("sp12_stale_sample") or [])
            )
        )
