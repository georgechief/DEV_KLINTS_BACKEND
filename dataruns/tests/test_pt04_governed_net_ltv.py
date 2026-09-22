"""PRD-WB-12 — PT-04 PASS when klints_net_ltv matches Shopify net."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.product import evaluate_pt_04
from dataruns.dcs.product_truth import (
    build_product_truth_snapshot,
    klints_net_ltv_matches_shopify_net,
)


def _ctx(snapshot: dict) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-09-22T00:00:00Z",
        extra={"scoring_snapshot": snapshot},
    )


class KlintsNetLtvMatchHelperTests(SimpleTestCase):
    def test_absolute_and_relative(self):
        self.assertTrue(
            klints_net_ltv_matches_shopify_net(stamped=60.0, shopify_net=60.0)
        )
        self.assertTrue(
            klints_net_ltv_matches_shopify_net(stamped=60.005, shopify_net=60.0)
        )
        self.assertTrue(
            klints_net_ltv_matches_shopify_net(stamped=100.0, shopify_net=99.0)
        )  # ~1% < 2%
        self.assertFalse(
            klints_net_ltv_matches_shopify_net(stamped=100.0, shopify_net=50.0)
        )
        self.assertFalse(
            klints_net_ltv_matches_shopify_net(stamped=None, shopify_net=60.0)
        )


class ProductTruthGovernedTests(SimpleTestCase):
    def _shopify(self):
        return {
            "customers": [{"id": 101, "email": "a@x.com"}],
            "orders": [
                {
                    "id": 1,
                    "customer": {"id": 101, "email": "a@x.com"},
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

    def _manago(self, *, properties=None, properties_list=None):
        contact = {
            "contactId": "m1",
            "externalId": "101",
            "email": "a@x.com",
        }
        if properties is not None:
            contact["properties"] = properties
        if properties_list is not None:
            contact["properties"] = properties_list
        return {
            "contacts": [contact],
            "transactions": [
                {
                    "contactExtEventType": "PURCHASE",
                    "contactId": "m1",
                    "externalId": "1",
                    "value": 100,
                },
            ],
        }

    def test_no_stamp_still_fail(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return self._shopify()
            return self._manago()

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        truth = payload["product_truth"]
        row = payload["product_truth_rows"][0]
        self.assertFalse(row["governed_by_klints_net_ltv"])
        self.assertEqual(truth["contacts_over_delta"], 1)
        self.assertEqual(truth["contacts_refund_blind"], 1)
        self.assertEqual(truth["contacts_governed_by_klints_net_ltv"], 0)

    def test_stamp_matches_net_governs_pass_path(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return self._shopify()
            return self._manago(properties={"klints_net_ltv": "60"})

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        truth = payload["product_truth"]
        row = payload["product_truth_rows"][0]
        self.assertTrue(row["governed_by_klints_net_ltv"])
        self.assertEqual(row["klints_net_ltv"], 60.0)
        self.assertFalse(row["refund_blind"])
        self.assertEqual(row["overstatement"], 0.0)
        self.assertEqual(truth["contacts_over_delta"], 0)
        self.assertEqual(truth["contacts_refund_blind"], 0)
        self.assertEqual(truth["contacts_governed_by_klints_net_ltv"], 1)
        self.assertEqual(truth["total_overstatement"], 0.0)

        result = evaluate_pt_04(
            _ctx(
                {
                    "connectors": {
                        "shopify": {"status": "connected"},
                        "manago_ai": {"status": "connected"},
                    },
                    "product_truth": truth,
                }
            )
        )
        self.assertEqual(result.status, "PASS")
        self.assertIn("klints_net_ltv", result.message or "")
        self.assertEqual(
            result.evidence[0].value.get("contacts_governed_by_klints_net_ltv"), 1
        )
        self.assertEqual(result.provenance.get("mismatches"), [])

    def test_name_value_list_bag(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return self._shopify()
            return self._manago(
                properties_list=[{"name": "klints_net_ltv", "value": 60.0}]
            )

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        self.assertTrue(payload["product_truth_rows"][0]["governed_by_klints_net_ltv"])

    def test_wrong_stamp_still_fail(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return self._shopify()
            return self._manago(properties={"klints_net_ltv": 10})

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        truth = payload["product_truth"]
        self.assertEqual(truth["contacts_over_delta"], 1)
        self.assertFalse(payload["product_truth_rows"][0]["governed_by_klints_net_ltv"])

    def test_partial_governed_mix(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return {
                    "customers": [
                        {"id": 101, "email": "a@x.com"},
                        {"id": 102, "email": "b@x.com"},
                    ],
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
                            "customer": {"id": 102},
                            "financial_status": "paid",
                            "total_price": "50.00",
                            "test": False,
                        },
                    ],
                }
            return {
                "contacts": [
                    {
                        "contactId": "m1",
                        "externalId": "101",
                        "email": "a@x.com",
                        "properties": {"klints_net_ltv": 100},
                    },
                    {
                        "contactId": "m2",
                        "externalId": "102",
                        "email": "b@x.com",
                    },
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "o1",
                        "value": 200,
                    },
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m2",
                        "externalId": "o2",
                        "value": 80,
                    },
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        truth = payload["product_truth"]
        self.assertEqual(truth["linked_contacts"], 2)
        self.assertEqual(truth["contacts_governed_by_klints_net_ltv"], 1)
        self.assertEqual(truth["contacts_over_delta"], 1)
        result = evaluate_pt_04(
            _ctx(
                {
                    "connectors": {
                        "shopify": {"status": "connected"},
                        "manago_ai": {"status": "connected"},
                    },
                    "product_truth": truth,
                }
            )
        )
        self.assertEqual(result.status, "FAIL")
        mids = {
            m.get("manago_contact_id") for m in result.provenance.get("mismatches") or []
        }
        self.assertIn("m2", mids)
        self.assertNotIn("m1", mids)

    def test_case_insensitive_property_name(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return self._shopify()
            return self._manago(
                properties_list=[{"name": "Klints_Net_Ltv", "value": "60"}]
            )

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        self.assertTrue(payload["product_truth_rows"][0]["governed_by_klints_net_ltv"])

    def test_empty_string_stamp_not_governed(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform, **_kwargs):
            if platform == "shopify":
                return self._shopify()
            return self._manago(properties={"klints_net_ltv": ""})

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        self.assertFalse(payload["product_truth_rows"][0]["governed_by_klints_net_ltv"])
        self.assertEqual(payload["product_truth"]["contacts_over_delta"], 1)

    def test_understated_purchase_governed(self):
        """Matching stamp clears FAIL even when purchase understates net."""
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
                        "properties": {"klints_net_ltv": 100},
                    }
                ],
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "contactId": "m1",
                        "externalId": "o1",
                        "value": 10,
                    }
                ],
            }

        with patch(
            "dataruns.dcs.product_truth._connector_raw_for_platform",
            side_effect=fake_raw,
        ):
            payload = build_product_truth_snapshot(company=company)
        row = payload["product_truth_rows"][0]
        self.assertTrue(row["governed_by_klints_net_ltv"])
        self.assertEqual(payload["product_truth"]["contacts_over_delta"], 0)


class EvaluatePt04GovernedMismatchGuardTests(SimpleTestCase):
    def test_mismatch_rows_skip_governed_leak(self):
        from dataruns.dcs.executors.product import _pt04_mismatch_rows

        rows = _pt04_mismatch_rows(
            [
                {
                    "manago_contact_id": "g1",
                    "shopify_net": 60,
                    "governed_by_klints_net_ltv": True,
                    "overstatement": 0,
                },
                {
                    "manago_contact_id": "f1",
                    "shopify_net": 50,
                    "governed_by_klints_net_ltv": False,
                    "overstatement": 10,
                },
            ],
            [],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["manago_contact_id"], "f1")

    def test_fail_detail_includes_governed_count(self):
        result = evaluate_pt_04(
            _ctx(
                {
                    "connectors": {
                        "shopify": {"status": "connected"},
                        "manago_ai": {"status": "connected"},
                    },
                    "product_truth": {
                        "linked_contacts": 3,
                        "contacts_over_delta": 1,
                        "contacts_refund_blind": 0,
                        "contacts_governed_by_klints_net_ltv": 2,
                        "total_overstatement": 10.0,
                        "fail_delta": 0.02,
                        "failing_sample": [
                            {
                                "manago_contact_id": "m2",
                                "shopify_net": 50,
                                "overstatement": 10,
                            }
                        ],
                        "refund_blind_sample": [],
                        "raw_enrichment": {
                            "shopify_from_raw": True,
                            "manago_from_raw": True,
                        },
                    },
                }
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertIn("governed=2", result.message or "")
