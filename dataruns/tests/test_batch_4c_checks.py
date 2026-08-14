"""Batch 4c RULE checks: PT-01/03, SP-03/07, ME-02, BR-01 (Excel sheet 02)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from dataruns.dcs.catalog_join import build_catalog_snapshot
from dataruns.dcs.executors.business import evaluate_br_01
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.measurement import evaluate_me_02
from dataruns.dcs.executors.product import evaluate_pt_01, evaluate_pt_03
from dataruns.dcs.executors.registry import registered_check_ids
from dataruns.dcs.executors.segment import evaluate_sp_03, evaluate_sp_07
from dataruns.dcs.segment_join import build_segment_snapshot


def _ctx(snapshot: dict, *, erp_in_scope: bool = False) -> FoundationGateContext:
    return FoundationGateContext(
        tenant_id="t1",
        run_id="r1",
        evaluated_at="2026-07-31T12:00:00Z",
        erp_in_scope=erp_in_scope,
        extra={"scoring_snapshot": snapshot},
    )


def _base_snap(**overrides) -> dict:
    snap = {
        "connectors": {
            "shopify": {"status": "connected"},
            "manago_ai": {"status": "connected"},
            "erp": {"status": "not_connected"},
        },
        "catalog": {
            "manago_catalog_available": False,
            "manago_catalog_count": 0,
            "shopify_products_from_line_items": 2,
            "shopify_variants_from_line_items": 3,
            "unique_event_product_ids": 2,
            "dangling_count": 0,
            "dangling_rate": 0.0,
            "resolve_target": "shopify_variants",
            "dangling_sample": [],
            "pt03": {
                "shopify_active_count": 2,
                "manago_catalog_count": 0,
                "missing_in_manago": 0,
                "surplus_in_manago": 0,
                "attribute_empty": 0,
                "missing_sample": [],
                "surplus_sample": [],
            },
            "raw_enrichment": {
                "shopify_line_items_present": True,
                "manago_event_products_present": True,
                "manago_catalog_present": False,
            },
        },
        "segment": {
            "contacts_scanned": 5,
            "contacts_with_details": 2,
            "contacts_with_tags": 0,
            "detail_key_count": 3,
            "tag_count": 0,
            "inconsistent_keys": 0,
            "inconsistent_sample": [],
            "klints_detail_collisions": [],
            "klints_tag_collisions": [],
            "klints_collision_count": 0,
            "raw_enrichment": {
                "manago_contacts_from_raw": True,
                "details_present": True,
                "tags_present": False,
            },
        },
        "measurement": {
            "workflows_available": False,
            "live_workflow_count": 0,
            "with_purchase_linkage": 0,
            "zero_outcome_path": 0,
            "funnel_membership_ids_seen": 0,
            "raw_enrichment": {
                "workflow_definitions_present": False,
                "workflow_analytics_present": False,
            },
        },
    }
    for key, value in overrides.items():
        if key in snap and isinstance(snap[key], dict) and isinstance(value, dict):
            merged = dict(snap[key])
            merged.update(value)
            snap[key] = merged
        else:
            snap[key] = value
    return snap


class Registry4cTests(SimpleTestCase):
    def test_all_4c_ids_registered(self):
        ids = registered_check_ids()
        for check_id in ("PT-01", "PT-03", "SP-03", "SP-07", "ME-02", "BR-01"):
            self.assertIn(check_id, ids)


class EvaluatePt01Tests(SimpleTestCase):
    def test_pass_when_all_resolve(self):
        self.assertEqual(evaluate_pt_01(_ctx(_base_snap())).status, "PASS")

    def test_fail_dangling(self):
        result = evaluate_pt_01(
            _ctx(
                _base_snap(
                    catalog={
                        "dangling_count": 1,
                        "dangling_rate": 0.5,
                        "unique_event_product_ids": 2,
                        "dangling_sample": [{"product_id": "x", "ref_count": 2}],
                        "raw_enrichment": {
                            "shopify_line_items_present": True,
                            "manago_event_products_present": True,
                            "manago_catalog_present": False,
                        },
                        "shopify_variants_from_line_items": 3,
                        "resolve_target": "shopify_variants",
                        "manago_catalog_available": False,
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-02")


class EvaluatePt03Tests(SimpleTestCase):
    def test_unknown_without_manago_catalog(self):
        result = evaluate_pt_03(_ctx(_base_snap()))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:manago_product_catalog")

    def test_fail_missing_in_manago(self):
        result = evaluate_pt_03(
            _ctx(
                _base_snap(
                    catalog={
                        "manago_catalog_available": True,
                        "pt03": {
                            "shopify_active_count": 2,
                            "manago_catalog_count": 1,
                            "missing_in_manago": 1,
                            "surplus_in_manago": 0,
                            "attribute_empty": 0,
                            "missing_sample": ["2"],
                            "surplus_sample": [],
                        },
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-01")


class EvaluateSp03Tests(SimpleTestCase):
    def test_fail_inconsistent_formats(self):
        result = evaluate_sp_03(
            _ctx(
                _base_snap(
                    segment={
                        "detail_key_count": 2,
                        "inconsistent_keys": 1,
                        "inconsistent_sample": [
                            {
                                "key": "ORDER_AVG",
                                "format_distribution": {"numeric": 1, "text": 1},
                                "samples": ["10", "ten"],
                            }
                        ],
                        "raw_enrichment": {
                            "manago_contacts_from_raw": True,
                            "details_present": True,
                            "tags_present": False,
                        },
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-06")

    def test_pass_consistent(self):
        self.assertEqual(evaluate_sp_03(_ctx(_base_snap())).status, "PASS")


class EvaluateSp07Tests(SimpleTestCase):
    def test_pass_clean_namespace(self):
        self.assertEqual(evaluate_sp_07(_ctx(_base_snap())).status, "PASS")

    def test_fail_collision(self):
        result = evaluate_sp_07(
            _ctx(
                _base_snap(
                    segment={
                        "klints_collision_count": 1,
                        "klints_detail_collisions": ["klints_net_ltv"],
                        "klints_tag_collisions": [],
                        "raw_enrichment": {
                            "manago_contacts_from_raw": True,
                            "details_present": True,
                            "tags_present": False,
                        },
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-04")


class EvaluateMe02Tests(SimpleTestCase):
    def test_unknown_without_workflows(self):
        result = evaluate_me_02(_ctx(_base_snap()))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:workflows")

    def test_fail_unwired_analytics(self):
        result = evaluate_me_02(
            _ctx(
                _base_snap(
                    measurement={
                        "workflows_available": True,
                        "live_workflow_count": 2,
                        "with_purchase_linkage": 1,
                        "zero_outcome_path": 1,
                        "zero_outcome_sample": [
                            {"externalId": "w1", "name": "Cart", "reason": "no_analytics"}
                        ],
                    }
                )
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-12")

    def test_pass_all_wired(self):
        result = evaluate_me_02(
            _ctx(
                _base_snap(
                    measurement={
                        "workflows_available": True,
                        "live_workflow_count": 2,
                        "with_purchase_linkage": 2,
                        "zero_outcome_path": 0,
                        "zero_outcome_sample": [],
                    }
                )
            )
        )
        self.assertEqual(result.status, "PASS")


class EvaluateBr01Tests(SimpleTestCase):
    def test_not_connected_without_erp(self):
        result = evaluate_br_01(_ctx(_base_snap(), erp_in_scope=False))
        self.assertEqual(result.status, "NOT_CONNECTED")
        self.assertEqual(result.reason_code, "ERP_OUT_OF_SCOPE")

    def test_fail_low_margin_share_when_erp_and_catalog(self):
        result = evaluate_br_01(
            _ctx(
                {
                    **_base_snap(
                        catalog={
                            "manago_catalog_available": True,
                            "margin": {
                                "manago_products": 10,
                                "margin_populated": 2,
                                "margin_unknown": 8,
                                "margin_share": 0.2,
                            },
                        }
                    ),
                    "connectors": {
                        "shopify": {"status": "connected"},
                        "manago_ai": {"status": "connected"},
                        "erp": {"status": "connected"},
                    },
                },
                erp_in_scope=True,
            )
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-01")


class CatalogJoinUnitTests(SimpleTestCase):
    def test_resolve_event_products_against_shopify_variants(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform):
            if platform == "shopify":
                return {
                    "products": [
                        {
                            "id": 1,
                            "title": "A",
                            "status": "active",
                            "variants": [{"id": 100, "sku": "A", "title": "Default"}],
                        }
                    ],
                    "orders": [],
                }
            return {
                "transactions": [
                    {
                        "contactExtEventType": "PURCHASE",
                        "products": "100,999",
                        "eventId": "e1",
                    }
                ],
                "events": [],
                "products": [],
                "product_catalogs": [],
            }

        with patch(
            "dataruns.dcs.catalog_join._latest_connector_raw", side_effect=fake_raw
        ):
            payload = build_catalog_snapshot(company=company)
        cat = payload["catalog"]
        self.assertEqual(cat["dangling_count"], 1)
        self.assertEqual(cat["dangling_sample"][0]["product_id"], "999")
        self.assertEqual(cat["resolve_target"], "shopify_variants")
        self.assertTrue(cat["shopify_products_from_api"])

    def test_pt03_with_manago_xml_products(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform):
            if platform == "shopify":
                return {
                    "products": [
                        {"id": 1, "title": "A", "status": "active", "variants": []},
                        {"id": 2, "title": "B", "status": "active", "variants": []},
                    ],
                    "orders": [],
                }
            return {
                "transactions": [],
                "events": [],
                "product_catalogs": [{"catalogId": "c1", "location": "shop"}],
                "products": [
                    {"productId": "1", "name": "A", "sku": "A"},
                    # product 2 missing → missing_in_manago
                ],
            }

        with patch(
            "dataruns.dcs.catalog_join._latest_connector_raw", side_effect=fake_raw
        ):
            payload = build_catalog_snapshot(company=company)
        cat = payload["catalog"]
        self.assertTrue(cat["manago_catalog_available"])
        self.assertEqual(cat["pt03"]["missing_in_manago"], 1)
        self.assertEqual(cat["pt03"]["missing_sample"][0], "2")


class SegmentJoinUnitTests(SimpleTestCase):
    def test_detect_klints_collision_and_mixed_formats(self):
        company = SimpleNamespace(id="c1")

        def fake_raw(*, company, platform):
            return {
                "contacts": [
                    {
                        "properties": [
                            {"name": "ORDER_AVG", "value": "10"},
                            {"name": "klints_net_ltv", "value": "1"},
                            {"name": "orderAvg", "value": "11"},
                        ],
                        "contactTags": [{"name": "vip"}],
                    },
                    {
                        "properties": [{"name": "ORDER_AVG", "value": "ten"}],
                        "contactTags": [],
                    },
                ]
            }

        with patch(
            "dataruns.dcs.segment_join._latest_connector_raw", side_effect=fake_raw
        ):
            payload = build_segment_snapshot(company=company)
        seg = payload["segment"]
        self.assertEqual(seg["inconsistent_keys"], 1)
        self.assertGreaterEqual(seg["semantic_duplicate_groups"], 1)
        self.assertEqual(seg["klints_collision_count"], 1)
        self.assertIn("klints_net_ltv", seg["klints_detail_collisions"])