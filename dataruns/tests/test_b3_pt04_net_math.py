"""B3 — PT-04 Shopify net math (Excel orders − actual refunds).

Fixtures derive expected nets independently of the old paid−full_refunded bug.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.dcs.product_truth import (
    build_product_truth_snapshot,
    dollars_to_cents,
    klints_net_ltv_dollars_from_contact,
    klints_net_ltv_matches_shopify_net,
    shopify_order_net_contribution,
)


class ShopifyOrderNetContributionTests(SimpleTestCase):
    def test_paid_order(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "paid",
                "total_price": "100.00",
                "test": False,
            }
        )
        self.assertEqual(c["paid"], 100.0)
        self.assertEqual(c["refunded"], 0.0)
        self.assertEqual(c["net"], 100.0)

    def test_full_refund_status_without_refund_rows(self):
        """Fully refunded order alone → net 0 (not −total_price)."""
        c = shopify_order_net_contribution(
            {
                "financial_status": "refunded",
                "total_price": "40.00",
                "test": False,
            }
        )
        self.assertEqual(c["paid"], 40.0)
        self.assertEqual(c["refunded"], 40.0)
        self.assertEqual(c["net"], 0.0)

    def test_partial_refund_from_refunds_array(self):
        """Partial refund $20 on $100 → net 80."""
        c = shopify_order_net_contribution(
            {
                "financial_status": "partially_refunded",
                "total_price": "100.00",
                "currency": "USD",
                "test": False,
                "refunds": [
                    {
                        "transactions": [
                            {"kind": "refund", "status": "success", "amount": "20.00"}
                        ]
                    }
                ],
            }
        )
        self.assertEqual(c["paid"], 100.0)
        self.assertEqual(c["refunded"], 20.0)
        self.assertEqual(c["net"], 80.0)
        self.assertFalse(c["incomplete_refund_history"])

    def test_refund_falls_back_to_line_items_when_txns_unusable(self):
        """Non-refund txn kinds must not block refund_line_items amounts."""
        c = shopify_order_net_contribution(
            {
                "financial_status": "partially_refunded",
                "total_price": "100.00",
                "test": False,
                "refunds": [
                    {
                        "transactions": [
                            {"kind": "sale", "status": "success", "amount": "100.00"}
                        ],
                        "refund_line_items": [{"subtotal": "25.00"}],
                    }
                ],
            }
        )
        self.assertEqual(c["refunded"], 25.0)
        self.assertEqual(c["net"], 75.0)
        self.assertFalse(c["incomplete_refund_history"])

    def test_refund_exceeding_paid_marked_incomplete(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "partially_refunded",
                "total_price": "50.00",
                "test": False,
                "refunds": [
                    {
                        "transactions": [
                            {"kind": "refund", "status": "success", "amount": "80.00"}
                        ]
                    }
                ],
            }
        )
        self.assertTrue(c["incomplete_refund_history"])
        self.assertEqual(c["net"], 0.0)

    def test_partial_refund_missing_amounts_marked_incomplete(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "partially_refunded",
                "total_price": "100.00",
                "test": False,
            }
        )
        self.assertTrue(c["incomplete_refund_history"])
        self.assertEqual(c["paid"], 100.0)
        self.assertEqual(c["refunded"], 0.0)
        self.assertEqual(c["net"], 100.0)

    def test_unpaid_cancellation_excluded(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "voided",
                "total_price": "75.00",
                "cancelled_at": "2026-01-01T00:00:00Z",
                "test": False,
            }
        )
        self.assertEqual(c["net"], 0.0)
        self.assertEqual(c["paid"], 0.0)
        self.assertEqual(c["refunded"], 0.0)
        self.assertEqual(c["skipped_reason"], "unpaid_cancellation")

    def test_multiple_refunds_sum(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "partially_refunded",
                "total_price": "100.00",
                "test": False,
                "refunds": [
                    {
                        "transactions": [
                            {"kind": "refund", "status": "success", "amount": "10.00"}
                        ]
                    },
                    {
                        "transactions": [
                            {"kind": "refund", "status": "success", "amount": "15.00"}
                        ]
                    },
                ],
            }
        )
        self.assertEqual(c["refunded"], 25.0)
        self.assertEqual(c["net"], 75.0)

    def test_partially_paid_uses_outstanding_when_present(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "partially_paid",
                "total_price": "100.00",
                "total_outstanding": "40.00",
                "test": False,
            }
        )
        self.assertEqual(c["paid"], 60.0)
        self.assertEqual(c["net"], 60.0)


class ProductTruthB3NetAggregationTests(SimpleTestCase):
    def test_paid_plus_fully_refunded_separate_orders_net_100(self):
        """Client fixture: paid 100 + refunded 40 → net 100 (not 60)."""
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101, "email": "a@x.com"},
                            "financial_status": "paid",
                            "total_price": "100.00",
                            "currency": "USD",
                            "test": False,
                        },
                        {
                            "id": 2,
                            "customer": {"id": 101},
                            "financial_status": "refunded",
                            "total_price": "40.00",
                            "currency": "USD",
                            "test": False,
                        },
                    ],
                }
            return {
                "contacts": [
                    {"contactId": "m1", "externalId": "101", "email": "a@x.com"}
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "1",
                        "value": 100,
                    }
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertEqual(row["shopify_net"], 100.0)
        self.assertEqual(row["shopify_paid_gross"], 140.0)
        self.assertEqual(row["shopify_refunded"], 40.0)
        self.assertFalse(row["mixed_currency"])
        self.assertEqual(
            payload["product_truth"]["revenue_scope"],
            "shopify_orders_in_import_snapshot",
        )

    def test_unpaid_cancel_does_not_reduce_net(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101},
                            "financial_status": "paid",
                            "total_price": "50.00",
                            "test": False,
                        },
                        {
                            "id": 2,
                            "customer": {"id": 101},
                            "financial_status": "voided",
                            "total_price": "50.00",
                            "cancelled_at": "2026-01-02T00:00:00Z",
                            "test": False,
                        },
                    ],
                }
            return {
                "contacts": [
                    {"contactId": "m1", "externalId": "101", "email": "a@x.com"}
                ],
                "transactions": [],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertEqual(row["shopify_net"], 50.0)
        self.assertEqual(row["shopify_refunded"], 0.0)

    def test_mixed_currency_flagged(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101},
                            "financial_status": "paid",
                            "total_price": "10.00",
                            "currency": "USD",
                            "test": False,
                        },
                        {
                            "id": 2,
                            "customer": {"id": 101},
                            "financial_status": "paid",
                            "total_price": "10.00",
                            "currency": "EUR",
                            "test": False,
                        },
                    ],
                }
            return {
                "contacts": [
                    {"contactId": "m1", "externalId": "101", "email": "a@x.com"}
                ],
                "transactions": [],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertTrue(row["mixed_currency"])
        self.assertEqual(set(row["shopify_currencies"]), {"USD", "EUR"})
        # Phase 2: mixed currency forces FAIL visibility (not certifiable).
        self.assertEqual(payload["product_truth"]["contacts_over_delta"], 1)
        self.assertFalse(row["governed_by_klints_net_ltv"])

    def test_incomplete_partial_refund_forces_over_delta(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101},
                            "financial_status": "partially_refunded",
                            "total_price": "100.00",
                            "test": False,
                        }
                    ],
                }
            return {
                "contacts": [
                    {
                        "contactId": "m1",
                        "externalId": "101",
                        "email": "a@x.com",
                        "properties": {"klints_net_ltv": 100},
                    }
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "1",
                        "value": 100,
                    }
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertTrue(row["incomplete_refund_history"])
        self.assertFalse(row["governed_by_klints_net_ltv"])
        self.assertEqual(payload["product_truth"]["contacts_over_delta"], 1)

    def test_paid_cancel_without_refund_amounts_incomplete(self):
        c = shopify_order_net_contribution(
            {
                "financial_status": "paid",
                "total_price": "80.00",
                "cancelled_at": "2026-01-01T00:00:00Z",
                "test": False,
            }
        )
        self.assertTrue(c["incomplete_refund_history"])
        self.assertEqual(c["paid"], 80.0)

    def test_dictionary_cents_stamp_governs(self):
        """NUMBER dictionary cents → dollars for WB-12 match."""
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101},
                            "financial_status": "paid",
                            "total_price": "100.00",
                            "test": False,
                        }
                    ],
                }
            return {
                "contacts": [
                    {
                        "contactId": "m1",
                        "externalId": "101",
                        "email": "a@x.com",
                        "dictionaryProperties": [
                            {
                                "name": "klints_net_ltv",
                                "type": "NUMBER",
                                "value": 10000,
                            }
                        ],
                    }
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "1",
                        "value": 140,
                    }
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertEqual(row["klints_net_ltv"], 100.0)
        self.assertTrue(row["governed_by_klints_net_ltv"])

    def test_vip_numeric_condition_compares_stored_cents(self):
        """Manago VIP compares the dictionary NUMBER integer directly (cents).

        Blueprint threshold must be in cents: >= 20000 means $200.00 — not dollars.
        """
        stored_cents = 24995  # $249.95
        vip_threshold_cents = 20000  # $200.00
        self.assertTrue(stored_cents >= vip_threshold_cents)
        self.assertFalse(15000 >= vip_threshold_cents)  # $150 would not qualify
        contact = {
            "dictionaryProperties": [
                {"name": "klints_net_ltv", "type": "NUMBER", "value": stored_cents}
            ]
        }
        dollars = klints_net_ltv_dollars_from_contact(contact)
        self.assertEqual(dollars, 249.95)
        self.assertEqual(dollars_to_cents(249.95), stored_cents)
        # Klints governance still matches on dollars after cents→dollars read.
        self.assertTrue(
            klints_net_ltv_matches_shopify_net(stamped=dollars, shopify_net=249.95)
        )

    def test_order_absent_from_import_snapshot_not_counted(self):
        """Refund of an older order outside the import window cannot appear.

        Fixture: only the paid $100 order is in the snapshot; a $40 refund of an
        older order is absent → net stays 100 (honest window, not invented).
        """
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [{"id": 101, "email": "a@x.com"}],
                    "orders": [
                        {
                            "id": 1,
                            "customer": {"id": 101},
                            "financial_status": "paid",
                            "total_price": "100.00",
                            "test": False,
                        }
                        # Older refunded order intentionally omitted (BOOTSTRAP window).
                    ],
                }
            return {
                "contacts": [
                    {"contactId": "m1", "externalId": "101", "email": "a@x.com"}
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "1",
                        "value": 100,
                    }
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertEqual(row["shopify_net"], 100.0)
        self.assertEqual(row["shopify_refunded"], 0.0)

    def test_phase4_before_after_restamp_evidence(self):
        """B3 Phase 4: wrong legacy stamp → correct net after re-score."""
        company = SimpleNamespace(id="c1")
        shopify = {
            "customers": [{"id": 101, "email": "a@x.com"}],
            "orders": [
                {
                    "id": 1,
                    "customer": {"id": 101},
                    "financial_status": "paid",
                    "total_price": "100.00",
                    "test": False,
                },
                {
                    "id": 2,
                    "customer": {"id": 101},
                    "financial_status": "refunded",
                    "total_price": "40.00",
                    "test": False,
                },
            ],
        }
        manago_before = {
            "contacts": [
                {
                    "contactId": "m1",
                    "externalId": "101",
                    "email": "a@x.com",
                    # Incorrect stamp from old paid−refunded bug (60).
                    "properties": {"klints_net_ltv": "60"},
                }
            ],
            "transactions": [
                {
                    "contactExtEventType": "PURCHASE",
                    "contactId": "m1",
                    "externalId": "1",
                    "value": 100,
                }
            ],
        }
        manago_after = {
            "contacts": [
                {
                    "contactId": "m1",
                    "externalId": "101",
                    "email": "a@x.com",
                    "dictionaryProperties": [
                        {
                            "name": "klints_net_ltv",
                            "type": "NUMBER",
                            "value": 10000,
                        }
                    ],
                }
            ],
            "transactions": manago_before["transactions"],
        }

        def fake_before(*, company, platform, **_kwargs):
            return shopify if platform == "shopify" else manago_before

        def fake_after(*, company, platform, **_kwargs):
            return shopify if platform == "shopify" else manago_after

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_before,
        ):
            before = build_product_truth_snapshot(company=company)
        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_after,
        ):
            after = build_product_truth_snapshot(company=company)

        b_row = before["product_truth_rows"][0]
        a_row = after["product_truth_rows"][0]
        self.assertEqual(b_row["shopify_net"], 100.0)
        self.assertEqual(b_row["klints_net_ltv"], 60.0)
        self.assertFalse(b_row["governed_by_klints_net_ltv"])
        self.assertEqual(before["product_truth"]["contacts_over_delta"], 0)
        # After re-stamp: cents 10000 ⇒ $100 ⇒ governed PASS path.
        self.assertEqual(a_row["klints_net_ltv"], 100.0)
        self.assertTrue(a_row["governed_by_klints_net_ltv"])
        self.assertEqual(after["product_truth"]["contacts_governed_by_klints_net_ltv"], 1)
