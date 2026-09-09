"""CAP-01 locked contract (PRD §3–§4) — enums + route eligibility helpers.

Registry: `registry.py`. Resolver: `resolver.py`. Do not invent MCP CONFIRMED.
"""

from __future__ import annotations

# Pack SoT: capability_record.schema.json
CAPABILITY_RECORD_SCHEMA_VERSION = "1.0.0"
CAPABILITY_RECORD_SCHEMA_REL = (
    "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
    "/03_Machine_Contracts/capability_record.schema.json"
)
MATRIX_PACK_SOURCE = "pack:Capability Matrix v1.1"
MATRIX_SEED_REL = "dataruns/capabilities/matrix_seed.json"

# Matrix status (pack enum — seed must use exactly these)
CAP_STATUS_CONFIRMED_LIVE = "CONFIRMED_LIVE"
CAP_STATUS_CONFIRMED_LIMITED = "CONFIRMED_LIMITED"
CAP_STATUS_DISCOVERY_REQUIRED = "DISCOVERY_REQUIRED"
CAP_STATUS_REQUIRED_BUILD = "REQUIRED_BUILD"
CAP_STATUS_NOT_SUPPORTED = "NOT_SUPPORTED"

CAP_STATUS_ENUM = frozenset(
    {
        CAP_STATUS_CONFIRMED_LIVE,
        CAP_STATUS_CONFIRMED_LIMITED,
        CAP_STATUS_DISCOVERY_REQUIRED,
        CAP_STATUS_REQUIRED_BUILD,
        CAP_STATUS_NOT_SUPPORTED,
    }
)

# Statuses that can unlock MCP write / execute-eligible (PRD §4.1)
CAP_STATUS_MCP_WRITE_ELIGIBLE = frozenset(
    {
        CAP_STATUS_CONFIRMED_LIVE,
        CAP_STATUS_CONFIRMED_LIMITED,
    }
)

# Modes (pack enum)
CAP_MODE_READ = "READ"
CAP_MODE_WRITE = "WRITE"
CAP_MODE_WRITE_ARTIFACT = "WRITE_ARTIFACT"
CAP_MODE_READ_ARTIFACT = "READ_ARTIFACT"

CAP_MODE_ENUM = frozenset(
    {
        CAP_MODE_READ,
        CAP_MODE_WRITE,
        CAP_MODE_WRITE_ARTIFACT,
        CAP_MODE_READ_ARTIFACT,
    }
)

# Well-known capability IDs (PRD §3.2 must-seed + route key)
CAP_ID_HUMAN_WORKFLOW_BUILD = "HUMAN.WORKFLOW.BUILD"
CAP_ID_MCP_WORKFLOW_UPSERT = "MCP.WORKFLOW.UPSERT"
CAP_ID_MCP_WORKFLOW_PUBLISH = "MCP.WORKFLOW.PUBLISH"
CAP_ID_RESTV2_WORKFLOW_LIST = "RESTV2.WORKFLOW.LIST"

# Channels seen in Matrix sheet 02 (not a closed enum in schema)
CHANNEL_MANAGO_MCP = "MANAGO_MCP"
CHANNEL_HUMAN_OPERATOR = "HUMAN_OPERATOR"
CHANNEL_REST_V2 = "REST_V2"

# Package route (WF-01 / CAP-01 §4.2)
PACKAGE_ROUTE_HUMAN_FALLBACK = "HUMAN_FALLBACK"
PACKAGE_ROUTE_MCP = "MCP"

PACKAGE_ROUTE_ENUM = frozenset(
    {
        PACKAGE_ROUTE_HUMAN_FALLBACK,
        PACKAGE_ROUTE_MCP,
    }
)

# capability_resolution[].resolved_status (package payload — not pack Matrix status)
RESOLVED_HUMAN_FALLBACK = "HUMAN_FALLBACK"
RESOLVED_NOT_CONFIRMED = "NOT_CONFIRMED"
RESOLVED_MCP = "MCP"  # UPSERT execute-eligible alias for route=MCP
# Confirmed non-UPSERT may also pass Matrix status through as resolved_status
RESOLVED_STATUS_VALUES = frozenset(
    {
        RESOLVED_HUMAN_FALLBACK,
        RESOLVED_NOT_CONFIRMED,
        RESOLVED_MCP,
        CAP_STATUS_CONFIRMED_LIVE,
        CAP_STATUS_CONFIRMED_LIMITED,
        CAP_STATUS_DISCOVERY_REQUIRED,
        CAP_STATUS_REQUIRED_BUILD,
        CAP_STATUS_NOT_SUPPORTED,
    }
)

# Blueprint required_status (do not invent new values)
REQUIRED_CONFIRMED_LIVE = "CONFIRMED_LIVE"
REQUIRED_CONFIRMED_LIVE_OR_APPROVED_FALLBACK = "CONFIRMED_LIVE_OR_APPROVED_FALLBACK"

# Seed / resolution row keys
SEED_ROW_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "capability_id",
        "channel",
        "mode",
        "status",
        "input_contract",
        "output_contract",
        "fallback",
        "evidence",
    }
)

RESOLUTION_ROW_REQUIRED_FIELDS = frozenset(
    {
        "capability_id",
        "required_status",
        "resolved_status",
        "fallback_used",
    }
)
# Optional on resolution rows: matrix_status, channel

# Default pilot / UPSERT fallback (sheet 05 Workflow build)
DEFAULT_HUMAN_FALLBACK_CAPABILITY = CAP_ID_HUMAN_WORKFLOW_BUILD


def status_allows_mcp_write(status: str | None) -> bool:
    """True when Matrix status may unlock MCP WRITE (still needs evidence for MCP channel)."""
    return str(status or "").strip().upper() in CAP_STATUS_MCP_WRITE_ELIGIBLE


def is_manago_mcp_write_channel(channel: str | None) -> bool:
    return str(channel or "").strip().upper() == CHANNEL_MANAGO_MCP


def is_human_operator_channel(channel: str | None) -> bool:
    return str(channel or "").strip().upper() == CHANNEL_HUMAN_OPERATOR


def upsert_is_execute_eligible(
    *,
    status: str | None,
    channel: str | None,
    evidence: list | None,
    mode: str | None = CAP_MODE_WRITE,
) -> bool:
    """
    MCP.WORKFLOW.UPSERT unlocks package route=MCP only when execute-eligible.

    PRD §4.2: CONFIRMED_LIVE|LIMITED + (WRITE MCP requires non-empty evidence)
    OR human channel (not applicable to UPSERT row itself).
    """
    if not status_allows_mcp_write(status):
        return False
    mode_u = str(mode or CAP_MODE_WRITE).strip().upper()
    has_evidence = isinstance(evidence, list) and len(evidence) > 0
    if mode_u in {CAP_MODE_WRITE, CAP_MODE_WRITE_ARTIFACT} and is_manago_mcp_write_channel(
        channel
    ):
        return has_evidence
    if is_human_operator_channel(channel):
        return True
    # Confirmed READ (e.g. REST list) never unlocks UPSERT route
    return False
