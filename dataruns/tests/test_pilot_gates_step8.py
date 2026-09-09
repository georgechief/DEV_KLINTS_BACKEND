"""DCS-09 Step 8 — Slice B executors (remaining 10 supplemental gates)."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.executors.registry import registered_check_ids
from dataruns.dcs.pilot_gates.context import build_supplemental_gate_context
from dataruns.dcs.pilot_gates.contract import (
    SLICE_B_CHECK_IDS,
    STATUS_FAIL,
    STATUS_NOT_CONNECTED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    SUPPLEMENTAL_CHECK_IDS,
)
from dataruns.dcs.pilot_gates.executors import (
    REASON_ERP_OUT_OF_SCOPE,
    REASON_MISSING_INPUT,
    clear_supplemental_executor_registry,
    registered_supplemental_check_ids,
    run_supplemental_check,
    run_supplemental_checks,
)
from dataruns.dcs.pilot_gates.slice_b import (
    BR09_FAIL_MISSING_INPUT_SHARE,
    LE07_FAIL_CAPTURE_RATE,
    SP10_FAIL_MISSING_RFM_SHARE,
    evaluate_br03,
    evaluate_br09,
    evaluate_le07,
    evaluate_le10,
    evaluate_pt05,
    evaluate_pt06,
    evaluate_pt11,
    evaluate_pt13,
    evaluate_sp04,
    evaluate_sp10,
)
from dataruns.dcs.pilot_gates.store import save_pilot_gate_eval
from tenants.models import Company, Tenant


def _as_of() -> str:
    return "2026-06-01T00:00:00Z"


def _ctx(
    company: Company,
    *,
    gate_inputs: dict | None = None,
    manago_connected: bool = True,
    shopify_connected: bool = True,
    erp_in_scope: bool = False,
):
    snapshot: dict = {
        "as_of": _as_of(),
        "connectors": {
            "manago_ai": {
                "status": "connected" if manago_connected else "disconnected"
            },
            "shopify": {
                "status": "connected" if shopify_connected else "disconnected"
            },
        },
    }
    if gate_inputs is not None:
        snapshot["gate_inputs"] = gate_inputs
    return build_supplemental_gate_context(
        company=company,
        scoring_snapshot=snapshot,
        erp_in_scope=erp_in_scope,
    )


class PilotGatesStep8IsolationTests(SimpleTestCase):
    def test_slice_b_not_in_headline_registry(self):
        self.assertEqual(registered_check_ids() & set(SLICE_B_CHECK_IDS), set())

    def test_slice_b_covers_remaining_ten(self):
        self.assertEqual(len(SLICE_B_CHECK_IDS), 10)
        self.assertEqual(
            set(SUPPLEMENTAL_CHECK_IDS) - {"CI-08", "CC-06"},
            set(SLICE_B_CHECK_IDS),
        )


class PilotGatesStep8ExecutorTests(TestCase):
    def setUp(self):
        clear_supplemental_executor_registry()
        self.tenant = Tenant.objects.create(name="PG S8", slug="pg-s8")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="PG S8 Co",
            domain="pg-s8.example.com",
        )

    def tearDown(self):
        clear_supplemental_executor_registry()

    def test_slice_b_registered(self):
        self.assertTrue(SLICE_B_CHECK_IDS <= registered_supplemental_check_ids())
        self.assertEqual(
            registered_supplemental_check_ids(),
            set(SUPPLEMENTAL_CHECK_IDS),
        )

    def test_sp10_pass_and_fail(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {
                        "email": "a@ex.com",
                        "purchase_count": 2,
                        "rfm_segment": "Champions",
                    },
                    {"email": "b@ex.com", "purchase_count": 0},
                ]
            },
        )
        self.assertEqual(evaluate_sp10(pass_ctx).status, STATUS_PASS)

        fail_n = max(1, int(SP10_FAIL_MISSING_RFM_SHARE * 10) + 1)
        contacts = [
            {"email": f"p{i}@ex.com", "purchase_count": 1, "rfm_segment": "X"}
            for i in range(10 - fail_n)
        ] + [
            {"email": f"m{i}@ex.com", "purchase_count": 1}
            for i in range(fail_n)
        ]
        fail_ctx = _ctx(self.company, gate_inputs={"manago_contacts": contacts})
        result = evaluate_sp10(fail_ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertEqual(result.reason_code, "SP10_MISSING_RFM_SHARE")

    def test_sp10_unknown_and_not_connected(self):
        unknown = evaluate_sp10(_ctx(self.company))
        self.assertEqual(unknown.status, STATUS_UNKNOWN)
        self.assertTrue(str(unknown.reason_code).startswith(REASON_MISSING_INPUT))

        nc = evaluate_sp10(_ctx(self.company, manago_connected=False))
        self.assertEqual(nc.status, STATUS_NOT_CONNECTED)

    def test_pt13_pass_fail(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_coupons": [{"code": "SAVE10"}],
                "shopify_discount_codes": [
                    {"code": "SAVE10", "status": "active", "valid": True}
                ],
            },
        )
        self.assertEqual(evaluate_pt13(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_coupons": [{"code": "GONE"}],
                "shopify_discount_codes": [
                    {"code": "SAVE10", "status": "active", "valid": True}
                ],
            },
        )
        self.assertEqual(evaluate_pt13(fail_ctx).status, STATUS_FAIL)

    def test_le07_capture_rate(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "shopify_abandoned_checkouts": [
                    {"id": "1", "email": "a@ex.com"},
                    {"id": "2", "email": "b@ex.com"},
                ],
                "manago_cart_events": [
                    {"email": "a@ex.com", "type": "CART"},
                    {"email": "b@ex.com", "event_type": "CART"},
                ],
            },
        )
        self.assertEqual(evaluate_le07(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            gate_inputs={
                "shopify_abandoned_checkouts": [
                    {"id": str(i), "email": f"u{i}@ex.com"} for i in range(10)
                ],
                "manago_cart_events": [
                    {"email": "u0@ex.com", "type": "CART"},
                ],
            },
        )
        result = evaluate_le07(fail_ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertLess(LE07_FAIL_CAPTURE_RATE, 1.0)

    def test_le10_other_dump_and_type_changed(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_events": [
                    {"event_type": "PURCHASE"},
                    {"event_type": "CART"},
                    {"event_type": "VIEW"},
                    {"event_type": "OTHER"},
                ]
            },
        )
        self.assertEqual(evaluate_le10(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_events": [
                    {"event_type": "OTHER"},
                    {"event_type": "OTHER"},
                    {"event_type": "OTHER"},
                    {"event_type": "CART"},
                ]
            },
        )
        self.assertEqual(evaluate_le10(fail_ctx).status, STATUS_FAIL)

        changed = _ctx(
            self.company,
            gate_inputs={
                "manago_events": [
                    {"event_type": "PURCHASE", "type_changed": True},
                ]
            },
        )
        self.assertEqual(evaluate_le10(changed).status, STATUS_FAIL)

    def test_pt05_price_parity(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "price": 10.0}],
                "shopify_products": [{"product_id": "p1", "price": 10.0}],
            },
        )
        self.assertEqual(evaluate_pt05(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "price": 20.0}],
                "shopify_products": [{"product_id": "p1", "price": 10.0}],
            },
        )
        self.assertEqual(evaluate_pt05(fail_ctx).status, STATUS_FAIL)

    def test_pt06_erp_out_and_parity(self):
        out = run_supplemental_check(
            "PT-06",
            context=_ctx(self.company, erp_in_scope=False),
        )
        self.assertEqual(out.status, STATUS_NOT_CONNECTED)
        self.assertEqual(out.reason_code, REASON_ERP_OUT_OF_SCOPE)

        pass_ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "quantity": 5}],
                "shopify_inventory": [{"product_id": "p1", "quantity": 5}],
            },
        )
        self.assertEqual(evaluate_pt06(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "quantity": 5}],
                "shopify_inventory": [{"product_id": "p1", "quantity": 2}],
            },
        )
        self.assertEqual(evaluate_pt06(fail_ctx).status, STATUS_FAIL)

        missing = evaluate_pt06(_ctx(self.company, erp_in_scope=True))
        self.assertEqual(missing.status, STATUS_UNKNOWN)

    def test_pt11_attribute_coverage(self):
        complete = {
            "product_id": "p1",
            "category": "Shoes",
            "brand": "Acme",
            "image_url": "https://x/i.png",
            "product_url": "https://x/p",
        }
        pass_ctx = _ctx(
            self.company,
            gate_inputs={"manago_products": [complete]},
        )
        self.assertEqual(evaluate_pt11(pass_ctx).status, STATUS_PASS)

        incomplete = [{"product_id": f"p{i}"} for i in range(10)]
        fail_ctx = _ctx(
            self.company,
            gate_inputs={"manago_products": incomplete},
        )
        self.assertEqual(evaluate_pt11(fail_ctx).status, STATUS_FAIL)

    def test_br03_oos_on_active_surface(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "active_surface_products": [
                    {"product_id": "p1", "stock": 3, "surface": "collection"}
                ]
            },
        )
        self.assertEqual(evaluate_br03(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            gate_inputs={
                "active_surface_products": [
                    {"product_id": "p1", "stock": 0, "surface": "reco"}
                ]
            },
        )
        self.assertEqual(evaluate_br03(fail_ctx).status, STATUS_FAIL)

    def test_br09_erp_and_coverage(self):
        out = run_supplemental_check(
            "BR-09",
            context=_ctx(self.company, erp_in_scope=False),
        )
        self.assertEqual(out.status, STATUS_NOT_CONNECTED)
        self.assertEqual(out.reason_code, REASON_ERP_OUT_OF_SCOPE)

        pass_ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "replenishment_products": [
                    {
                        "product_id": "p1",
                        "pack_size": 2,
                        "consumption_days": 30,
                    }
                ]
            },
        )
        self.assertEqual(evaluate_br09(pass_ctx).status, STATUS_PASS)
        self.assertGreater(BR09_FAIL_MISSING_INPUT_SHARE, 0)

        fail_ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "replenishment_products": [
                    {"product_id": f"p{i}"} for i in range(10)
                ]
            },
        )
        self.assertEqual(evaluate_br09(fail_ctx).status, STATUS_FAIL)

    def test_sp04_date_details(self):
        pass_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {
                        "email": "a@ex.com",
                        "details": {"date.birthday": "1995-06-01"},
                    }
                ]
            },
        )
        self.assertEqual(evaluate_sp04(pass_ctx).status, STATUS_PASS)

        fail_ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {
                        "email": "a@ex.com",
                        "details": {"date.birthday": "not-a-date"},
                    }
                ]
            },
        )
        self.assertEqual(evaluate_sp04(fail_ctx).status, STATUS_FAIL)

    def test_le07_capture_uses_unique_email_match(self):
        # Many duplicate CART events for one email must not inflate capture_rate.
        ctx = _ctx(
            self.company,
            gate_inputs={
                "shopify_abandoned_checkouts": [
                    {"id": "1", "email": "a@ex.com"},
                    {"id": "2", "email": "b@ex.com"},
                ],
                "manago_cart_events": [
                    {"email": "a@ex.com", "type": "CART"},
                    {"email": "a@ex.com", "type": "CART"},
                    {"email": "a@ex.com", "type": "CART"},
                    {"email": "a@ex.com", "type": "CART"},
                    {"email": "a@ex.com", "type": "CART"},
                ],
            },
        )
        result = evaluate_le07(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        summary = result.evidence[0].value if result.evidence else {}
        self.assertEqual(summary.get("matched_emails"), 1)
        self.assertEqual(summary.get("capture_rate"), 0.5)

    def test_pt05_unknown_when_no_join(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "price": 10.0}],
                "shopify_products": [{"product_id": "other", "price": 10.0}],
            },
        )
        result = evaluate_pt05(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("price_join", str(result.reason_code))

    def test_pt06_unknown_when_no_join(self):
        ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "quantity": 5}],
                "shopify_inventory": [{"product_id": "other", "quantity": 5}],
            },
        )
        result = evaluate_pt06(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("stock_join", str(result.reason_code))

    def test_sp04_unknown_when_no_date_fields(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [{"email": "a@ex.com", "details": {"name": "Ada"}}]
            },
        )
        result = evaluate_sp04(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("date_details", str(result.reason_code))

    def test_manago_only_not_connected_when_disconnected(self):
        ctx = _ctx(self.company, manago_connected=False)
        for check_id, evaluate in (
            ("LE-10", evaluate_le10),
            ("PT-11", evaluate_pt11),
            ("BR-03", evaluate_br03),
            ("SP-04", evaluate_sp04),
        ):
            with self.subTest(check_id=check_id):
                result = evaluate(ctx)
                self.assertEqual(result.status, STATUS_NOT_CONNECTED)

    def test_malformed_list_does_not_silent_pass(self):
        # Non-dict rows must not become authoritative empty → PASS.
        ctx = _ctx(
            self.company,
            gate_inputs={"manago_contacts": ["not-a-dict", 123]},
        )
        result = evaluate_sp10(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("manago_contacts", str(result.reason_code))

    def test_sp10_unknown_when_contacts_lack_purchase_history_fields(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {"email": "a@ex.com", "name": "Ada"},
                    {"email": "b@ex.com", "rfm_segment": "Champions"},
                ]
            },
        )
        result = evaluate_sp10(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("purchase_history", str(result.reason_code))

    def test_sp10_camelcase_has_purchase_history(self):
        # Manago camelCase flag must count as purchaser (not silent PASS).
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {"email": "a@ex.com", "hasPurchaseHistory": True},
                ]
            },
        )
        result = evaluate_sp10(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        self.assertEqual(result.reason_code, "SP10_MISSING_RFM_SHARE")
        summary = result.evidence[0].value if result.evidence else {}
        self.assertEqual(summary.get("purchasers"), 1)

    def test_pt13_not_connected_blames_missing_connector(self):
        # Shopify list missing + Shopify disconnected → shopify, not manago.
        shop_down = _ctx(
            self.company,
            shopify_connected=False,
            gate_inputs={"manago_coupons": [{"code": "A"}]},
        )
        r1 = evaluate_pt13(shop_down)
        self.assertEqual(r1.status, STATUS_NOT_CONNECTED)
        self.assertIn("shopify", str(r1.reason_code))

        # Manago list missing + Manago disconnected → manago.
        manago_down = _ctx(
            self.company,
            manago_connected=False,
            gate_inputs={"shopify_discount_codes": [{"code": "A", "valid": True}]},
        )
        r2 = evaluate_pt13(manago_down)
        self.assertEqual(r2.status, STATUS_NOT_CONNECTED)
        self.assertIn("manago", str(r2.reason_code))

    def test_le10_other_share_fail_includes_other_in_sample(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_events": [
                    {"id": "1", "event_type": "OTHER"},
                    {"id": "2", "event_type": "OTHER"},
                    {"id": "3", "event_type": "OTHER"},
                    {"id": "4", "event_type": "CART"},
                ]
            },
        )
        result = evaluate_le10(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        sample = result.evidence[1].value if len(result.evidence) > 1 else []
        self.assertTrue(any(row.get("event_type") == "OTHER" for row in sample))

    def test_le10_sample_prefers_type_changed_over_other_flood(self):
        events = [{"id": f"o{i}", "event_type": "OTHER"} for i in range(40)]
        events.append({"id": "tc1", "event_type": "CART", "type_changed": True})
        result = evaluate_le10(
            _ctx(self.company, gate_inputs={"manago_events": events})
        )
        self.assertEqual(result.status, STATUS_FAIL)
        sample = result.evidence[1].value if len(result.evidence) > 1 else []
        self.assertTrue(any(row.get("type_changed") is True for row in sample))

    def test_pt06_negative_qty_does_not_double_count_diff(self):
        ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "manago_products": [{"product_id": "p1", "quantity": -2}],
                "shopify_inventory": [{"product_id": "p1", "quantity": 5}],
            },
        )
        result = evaluate_pt06(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        sample = result.evidence[1].value if len(result.evidence) > 1 else []
        reasons = [row.get("reason") for row in sample]
        self.assertIn("negative_manago_qty", reasons)
        self.assertNotIn("qty_diff", reasons)

    def test_sp04_non_date_details_keys_skipped(self):
        # Non date.* keys in date_details must not false-FAIL SP-04.
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {
                        "email": "a@ex.com",
                        "details": {"date.birthday": "1995-06-01"},
                        "date_details": [
                            {"key": "name", "value": "not-a-date"},
                            {"key": "date.next", "value": "2030-01-01"},
                        ],
                    }
                ]
            },
        )
        self.assertEqual(evaluate_sp04(ctx).status, STATUS_PASS)

    def test_br03_missing_stock_is_unknown(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "active_surface_products": [
                    {"product_id": "p1", "surface": "reco"},
                ]
            },
        )
        result = evaluate_br03(ctx)
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("stock", str(result.reason_code))

    def test_br03_evidence_includes_oos_and_missing(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "active_surface_products": [
                    {"product_id": "oos1", "stock": 0, "surface": "c"},
                    {"product_id": "miss1", "surface": "c"},
                ]
            },
        )
        result = evaluate_br03(ctx)
        self.assertEqual(result.status, STATUS_FAIL)
        sample = result.evidence[1].value if len(result.evidence) > 1 else []
        ids = {row.get("product_id") for row in sample}
        self.assertIn("oos1", ids)
        self.assertIn("miss1", ids)

    def test_br09_unknown_when_erp_in_scope_missing_input(self):
        result = evaluate_br09(_ctx(self.company, erp_in_scope=True))
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertTrue(str(result.reason_code).startswith(REASON_MISSING_INPUT))

    def test_slice_b_executors_map_locked(self):
        from dataruns.dcs.pilot_gates.slice_b import SLICE_B_EXECUTORS

        self.assertEqual(set(SLICE_B_EXECUTORS), set(SLICE_B_CHECK_IDS))

    def test_registry_run_matches_direct(self):
        ctx = _ctx(
            self.company,
            gate_inputs={
                "manago_contacts": [
                    {
                        "email": "a@ex.com",
                        "purchase_count": 1,
                        "rfm_segment": "Loyal",
                    }
                ]
            },
        )
        direct = evaluate_sp10(ctx)
        via = run_supplemental_check("SP-10", context=ctx)
        self.assertEqual(direct.status, via.status)
        self.assertEqual(direct.reason_code, via.reason_code)

    def test_run_slice_b_and_persist(self):
        ctx = _ctx(
            self.company,
            erp_in_scope=True,
            gate_inputs={
                "manago_contacts": [
                    {
                        "email": "a@ex.com",
                        "purchase_count": 1,
                        "rfm_segment": "X",
                        "details": {"date.next": "2030-01-01"},
                    }
                ],
                "manago_coupons": [{"code": "A"}],
                "shopify_discount_codes": [
                    {"code": "A", "valid": True, "status": "active"}
                ],
                "shopify_abandoned_checkouts": [{"id": "1", "email": "a@ex.com"}],
                "manago_cart_events": [{"email": "a@ex.com", "type": "CART"}],
                "manago_events": [{"event_type": "PURCHASE"}],
                "manago_products": [
                    {
                        "product_id": "p1",
                        "price": 10,
                        "quantity": 1,
                        "category": "c",
                        "brand": "b",
                        "image_url": "https://i",
                        "product_url": "https://p",
                    }
                ],
                "shopify_products": [{"product_id": "p1", "price": 10}],
                "shopify_inventory": [{"product_id": "p1", "quantity": 1}],
                "active_surface_products": [
                    {"product_id": "p1", "stock": 1, "surface": "c"}
                ],
                "replenishment_products": [
                    {
                        "product_id": "p1",
                        "pack_size": 1,
                        "consumption_days": 7,
                    }
                ],
            },
        )
        results = run_supplemental_checks(list(SLICE_B_CHECK_IDS), context=ctx)
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r.status == STATUS_PASS for r in results))
        from dataruns.dcs.pilot_gates.executors import check_result_to_store_row

        bundle = save_pilot_gate_eval(
            company=self.company,
            results=[check_result_to_store_row(r) for r in results],
            erp_in_scope=True,
            merge_with_previous=False,
        )
        self.assertEqual(set(bundle.status_by_check_id), set(SLICE_B_CHECK_IDS))
        self.assertTrue(all(v == "PASS" for v in bundle.status_by_check_id.values()))
