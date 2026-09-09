"""CAP-01 Step 4 — package route / capability_resolution resolver."""

from __future__ import annotations

from copy import deepcopy

from django.test import SimpleTestCase

from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
    PACKAGE_ROUTE_MCP,
    RESOLVED_HUMAN_FALLBACK,
    RESOLVED_MCP,
    RESOLVED_NOT_CONFIRMED,
)
from dataruns.capabilities.registry import clear_matrix_registry_cache, get_capability
from dataruns.capabilities.resolver import (
    resolve_blueprint_capabilities,
    resolve_capabilities,
    resolve_dependency,
    resolve_package_route,
)

UC02_DEPS = [
    {
        "capability_id": "AGENT.SEGMENT.CREATE",
        "required_status": "CONFIRMED_LIVE",
        "fallback": None,
    },
    {
        "capability_id": "AGENT.EMAIL.DRAFT",
        "required_status": "CONFIRMED_LIVE",
        "fallback": None,
    },
    {
        "capability_id": CAP_ID_MCP_WORKFLOW_UPSERT,
        "required_status": "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
        "fallback": CAP_ID_HUMAN_WORKFLOW_BUILD,
    },
]


class Cap01ResolverStep4Tests(SimpleTestCase):
    def setUp(self):
        clear_matrix_registry_cache()

    def tearDown(self):
        clear_matrix_registry_cache()

    def test_stock_seed_uc02_route_human_fallback(self):
        outcome = resolve_blueprint_capabilities({"capability_dependencies": UC02_DEPS})
        self.assertEqual(outcome.route, PACKAGE_ROUTE_HUMAN_FALLBACK)
        by_id = {r["capability_id"]: r for r in outcome.capability_resolution}
        upsert = by_id[CAP_ID_MCP_WORKFLOW_UPSERT]
        self.assertEqual(upsert["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(upsert["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)
        self.assertEqual(upsert["matrix_status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(upsert["channel"], "MANAGO_MCP")

    def test_stock_seed_agent_deps_pass_confirmed(self):
        rows = resolve_capabilities(UC02_DEPS)
        by_id = {r["capability_id"]: r for r in rows}
        for cap_id in ("AGENT.SEGMENT.CREATE", "AGENT.EMAIL.DRAFT"):
            self.assertEqual(by_id[cap_id]["resolved_status"], CAP_STATUS_CONFIRMED_LIVE)
            self.assertIsNone(by_id[cap_id]["fallback_used"])
            self.assertEqual(by_id[cap_id]["matrix_status"], CAP_STATUS_CONFIRMED_LIVE)

    def test_missing_capability_without_fallback_not_confirmed(self):
        row = resolve_dependency(
            {
                "capability_id": "MCP.DOES.NOT.EXIST",
                "required_status": "CONFIRMED_LIVE",
                "fallback": None,
            }
        )
        self.assertEqual(row["resolved_status"], RESOLVED_NOT_CONFIRMED)
        self.assertIsNone(row["fallback_used"])

    def test_missing_capability_with_fallback_human(self):
        row = resolve_dependency(
            {
                "capability_id": "MCP.DOES.NOT.EXIST",
                "required_status": "CONFIRMED_LIVE",
                "fallback": CAP_ID_HUMAN_WORKFLOW_BUILD,
            }
        )
        self.assertEqual(row["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(row["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)

    def test_upsert_without_dep_fallback_still_uses_human_build(self):
        row = resolve_dependency(
            {
                "capability_id": CAP_ID_MCP_WORKFLOW_UPSERT,
                "required_status": "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
                "fallback": None,
            }
        )
        self.assertEqual(row["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(row["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)

    def test_in_memory_upsert_confirmed_with_evidence_sets_route_mcp(self):
        stock = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        self.assertIsNotNone(stock)
        assert stock is not None
        fake = deepcopy(stock)
        fake["status"] = CAP_STATUS_CONFIRMED_LIVE
        fake["evidence"] = [
            {
                "source": "unit-test",
                "locator": "step4",
                "observed_at": "2026-08-26T00:00:00Z",
            }
        ]
        outcome = resolve_blueprint_capabilities(
            {"capability_dependencies": UC02_DEPS},
            overrides={CAP_ID_MCP_WORKFLOW_UPSERT: fake},
        )
        self.assertEqual(outcome.route, PACKAGE_ROUTE_MCP)
        upsert = next(
            r
            for r in outcome.capability_resolution
            if r["capability_id"] == CAP_ID_MCP_WORKFLOW_UPSERT
        )
        self.assertEqual(upsert["resolved_status"], RESOLVED_MCP)
        self.assertIsNone(upsert["fallback_used"])

    def test_confirmed_mcp_write_without_evidence_falls_back(self):
        stock = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        assert stock is not None
        fake = deepcopy(stock)
        fake["status"] = CAP_STATUS_CONFIRMED_LIVE
        fake["evidence"] = []
        row = resolve_dependency(
            {
                "capability_id": CAP_ID_MCP_WORKFLOW_UPSERT,
                "required_status": "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
                "fallback": CAP_ID_HUMAN_WORKFLOW_BUILD,
            },
            overrides={CAP_ID_MCP_WORKFLOW_UPSERT: fake},
        )
        self.assertEqual(row["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(resolve_package_route([row]), PACKAGE_ROUTE_HUMAN_FALLBACK)

    def test_resolve_package_route_without_upsert_is_human(self):
        rows = resolve_capabilities(
            [
                {
                    "capability_id": "AGENT.SEGMENT.CREATE",
                    "required_status": "CONFIRMED_LIVE",
                    "fallback": None,
                }
            ]
        )
        self.assertEqual(resolve_package_route(rows), PACKAGE_ROUTE_HUMAN_FALLBACK)

    def test_prose_matrix_fallback_not_used_as_id(self):
        # RESTV2.AUTH.VALIDATE fallback is prose "Block onboarding"
        row = resolve_dependency(
            {
                "capability_id": "RESTV2.AUTH.VALIDATE",
                "required_status": "CONFIRMED_LIVE",
                "fallback": None,
            }
        )
        # Confirmed live → pass through; no fallback_used
        self.assertEqual(row["resolved_status"], CAP_STATUS_CONFIRMED_LIVE)
        self.assertIsNone(row["fallback_used"])

    def test_empty_capability_id_not_confirmed(self):
        row = resolve_dependency(
            {"capability_id": "  ", "required_status": "CONFIRMED_LIVE", "fallback": None}
        )
        self.assertEqual(row["capability_id"], "")
        self.assertEqual(row["resolved_status"], RESOLVED_NOT_CONFIRMED)

    def test_empty_blueprint_body_route_human(self):
        outcome = resolve_blueprint_capabilities(None)
        self.assertEqual(outcome.capability_resolution, [])
        self.assertEqual(outcome.route, PACKAGE_ROUTE_HUMAN_FALLBACK)
        outcome2 = resolve_blueprint_capabilities({})
        self.assertEqual(outcome2.route, PACKAGE_ROUTE_HUMAN_FALLBACK)

    def test_rest_workflow_list_does_not_unlock_mcp_route(self):
        from dataruns.capabilities.contract import CAP_ID_RESTV2_WORKFLOW_LIST

        outcome = resolve_blueprint_capabilities(
            {
                "capability_dependencies": [
                    {
                        "capability_id": CAP_ID_RESTV2_WORKFLOW_LIST,
                        "required_status": "CONFIRMED_LIVE",
                        "fallback": None,
                    }
                ]
            }
        )
        self.assertEqual(
            outcome.capability_resolution[0]["resolved_status"],
            CAP_STATUS_CONFIRMED_LIVE,
        )
        self.assertEqual(outcome.route, PACKAGE_ROUTE_HUMAN_FALLBACK)

    def test_publish_discovery_without_id_fallback_not_confirmed(self):
        from dataruns.capabilities.contract import CAP_ID_MCP_WORKFLOW_PUBLISH

        row = resolve_dependency(
            {
                "capability_id": CAP_ID_MCP_WORKFLOW_PUBLISH,
                "required_status": "CONFIRMED_LIVE",
                "fallback": None,
            }
        )
        self.assertEqual(row["matrix_status"], CAP_STATUS_DISCOVERY_REQUIRED)
        self.assertEqual(row["resolved_status"], RESOLVED_NOT_CONFIRMED)
        self.assertIsNone(row["fallback_used"])

    def test_confirmed_limited_upsert_with_evidence_sets_mcp(self):
        from dataruns.capabilities.contract import CAP_STATUS_CONFIRMED_LIMITED

        stock = get_capability(CAP_ID_MCP_WORKFLOW_UPSERT)
        assert stock is not None
        fake = deepcopy(stock)
        fake["status"] = CAP_STATUS_CONFIRMED_LIMITED
        fake["evidence"] = [
            {
                "source": "unit-test",
                "locator": "limited",
                "observed_at": "2026-08-26T00:00:00Z",
            }
        ]
        row = resolve_dependency(
            {
                "capability_id": CAP_ID_MCP_WORKFLOW_UPSERT,
                "required_status": "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
                "fallback": CAP_ID_HUMAN_WORKFLOW_BUILD,
            },
            overrides={CAP_ID_MCP_WORKFLOW_UPSERT: fake},
        )
        self.assertEqual(row["resolved_status"], RESOLVED_MCP)
        self.assertEqual(resolve_package_route([row]), PACKAGE_ROUTE_MCP)

    def test_upsert_override_missing_record_still_human(self):
        row = resolve_dependency(
            {
                "capability_id": CAP_ID_MCP_WORKFLOW_UPSERT,
                "required_status": "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
                "fallback": CAP_ID_HUMAN_WORKFLOW_BUILD,
            },
            overrides={CAP_ID_MCP_WORKFLOW_UPSERT: "bad"},  # type: ignore[dict-item]
        )
        self.assertEqual(row["resolved_status"], RESOLVED_HUMAN_FALLBACK)
        self.assertEqual(row["fallback_used"], CAP_ID_HUMAN_WORKFLOW_BUILD)
