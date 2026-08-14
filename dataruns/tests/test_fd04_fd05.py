"""FD-04 rate headroom and FD-05 history depth tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.executors.foundation import (
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_fd_04,
    evaluate_fd_05,
)
from dataruns.dcs.history_depth import (
    compute_history_depth,
    shortest_common_window_days,
)
from dataruns.dcs.rate_budget import (
    budget_has_headroom,
    build_manago_rate_budget,
    parse_shopify_call_limit,
    shopify_call_limit_from_headers,
)
from dataruns.models import Contact, Order
from tenants.models import Company, Tenant


class RateBudgetUnitTests(SimpleTestCase):
    def test_parse_shopify_call_limit(self):
        parsed = parse_shopify_call_limit("32/40")
        self.assertEqual(parsed, {"used": 32, "limit": 40, "remaining": 8})

    def test_headers_case_insensitive(self):
        parsed = shopify_call_limit_from_headers(
            {"X-Shopify-Shop-Api-Call-Limit": "39/40"}
        )
        self.assertEqual(parsed["remaining"], 1)

    def test_manago_budget_headroom(self):
        budget = build_manago_rate_budget(
            requests_sampled=3,
            requests_ok=3,
            hit_rate_limit=False,
        )
        self.assertTrue(budget_has_headroom(budget))
        failed = build_manago_rate_budget(
            requests_sampled=2,
            requests_ok=1,
            hit_rate_limit=True,
        )
        self.assertFalse(budget_has_headroom(failed))


class EvaluateFd04Tests(SimpleTestCase):
    def test_pass_with_measured_budgets(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                rate_budget=build_manago_rate_budget(
                    requests_sampled=3,
                    requests_ok=3,
                    hit_rate_limit=False,
                    source="probe",
                ),
            ),
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                rate_budget={
                    "platform": "shopify",
                    "used": 10,
                    "limit": 40,
                    "remaining": 30,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "header",
                },
            ),
        )
        result = evaluate_fd_04(ctx)
        self.assertEqual(result.status, "PASS")

    def test_fail_on_rate_limit_issue(self):
        ctx = FoundationGateContext(
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                health_report={
                    "postflight": {
                        "issues": [{"code": "RATE_LIMIT", "severity": "error"}]
                    }
                },
                rate_budget={
                    "platform": "shopify",
                    "remaining": 0,
                    "hit_rate_limit": True,
                    "headroom_ok": False,
                },
            ),
        )
        result = evaluate_fd_04(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-15")

    def test_unknown_without_budget(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                health_report={"summary_status": "ok", "days": 30},
            ),
        )
        result = evaluate_fd_04(ctx)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:rate_budget")

    def test_does_not_pass_on_health_report_alone(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                health_report={"summary_status": "ok"},
            ),
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                health_report={"summary_status": "ok"},
            ),
        )
        result = evaluate_fd_04(ctx)
        self.assertEqual(result.status, "UNKNOWN")


class EvaluateFd05Tests(SimpleTestCase):
    def test_pass_from_entity_depth(self):
        ctx = FoundationGateContext(
            bootstrap_days_required=30,
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                history_earliest={"orders": "2026-01-01T00:00:00Z"},
            ),
            extra={
                "history_depth": {
                    "platforms": {
                        "manago_ai": {
                            "platform": "manago_ai",
                            "depth_days": 40,
                            "meets_required": True,
                            "earliest": {"orders": "2026-01-01T00:00:00Z"},
                        }
                    },
                    "common_window_days": 40,
                }
            },
        )
        result = evaluate_fd_05(ctx)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.confidence, "HIGH")

    def test_fail_when_depth_too_shallow(self):
        ctx = FoundationGateContext(
            bootstrap_days_required=30,
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                history_earliest={"orders": "2026-07-20T00:00:00Z"},
                health_report={"summary_status": "ok", "days": 7},
            ),
            extra={
                "history_depth": {
                    "platforms": {
                        "shopify": {
                            "platform": "shopify",
                            "depth_days": 7,
                            "meets_required": False,
                            "earliest": {"orders": "2026-07-20T00:00:00Z"},
                        }
                    },
                    "common_window_days": 7,
                }
            },
        )
        result = evaluate_fd_05(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-09")

    def test_bootstrap_fallback_pass_medium_confidence(self):
        ctx = FoundationGateContext(
            bootstrap_days_required=30,
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                health_report={"summary_status": "ok", "days": 30},
            ),
        )
        result = evaluate_fd_05(ctx)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.confidence, "MEDIUM")


class HistoryDepthDbTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="FD05 Tenant", slug="fd05-tenant")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="FD05 Co",
            domain="fd05.example",
        )

    def test_compute_history_depth_from_orders(self):
        contact = Contact.objects.create(
            company=self.company,
            source="shopify",
            external_id="c1",
            email="a@example.com",
        )
        old = datetime.now(timezone.utc) - timedelta(days=45)
        order = Order.objects.create(
            company=self.company,
            contact=contact,
            source="shopify",
            external_id="o1",
            amount="10.00",
            currency="EUR",
            status="paid",
        )
        Order.objects.filter(pk=order.pk).update(created_at=old)

        depth = compute_history_depth(
            company=self.company,
            platform="shopify",
            required_days=30,
        )
        self.assertTrue(depth["meets_required"])
        self.assertGreaterEqual(depth["depth_days"], 30)
        self.assertIn("orders", depth["earliest"])
        self.assertEqual(
            shortest_common_window_days([depth, {**depth, "depth_days": 20}]),
            20,
        )


class BuildFetchSectionRateBudgetTests(SimpleTestCase):
    def test_fetch_section_includes_rate_budget(self):
        from dataruns.connectors.bootstrap_health import build_fetch_section

        fetch = build_fetch_section(
            result={
                "connector": "shopify",
                "counts": {"contacts": 1, "orders": 2},
                "rate_budget": {
                    "platform": "shopify",
                    "remaining": 20,
                    "headroom_ok": True,
                },
            },
            snapshot_data={"platform": "shopify", "raw": {}},
            duration_ms=100,
            import_succeeded=True,
        )
        self.assertEqual(fetch["rate_budget"]["remaining"], 20)
