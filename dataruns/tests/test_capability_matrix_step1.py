"""CAP-01 Step 1 — locked contract constants (no seed / resolver yet)."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.capabilities.contract import (
    CAP_ID_HUMAN_WORKFLOW_BUILD,
    CAP_ID_MCP_WORKFLOW_PUBLISH,
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_ID_RESTV2_WORKFLOW_LIST,
    CAP_MODE_ENUM,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    CAP_STATUS_ENUM,
    CAP_STATUS_MCP_WRITE_ELIGIBLE,
    CHANNEL_MANAGO_MCP,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
    PACKAGE_ROUTE_MCP,
    REQUIRED_CONFIRMED_LIVE_OR_APPROVED_FALLBACK,
    RESOLVED_HUMAN_FALLBACK,
    RESOLVED_MCP,
    SEED_ROW_REQUIRED_FIELDS,
    status_allows_mcp_write,
    upsert_is_execute_eligible,
)


class Cap01ContractStep1Tests(SimpleTestCase):
    def test_status_enum_matches_pack_schema(self):
        self.assertEqual(
            CAP_STATUS_ENUM,
            frozenset(
                {
                    "CONFIRMED_LIVE",
                    "CONFIRMED_LIMITED",
                    "DISCOVERY_REQUIRED",
                    "REQUIRED_BUILD",
                    "NOT_SUPPORTED",
                }
            ),
        )

    def test_mode_enum_matches_pack_schema(self):
        self.assertEqual(
            CAP_MODE_ENUM,
            frozenset({"READ", "WRITE", "WRITE_ARTIFACT", "READ_ARTIFACT"}),
        )

    def test_must_seed_ids_locked(self):
        self.assertEqual(CAP_ID_HUMAN_WORKFLOW_BUILD, "HUMAN.WORKFLOW.BUILD")
        self.assertEqual(CAP_ID_MCP_WORKFLOW_UPSERT, "MCP.WORKFLOW.UPSERT")
        self.assertEqual(CAP_ID_MCP_WORKFLOW_PUBLISH, "MCP.WORKFLOW.PUBLISH")
        self.assertEqual(CAP_ID_RESTV2_WORKFLOW_LIST, "RESTV2.WORKFLOW.LIST")

    def test_seed_row_required_fields(self):
        self.assertIn("capability_id", SEED_ROW_REQUIRED_FIELDS)
        self.assertIn("evidence", SEED_ROW_REQUIRED_FIELDS)
        self.assertIn("fallback", SEED_ROW_REQUIRED_FIELDS)

    def test_mcp_write_eligible_statuses(self):
        self.assertTrue(status_allows_mcp_write(CAP_STATUS_CONFIRMED_LIVE))
        self.assertTrue(status_allows_mcp_write("CONFIRMED_LIMITED"))
        self.assertFalse(status_allows_mcp_write(CAP_STATUS_DISCOVERY_REQUIRED))
        self.assertEqual(
            CAP_STATUS_MCP_WRITE_ELIGIBLE,
            frozenset({"CONFIRMED_LIVE", "CONFIRMED_LIMITED"}),
        )

    def test_upsert_not_eligible_without_evidence(self):
        self.assertFalse(
            upsert_is_execute_eligible(
                status=CAP_STATUS_CONFIRMED_LIVE,
                channel=CHANNEL_MANAGO_MCP,
                evidence=[],
            )
        )
        self.assertFalse(
            upsert_is_execute_eligible(
                status=CAP_STATUS_DISCOVERY_REQUIRED,
                channel=CHANNEL_MANAGO_MCP,
                evidence=[{"source": "x", "locator": "y", "observed_at": "z"}],
            )
        )

    def test_upsert_eligible_with_confirmed_and_evidence(self):
        self.assertTrue(
            upsert_is_execute_eligible(
                status=CAP_STATUS_CONFIRMED_LIVE,
                channel=CHANNEL_MANAGO_MCP,
                evidence=[{"source": "test", "locator": "unit", "observed_at": "2026-01-01T00:00:00Z"}],
            )
        )

    def test_upsert_rejects_non_list_evidence(self):
        self.assertFalse(
            upsert_is_execute_eligible(
                status=CAP_STATUS_CONFIRMED_LIVE,
                channel=CHANNEL_MANAGO_MCP,
                evidence="not-a-list",  # type: ignore[arg-type]
            )
        )

    def test_package_route_values(self):
        self.assertEqual(PACKAGE_ROUTE_HUMAN_FALLBACK, "HUMAN_FALLBACK")
        self.assertEqual(PACKAGE_ROUTE_MCP, "MCP")
        self.assertEqual(RESOLVED_HUMAN_FALLBACK, "HUMAN_FALLBACK")
        self.assertEqual(RESOLVED_MCP, "MCP")

    def test_uc02_required_status_token(self):
        self.assertEqual(
            REQUIRED_CONFIRMED_LIVE_OR_APPROVED_FALLBACK,
            "CONFIRMED_LIVE_OR_APPROVED_FALLBACK",
        )
