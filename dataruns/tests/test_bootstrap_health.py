"""Tests for Shopify bootstrap scope capability validation."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.connectors.bootstrap_health import (
    build_preflight_section,
    compute_summary_status,
    missing_shopify_scopes,
    parse_shopify_scopes,
    postflight_health,
    shopify_admin_scope_satisfied,
)


class ShopifyScopeCapabilityTests(SimpleTestCase):
    def test_legacy_read_handles_still_satisfy_capabilities(self):
        granted = parse_shopify_scopes("read_customers,read_orders,read_products")
        missing_required, missing_recommended = missing_shopify_scopes(granted)
        self.assertEqual(missing_required, [])
        self.assertEqual(missing_recommended, [])

    def test_customers_and_orders_only_have_no_recommended_missing(self):
        granted = parse_shopify_scopes("read_customers,read_orders")
        missing_required, missing_recommended = missing_shopify_scopes(granted)
        self.assertEqual(missing_required, [])
        self.assertEqual(missing_recommended, [])

    def test_write_handles_satisfy_admin_capabilities(self):
        granted = parse_shopify_scopes(
            "write_customers,write_orders,write_products,write_inventory"
        )
        missing_required, missing_recommended = missing_shopify_scopes(granted)
        self.assertEqual(missing_required, [])
        self.assertEqual(missing_recommended, [])

    def test_partner_dashboard_scope_bundle_from_2026_oauth(self):
        granted = parse_shopify_scopes(
            "read_analytics,write_assigned_fulfillment_orders,read_customer_events,"
            "write_cart_transforms,read_all_cart_transforms,write_validations,"
            "write_checkouts,write_companies,write_customers,write_customer_merge,"
            "write_orders,customer_write_companies,customer_write_customers,"
            "customer_write_orders"
        )
        missing_required, missing_recommended = missing_shopify_scopes(granted)
        self.assertEqual(missing_required, [])
        self.assertEqual(missing_recommended, [])

    def test_customer_account_handles_do_not_satisfy_admin_orders(self):
        self.assertFalse(
            shopify_admin_scope_satisfied(
                {"customer_write_orders", "customer_write_customers"},
                "read_orders",
            )
        )
        self.assertFalse(
            shopify_admin_scope_satisfied(
                {"customer_write_orders", "customer_write_customers"},
                "read_customers",
            )
        )

    def test_build_preflight_section_reports_canonical_missing_scopes(self):
        config = {"scopes": "read_products"}
        preflight = build_preflight_section(
            platform="shopify",
            config=config,
            issues=[],
        )
        self.assertEqual(
            preflight["scopes_missing"],
            ["read_customers", "read_orders"],
        )


class PostflightEmptyWindowTests(SimpleTestCase):
    def test_manago_contacts_without_orders_is_ok(self):
        issues = postflight_health(
            platform="manago_ai",
            days=30,
            result={"counts": {"contacts": 15, "orders": 0}},
            snapshot_data={},
        )
        self.assertEqual(issues, [])
        self.assertEqual(compute_summary_status(import_succeeded=True, issues=issues), "ok")

    def test_manago_zero_contacts_still_warns(self):
        issues = postflight_health(
            platform="manago_ai",
            days=30,
            result={"counts": {"contacts": 0, "orders": 0}},
            snapshot_data={},
        )
        codes = [i["code"] for i in issues]
        self.assertIn("EMPTY_CONTACTS_WINDOW", codes)
        self.assertNotIn("EMPTY_ORDERS_WINDOW", codes)
        self.assertEqual(
            compute_summary_status(import_succeeded=True, issues=issues), "degraded"
        )

    def test_shopify_zero_orders_still_warns(self):
        issues = postflight_health(
            platform="shopify",
            days=30,
            result={"counts": {"contacts": 28, "orders": 0}},
            snapshot_data={},
        )
        codes = [i["code"] for i in issues]
        self.assertIn("EMPTY_ORDERS_WINDOW", codes)
        self.assertEqual(
            compute_summary_status(import_succeeded=True, issues=issues), "degraded"
        )
