"""Tests for Shopify bootstrap scope capability validation."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from dataruns.connectors.bootstrap_health import (
    build_latest_bootstrap_payload,
    build_preflight_section,
    compute_summary_status,
    missing_shopify_scopes,
    parse_shopify_scopes,
    postflight_health,
    recompute_health_report_summary,
    shopify_admin_scope_satisfied,
)
from dataruns.models import DataRun
from tenants.models import ConnectorSnapshot


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

    def test_shopify_exact_page_size_orders_not_partial_fetch(self):
        """Full pagination: exactly 250 orders is complete, not truncated."""
        orders = [{"id": i} for i in range(250)]
        issues = postflight_health(
            platform="shopify",
            days=30,
            result={"counts": {"contacts": 189, "orders": 250}},
            snapshot_data={"raw": {"customers": [{"id": 1}], "orders": orders}},
        )
        codes = [i["code"] for i in issues]
        self.assertNotIn("PARTIAL_FETCH", codes)
        self.assertEqual(compute_summary_status(import_succeeded=True, issues=issues), "ok")

    def test_partial_fetch_from_snapshot_notes_still_warns(self):
        issues = postflight_health(
            platform="shopify",
            days=30,
            result={"counts": {"contacts": 10, "orders": 10}},
            snapshot_data={
                "raw": {"customers": [{"id": 1}], "orders": [{"id": 1}]},
                "notes": ["Pagination truncated early"],
            },
        )
        codes = [i["code"] for i in issues]
        self.assertIn("PARTIAL_FETCH", codes)
        self.assertEqual(
            compute_summary_status(import_succeeded=True, issues=issues), "degraded"
        )


class StaleHealthReportRecomputeTests(TestCase):
    def setUp(self):
        from tenants.models import Company, Connector, Tenant

        self.tenant = Tenant.objects.create(name="Demo", slug="demo")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Demo",
            domain="demo.com",
        )
        self.connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "klints-dev.myshopify.com"},
            status="degraded",
        )

    def test_stale_partial_fetch_recomputed_ok_for_display(self):
        """Persisted PARTIAL_FETCH from retired heuristics must not degrade display."""
        snapshot = ConnectorSnapshot.objects.create(
            connector=self.connector,
            version=1,
            snapshot_data={
                "raw": {
                    "customers": [{"id": i} for i in range(189)],
                    "orders": [{"id": i} for i in range(250)],
                },
                "notes": [],
            },
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.SUCCEEDED,
            finished_at=timezone.now(),
            metadata={
                "connector": "shopify",
                "snapshot_id": str(snapshot.id),
                "counts": {"contacts": 189, "orders": 250},
                "health_report": {
                    "platform": "shopify",
                    "days": 30,
                    "summary_status": "degraded",
                    "preflight": {"issues": []},
                    "postflight": {
                        "issues": [
                            {
                                "code": "PARTIAL_FETCH",
                                "severity": "warn",
                                "message": "Order fetch reached Shopify pagination limit; additional pages may exist.",
                            }
                        ]
                    },
                    "fetch": {
                        "contacts_upserted": 189,
                        "orders_upserted": 250,
                    },
                },
            },
        )
        payload = build_latest_bootstrap_payload(data_run)
        self.assertEqual(payload["summary_status"], "ok")
        self.assertEqual(payload["issue_count"], 0)
        self.assertEqual(payload["contacts"], 189)
        self.assertEqual(payload["orders"], 250)

    def test_recompute_preserves_real_snapshot_note_partial_fetch(self):
        snapshot = ConnectorSnapshot.objects.create(
            connector=self.connector,
            version=2,
            snapshot_data={
                "raw": {"customers": [{"id": 1}], "orders": [{"id": 1}]},
                "notes": ["Pagination truncated early"],
            },
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="connector-bootstrap:shopify",
            status=DataRun.Status.SUCCEEDED,
            finished_at=timezone.now(),
            metadata={
                "connector": "shopify",
                "snapshot_id": str(snapshot.id),
                "counts": {"contacts": 10, "orders": 10},
                "health_report": {
                    "platform": "shopify",
                    "days": 30,
                    "summary_status": "ok",
                    "preflight": {"issues": []},
                    "postflight": {"issues": []},
                },
            },
        )
        refreshed = recompute_health_report_summary(
            data_run=data_run,
            health_report=data_run.metadata["health_report"],
        )
        codes = [i["code"] for i in refreshed["postflight"]["issues"]]
        self.assertIn("PARTIAL_FETCH", codes)
        self.assertEqual(refreshed["summary_status"], "degraded")
