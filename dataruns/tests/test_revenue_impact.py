"""PRD-DCS-08 revenue impact formulas + dedupe rollup tests."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.lifecycle import (
    evaluate_le_02,
    evaluate_le_04,
    evaluate_le_05,
    evaluate_le_09,
)
from dataruns.dcs.executors.product import evaluate_pt_04
from dataruns.dcs.revenue_impact import (
    attach_revenue_impact,
    duplicate_purchase_gmv,
    money_2,
    rollup_revenue_impact,
    seal_revenue_on_result,
)
from dataruns.dcs.types import CheckResult


def _ctx(snapshot: dict) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-08-03T12:00:00Z",
        extra={"scoring_snapshot": snapshot},
    )


def _connectors_ok() -> dict:
    return {
        "shopify": {"status": "connected"},
        "manago_ai": {"status": "connected"},
    }


def _life_base(**overrides) -> dict:
    life = {
        "shopify_paid_orders": 2,
        "manago_purchase_events": 0,
        "manago_return_cancel_events": 0,
        "shopify_refund_cancel_orders": 0,
        "shopify_order_value": 120.0,
        "shopify_order_value_gross": 120.0,
        "shopify_order_value_net": 120.0,
        "manago_purchase_value": 0.0,
        "in_both": 0,
        "shopify_only": ["o1", "o2"],
        "manago_only": [],
        "shopify_only_count": 2,
        "manago_only_count": 0,
        "gaps_truncated": False,
        "purchase_with_external_id": 0,
        "purchase_without_external_id": 0,
        "duplicate_purchase_clusters": [],
        "duplicate_extra_events": 0,
        "duplicate_purchase_gmv": 0,
        "primary_currency": "EUR",
        "monthly": [
            {
                "month": "2026-07",
                "shopify_orders": 2,
                "manago_purchases": 0,
                "shopify_value": 120.0,
                "manago_value": 0.0,
                "count_delta": 1.0,
                "value_delta": 1.0,
            }
        ],
        "value_decomposition": {
            "missing_events_value": 120.0,
            "extra_events_value": 0,
            "matched_gross_delta": 0,
            "matched_net_delta": 0,
        },
        "return_coverage": {
            "shopify_only_returns": [],
            "manago_only_returns": [],
            "shopify_only_returns_count": 0,
            "manago_only_returns_count": 0,
            "shopify_return_value": 0,
            "shopify_only_returns_value": 0,
            "manago_return_value": 0,
            "return_value_delta": 0,
        },
        "raw_enrichment": {
            "shopify_orders_from_raw": True,
            "manago_purchases_from_raw": True,
            "return_events_from_raw": True,
        },
        "heuristic_match_count": 0,
        "heuristic_matches": [],
        "external_id_known": True,
    }
    life.update(overrides)
    return life


class MoneyHelperTests(SimpleTestCase):
    def test_money_2_half_up(self):
        self.assertEqual(money_2(15.555), 15.56)
        self.assertEqual(money_2(15.554), 15.55)

    def test_duplicate_purchase_gmv(self):
        clusters = [
            {"count": 3, "representative_value": 40, "cluster_impact": 80},
            {"count": 2, "values": [10, 10]},
        ]
        self.assertEqual(duplicate_purchase_gmv(clusters), 90.0)

    def test_attach_and_rollup_dedupes_le02(self):
        le05 = CheckResult(check_id="LE-05", status="FAIL")
        seal_revenue_on_result(
            le05,
            amount=120,
            currency="EUR",
            formula_id="LE-05.missing_purchase_gmv.v1",
            window_days=30,
            as_of="2026-08-03T12:00:00Z",
            source="snapshot_raw",
        )
        le02 = CheckResult(check_id="LE-02", status="FAIL")
        seal_revenue_on_result(
            le02,
            amount=120,
            currency="EUR",
            formula_id="LE-02.missing_events_value.v1",
            window_days=30,
            as_of="2026-08-03T12:00:00Z",
            source="snapshot_raw",
        )
        le09 = CheckResult(check_id="LE-09", status="FAIL")
        seal_revenue_on_result(
            le09,
            amount=30,
            currency="EUR",
            formula_id="LE-09.missing_return_gmv.v1",
            window_days=30,
            as_of="2026-08-03T12:00:00Z",
            source="snapshot_raw",
        )
        rollup = rollup_revenue_impact([le05, le02, le09])
        self.assertEqual(rollup["estimate"], 150.0)
        self.assertEqual(rollup["by_check"]["LE-05"], 120.0)
        self.assertEqual(rollup["by_check"]["LE-09"], 30.0)
        self.assertEqual(rollup["excluded_from_rollup"]["LE-02"], 120.0)
        self.assertNotIn("LE-02", rollup["by_check"])

    def test_pass_and_non_allowlist_zero(self):
        passed = CheckResult(check_id="LE-05", status="PASS")
        seal_revenue_on_result(
            passed,
            amount=999,
            currency="EUR",
            formula_id="LE-05.missing_purchase_gmv.v1",
            window_days=30,
            as_of="2026-08-03T12:00:00Z",
            source="snapshot_raw",
        )
        self.assertEqual(passed.provenance["revenue_impact"], 0.0)

        ci = CheckResult(check_id="CI-01", status="FAIL")
        attach_revenue_impact(
            {},
            amount=50,
            currency="EUR",
            formula_id="x",
            window_days=30,
            as_of="2026-08-03T12:00:00Z",
            source="snapshot_raw",
        )
        # CI-01 not sealed by allowlist executors; rollup ignores it.
        ci.provenance = {"revenue_impact": 50}
        rollup = rollup_revenue_impact([passed, ci])
        self.assertEqual(rollup["estimate"], 0.0)
        self.assertEqual(rollup["by_check"], {})


class Le05Le02RevenueTests(SimpleTestCase):
    def test_missing_orders_fifty_and_seventy(self):
        life = _life_base()
        snapshot = {
            "as_of": "2026-08-03T12:00:00Z",
            "window_days": 30,
            "connectors": _connectors_ok(),
            "lifecycle": life,
            "orders": [
                {
                    "order.id": "o1",
                    "amount_gross": 50.0,
                    "currency": "EUR",
                },
                {
                    "order.id": "o2",
                    "amount_gross": 70.0,
                    "currency": "EUR",
                },
            ],
        }
        r05 = evaluate_le_05(_ctx(snapshot))
        self.assertEqual(r05.status, "FAIL")
        self.assertEqual(r05.provenance["revenue_impact"], 120.0)
        self.assertEqual(
            r05.provenance["revenue_formula_id"], "LE-05.missing_purchase_gmv.v1"
        )
        self.assertEqual(r05.provenance["revenue_currency"], "EUR")

        r02 = evaluate_le_02(_ctx(snapshot))
        self.assertEqual(r02.status, "FAIL")
        self.assertEqual(r02.provenance["revenue_impact"], 120.0)
        self.assertEqual(
            r02.provenance["revenue_formula_id"], "LE-02.missing_events_value.v1"
        )

        rollup = rollup_revenue_impact([r05, r02])
        self.assertEqual(rollup["estimate"], 120.0)


class Le09RevenueTests(SimpleTestCase):
    def test_refund_without_manago_return(self):
        life = _life_base(
            shopify_paid_orders=1,
            manago_purchase_events=1,
            shopify_only=[],
            shopify_only_count=0,
            shopify_order_value_gross=100,
            manago_purchase_value=100,
            shopify_refund_cancel_orders=1,
            manago_return_cancel_events=0,
            value_decomposition={
                "missing_events_value": 0,
                "extra_events_value": 0,
                "matched_gross_delta": 0,
                "matched_net_delta": 0,
            },
            monthly=[
                {
                    "month": "2026-07",
                    "shopify_orders": 1,
                    "manago_purchases": 1,
                    "shopify_value": 100,
                    "manago_value": 100,
                    "count_delta": 0,
                    "value_delta": 0,
                }
            ],
            return_coverage={
                "shopify_only_returns": ["r1"],
                "manago_only_returns": [],
                "shopify_only_returns_count": 1,
                "manago_only_returns_count": 0,
                "shopify_return_value": 30.0,
                "shopify_only_returns_value": 30.0,
                "manago_return_value": 0,
                "return_value_delta": 1.0,
            },
        )
        snapshot = {
            "as_of": "2026-08-03T12:00:00Z",
            "window_days": 30,
            "connectors": _connectors_ok(),
            "lifecycle": life,
        }
        result = evaluate_le_09(_ctx(snapshot))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.provenance["revenue_impact"], 30.0)
        rollup = rollup_revenue_impact([result])
        self.assertEqual(rollup["estimate"], 30.0)


class Le04RevenueTests(SimpleTestCase):
    def test_dup_cluster_three_events_value_40(self):
        life = _life_base(
            shopify_paid_orders=1,
            manago_purchase_events=3,
            shopify_only=[],
            shopify_only_count=0,
            shopify_order_value_gross=40,
            manago_purchase_value=120,
            duplicate_purchase_clusters=[
                {
                    "order.id": "oid-1",
                    "count": 3,
                    "values": [40, 40, 40],
                    "representative_value": 40,
                    "cluster_impact": 80,
                }
            ],
            duplicate_extra_events=2,
            duplicate_purchase_gmv=80,
            value_decomposition={
                "missing_events_value": 0,
                "extra_events_value": 80,
                "matched_gross_delta": 0,
                "matched_net_delta": 0,
            },
            monthly=[
                {
                    "month": "2026-07",
                    "shopify_orders": 1,
                    "manago_purchases": 3,
                    "shopify_value": 40,
                    "manago_value": 120,
                    "count_delta": 0.67,
                    "value_delta": 0.67,
                }
            ],
        )
        snapshot = {
            "as_of": "2026-08-03T12:00:00Z",
            "window_days": 30,
            "connectors": _connectors_ok(),
            "lifecycle": life,
        }
        result = evaluate_le_04(_ctx(snapshot))
        self.assertIn(result.status, {"FAIL", "WARN"})
        self.assertEqual(result.provenance["revenue_impact"], 80.0)


class Pt04RevenueTests(SimpleTestCase):
    def test_total_overstatement(self):
        snapshot = {
            "as_of": "2026-08-03T12:00:00Z",
            "window_days": 30,
            "connectors": _connectors_ok(),
            "product_truth": {
                "linked_contacts": 2,
                "contacts_over_delta": 1,
                "contacts_refund_blind": 0,
                "total_overstatement": 15.5,
                "fail_delta": 0.02,
                "failing_sample": [
                    {
                        "person.email": "a@x.com",
                        "shopify_net": 10,
                        "manago_purchase_value_deduped": 25.5,
                        "delta_vs_net": 0.6,
                        "overstatement": 15.5,
                        "refund_blind": False,
                    }
                ],
                "refund_blind_sample": [],
                "raw_enrichment": {
                    "shopify_from_raw": True,
                    "manago_from_raw": True,
                },
            },
        }
        result = evaluate_pt_04(_ctx(snapshot))
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.provenance["revenue_impact"], 15.50)
        self.assertEqual(
            result.provenance["revenue_formula_id"], "PT-04.ltv_overstatement.v1"
        )
        self.assertIsNone(result.provenance["revenue_window_days"])
        self.assertEqual(
            result.provenance["revenue_scope"], "lifetime_linked_contacts"
        )


class UnknownLifecycleRevenueTests(SimpleTestCase):
    def test_unknown_lifecycle_zero_no_crash(self):
        snapshot = {
            "connectors": {
                "shopify": {"status": "connected"},
                "manago_ai": {"status": "disconnected"},
            },
            "lifecycle": {},
        }
        result = evaluate_le_05(_ctx(snapshot))
        self.assertIn(result.status, {"UNKNOWN", "NOT_CONNECTED"})
        # Early exit may not seal money; rollup must still be safe.
        rollup = rollup_revenue_impact([result])
        self.assertEqual(rollup["estimate"], 0.0)
