"""Lifecycle LE-01/02/03/04/05/09 executor + join tests (Excel sheet 02 / PRD-DCS-04)."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.lifecycle import (
    evaluate_le_01,
    evaluate_le_02,
    evaluate_le_03,
    evaluate_le_04,
    evaluate_le_05,
    evaluate_le_09,
)
from dataruns.dcs.lifecycle_join import build_lifecycle_snapshot
from dataruns.models import Contact, Order
from tenants.models import Company, Tenant


def _ctx(snapshot: dict) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-07-31T12:00:00Z",
        extra={"scoring_snapshot": snapshot},
    )


def _base_lifecycle(**overrides) -> dict:
    life = {
        "shopify_paid_orders": 100,
        "manago_purchase_events": 100,
        "manago_return_cancel_events": 0,
        "shopify_refund_cancel_orders": 0,
        "shopify_order_value": 1000.0,
        "manago_purchase_value": 1000.0,
        "in_both": 100,
        "shopify_only": [],
        "manago_only": [],
        "shopify_only_count": 0,
        "manago_only_count": 0,
        "gaps_truncated": False,
        "purchase_with_external_id": 100,
        "purchase_without_external_id": 0,
        "duplicate_purchase_clusters": [],
        "duplicate_extra_events": 0,
        "monthly": [
            {
                "month": "2026-07",
                "shopify_orders": 100,
                "manago_purchases": 100,
                "shopify_value": 1000.0,
                "manago_value": 1000.0,
                "count_delta": 0.0,
                "value_delta": 0.0,
            }
        ],
        "return_coverage": {
            "shopify_only_returns": [],
            "manago_only_returns": [],
            "shopify_only_returns_count": 0,
            "manago_only_returns_count": 0,
        },
        "raw_enrichment": {
            "shopify_raw_present": False,
            "manago_raw_present": False,
            "return_events_from_raw": False,
            "external_id_from_raw": False,
        },
        "shopify_excluded_test_orders": 0,
        "test_filter_applied": True,
        "external_id_known": True,
        "heuristic_match_count": 0,
        "heuristic_matches": [],
        "value_decomposition": {
            "missing_events_value": 0,
            "extra_events_value": 0,
            "matched_gross_delta": 0,
            "matched_net_delta": 0,
        },
        "value_composition": {
            "shopify_field": "total_price (gross)",
            "manago_field": "PURCHASE event value",
        },
        "shopify_order_value_gross": 1000.0,
        "shopify_order_value_net": 900.0,
    }
    life.update(overrides)
    return {
        "connectors": {
            "shopify": {"status": "connected"},
            "manago_ai": {"status": "connected"},
        },
        "lifecycle": life,
        "events": [],
        "orders": [],
    }


class EvaluateLe01Tests(SimpleTestCase):
    def test_pass_within_two_percent(self):
        # 100 vs 101 → ~1% < 2%
        result = evaluate_le_01(
            _ctx(
                _base_lifecycle(
                    shopify_paid_orders=100,
                    manago_purchase_events=101,
                    monthly=[
                        {
                            "month": "2026-07",
                            "shopify_orders": 100,
                            "manago_purchases": 101,
                            "shopify_value": 1000,
                            "manago_value": 1010,
                            "count_delta": 0.0099,
                            "value_delta": 0.0099,
                        }
                    ],
                )
            )
        )
        self.assertEqual(result.status, "PASS")

    def test_fail_when_month_delta_over_two_percent(self):
        result = evaluate_le_01(
            _ctx(
                _base_lifecycle(
                    shopify_paid_orders=100,
                    manago_purchase_events=90,
                    shopify_only=["o-missing"],
                    shopify_only_count=10,
                    monthly=[
                        {
                            "month": "2026-07",
                            "shopify_orders": 100,
                            "manago_purchases": 90,
                            "shopify_value": 1000,
                            "manago_value": 900,
                            "count_delta": 0.1,
                            "value_delta": 0.1,
                        }
                    ],
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertIn(
            "o-missing", [m["order.id"] for m in result.provenance["mismatches"]]
        )


class EvaluateLe05Tests(SimpleTestCase):
    def test_fail_lists_real_order_ids(self):
        result = evaluate_le_05(
            _ctx(
                _base_lifecycle(
                    shopify_only=["501", "502"],
                    manago_only=["999"],
                    shopify_only_count=2,
                    manago_only_count=1,
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        sides = {(m["side"], m["order.id"]) for m in result.provenance["mismatches"]}
        self.assertIn(("shopify_only", "501"), sides)
        self.assertIn(("manago_only", "999"), sides)

    def test_pass_when_no_gaps(self):
        result = evaluate_le_05(_ctx(_base_lifecycle()))
        self.assertEqual(result.status, "PASS")


class EvaluateLe02Tests(SimpleTestCase):
    def test_fail_value_delta(self):
        result = evaluate_le_02(
            _ctx(
                _base_lifecycle(
                    shopify_order_value=1000,
                    manago_purchase_value=800,
                    monthly=[
                        {
                            "month": "2026-07",
                            "shopify_orders": 100,
                            "manago_purchases": 100,
                            "shopify_value": 1000,
                            "manago_value": 800,
                            "count_delta": 0.0,
                            "value_delta": 0.2,
                        }
                    ],
                )
            )
        )
        self.assertEqual(result.status, "FAIL")


class EvaluateLe03Tests(SimpleTestCase):
    def test_fail_low_external_id_share(self):
        result = evaluate_le_03(
            _ctx(
                _base_lifecycle(
                    manago_purchase_events=10,
                    purchase_with_external_id=5,
                    purchase_without_external_id=5,
                    external_id_known=True,
                )
            )
        )
        self.assertEqual(result.status, "FAIL")

    def test_unknown_without_raw_external_id(self):
        result = evaluate_le_03(
            _ctx(
                _base_lifecycle(
                    manago_purchase_events=10,
                    purchase_with_external_id=0,
                    purchase_without_external_id=0,
                    external_id_known=False,
                )
            )
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:manago_raw_external_id")


class EvaluateLe04Tests(SimpleTestCase):
    def test_warn_on_duplicate_cluster(self):
        result = evaluate_le_04(
            _ctx(
                _base_lifecycle(
                    manago_purchase_events=100,
                    duplicate_purchase_clusters=[
                        {"order.id": "501", "count": 2, "values": [10, 10]}
                    ],
                    duplicate_extra_events=1,
                )
            )
        )
        self.assertEqual(result.status, "WARN")
        self.assertEqual(result.provenance["mismatches"][0]["order.id"], "501")


class EvaluateLe09Tests(SimpleTestCase):
    def test_fail_when_shopify_refunds_without_manago_returns(self):
        result = evaluate_le_09(
            _ctx(
                _base_lifecycle(
                    shopify_refund_cancel_orders=3,
                    manago_return_cancel_events=0,
                    return_coverage={
                        "shopify_only_returns": ["r1", "r2", "r3"],
                        "manago_only_returns": [],
                        "shopify_only_returns_count": 3,
                        "manago_only_returns_count": 0,
                    },
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-01")

    def test_pass_when_neither_side_has_returns(self):
        result = evaluate_le_09(_ctx(_base_lifecycle()))
        self.assertEqual(result.status, "PASS")


class LifecycleJoinDbTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="LE Tenant", slug="le-tenant")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="LE Co",
            domain="le.example",
        )

    def test_join_paid_orders_and_purchases(self):
        sc = Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="c1",
            email="a@example.com",
        )
        mc = Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="m1",
            email="a@example.com",
            link_key="c1",
        )
        Order.objects.create(
            company=self.company,
            contact=sc,
            source="shopify",
            external_id="501",
            amount="10.00",
            currency="EUR",
            status="paid",
        )
        Order.objects.create(
            company=self.company,
            contact=sc,
            source="shopify",
            external_id="502",
            amount="20.00",
            currency="EUR",
            status="paid",
        )
        Order.objects.create(
            company=self.company,
            contact=mc,
            source="manago_ai",
            external_id="501",
            amount="10.00",
            currency="EUR",
            status="paid",
        )

        payload = build_lifecycle_snapshot(company=self.company)
        life = payload["lifecycle"]
        self.assertEqual(life["shopify_paid_orders"], 2)
        self.assertEqual(life["manago_purchase_events"], 1)
        self.assertEqual(life["shopify_only_count"], 1)
        self.assertEqual(life["shopify_only"], ["502"])
        self.assertEqual(life["in_both"], 1)
        self.assertFalse(life["external_id_known"])  # no Manago raw
        self.assertFalse(life["test_filter_applied"])  # no Shopify raw
        types = {e["type"] for e in payload["events"]}
        self.assertIn("PURCHASE", types)


class LifecycleJoinRawTests(SimpleTestCase):
    """Unit tests for raw-path helpers (Excel LE-01/03/05/09)."""

    def test_shopify_excludes_test_and_uses_cancelled_at(self):
        from dataruns.dcs.lifecycle_join import _shopify_orders_from_raw

        paid, refunds, excluded = _shopify_orders_from_raw(
            {
                "orders": [
                    {
                        "id": 1,
                        "test": True,
                        "financial_status": "paid",
                        "total_price": "9.00",
                        "currency": "EUR",
                        "created_at": "2026-07-01T00:00:00Z",
                    },
                    {
                        "id": 2,
                        "test": False,
                        "financial_status": "paid",
                        "total_price": "10.00",
                        "subtotal_price": "8.00",
                        "currency": "EUR",
                        "created_at": "2026-07-02T00:00:00Z",
                        "customer": {"id": 9, "email": "a@x.com"},
                    },
                    {
                        "id": 3,
                        "financial_status": "paid",
                        "cancelled_at": "2026-07-03T00:00:00Z",
                        "total_price": "5.00",
                        "currency": "EUR",
                        "created_at": "2026-07-02T00:00:00Z",
                    },
                    {
                        "id": 4,
                        "financial_status": "refunded",
                        "total_price": "7.00",
                        "currency": "EUR",
                        "created_at": "2026-07-04T00:00:00Z",
                    },
                ]
            }
        )
        self.assertEqual(excluded, 1)
        self.assertEqual([o["order.id"] for o in paid], ["2"])
        self.assertEqual(paid[0]["amount_net"], 8.0)
        statuses = {o["order.id"]: o["status"] for o in refunds}
        self.assertEqual(statuses["3"], "cancelled")
        self.assertEqual(statuses["4"], "refunded")

    def test_manago_external_id_only_when_field_present(self):
        from dataruns.dcs.lifecycle_join import _manago_purchases_from_raw

        rows = _manago_purchases_from_raw(
            {
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "externalId": "501",
                        "transactionId": "txn-1",
                        "value": 10,
                        "email": "a@x.com",
                        "date": 1720000000000,
                    },
                    {
                        "contactExtEventType": "PURCHASE",
                        "transactionId": "txn-2",
                        "value": 20,
                        "email": "b@x.com",
                        "date": 1720000000000,
                    },
                ]
            }
        )
        by_id = {r["order.id"]: r for r in rows}
        self.assertTrue(by_id["501"]["has_external_id"])
        self.assertEqual(by_id["501"]["join_key_source"], "externalId")
        self.assertFalse(by_id["txn-2"]["has_external_id"])
        self.assertEqual(by_id["txn-2"]["join_key_source"], "transactionId")

    def test_heuristic_join_email_date_value(self):
        from dataruns.dcs.lifecycle_join import _reconcile_order_events

        result = _reconcile_order_events(
            paid_shopify=[
                {
                    "order.id": "501",
                    "person.email": "a@x.com",
                    "amount_gross": 10.0,
                    "ordered_at": "2026-07-01T12:00:00Z",
                }
            ],
            purchase_events=[
                {
                    "order.id": "",
                    "person.email": "a@x.com",
                    "value": 10.0,
                    "occurred_at": "2026-07-01T18:00:00Z",
                    "has_external_id": False,
                }
            ],
        )
        self.assertEqual(result["in_both"], 1)
        self.assertEqual(result["heuristic_match_count"], 1)
        self.assertEqual(result["shopify_only_all"], [])
