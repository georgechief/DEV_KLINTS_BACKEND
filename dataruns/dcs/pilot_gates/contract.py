"""DCS-09 pilot supplemental gates — locked contract (PRD §2–§3, §5).

File-only master + UC map. Never feed these IDs into assemble_dcs_score (42).
"""

from __future__ import annotations

from dataruns.use_cases.constants import SUPPLEMENTAL_PREFLIGHT_CHECKS

# Pack / PRD §5 envelope
GATE_CATALOG_VERSION = "MVP1-SUPP-12-v1.4.1"
SUPPLEMENTAL_MASTER_SCHEMA_VERSION = "1.0.0"
SUPPLEMENTAL_MASTER_REL = "dataruns/dcs/check_master_supplemental_mvp1.json"
SUPPLEMENTAL_GATE_MAP_REL = "dataruns/dcs/pilot_supplemental_gate_map.json"
SUPPLEMENTAL_PACK_SOURCE = "pack:sheet 11 Pilot Supplemental Gates"

# Persist metadata (Step 2)
PILOT_GATE_EVAL_KIND = "pilot_gate_eval"
PILOT_SUPPLEMENTAL_SCOPE = "pilot_supplemental"

# Expected count
EXPECTED_SUPPLEMENTAL_CHECK_COUNT = 12

# Executor / recommend result statuses (DCS-04-aligned + recommend labels)
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_NOT_CONNECTED = "NOT_CONNECTED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
# Recommend-only label when no stored supplemental result
STATUS_NOT_EVALUATED = "not_evaluated"

SUPPLEMENTAL_RESULT_STATUS_ENUM = frozenset(
    {
        STATUS_PASS,
        STATUS_FAIL,
        STATUS_WARN,
        STATUS_UNKNOWN,
        STATUS_NOT_CONNECTED,
        STATUS_NOT_APPLICABLE,
    }
)

# PRD §2.3 — only PASS satisfies supplemental readiness
SUPPLEMENTAL_READY_STATUSES = frozenset({STATUS_PASS})

# ERP-out degrades honestly (PRD §9)
ERP_SENSITIVE_CHECK_IDS = frozenset({"BR-09", "PT-06"})

# Slice A (M2 demo) — UC-02
SLICE_A_CHECK_IDS = frozenset({"CI-08", "CC-06"})

# Slice B (Step 8) — remaining 10
SLICE_B_CHECK_IDS = frozenset(
    {
        "BR-03",
        "BR-09",
        "LE-07",
        "LE-10",
        "PT-05",
        "PT-06",
        "PT-11",
        "PT-13",
        "SP-04",
        "SP-10",
    }
)

if SLICE_A_CHECK_IDS & SLICE_B_CHECK_IDS:
    raise RuntimeError("SLICE_A_CHECK_IDS and SLICE_B_CHECK_IDS must be disjoint")
if SLICE_A_CHECK_IDS | SLICE_B_CHECK_IDS != frozenset(SUPPLEMENTAL_PREFLIGHT_CHECKS):
    raise RuntimeError(
        "SLICE_A ∪ SLICE_B must equal SUPPLEMENTAL_PREFLIGHT_CHECKS"
    )

# Alias: pack set already locked in use_cases.constants
SUPPLEMENTAL_CHECK_IDS = SUPPLEMENTAL_PREFLIGHT_CHECKS

# Seed / master row required keys
SUPPLEMENTAL_CHECK_REQUIRED_FIELDS = frozenset(
    {
        "check_id",
        "dimension",
        "title",
        "detection_logic",
        "systems",
        "severity",
        "required_by",
        "failure_behavior",
        "erp_sensitive",
        "role",
        "in_headline_score",
    }
)

SEVERITY_ENUM = frozenset({"High", "Medium", "Low"})


def is_supplemental_check_id(check_id: str | None) -> bool:
    # Seed / constants IDs are uppercase; normalize caller input.
    return str(check_id or "").strip().upper() in SUPPLEMENTAL_CHECK_IDS


def is_erp_sensitive(check_id: str | None) -> bool:
    return str(check_id or "").strip().upper() in ERP_SENSITIVE_CHECK_IDS


def supplemental_status_is_ready(status: str | None) -> bool:
    """True only for PASS (strict readiness — WARN/UNKNOWN/etc. do not unlock)."""
    return str(status or "").strip().upper() == STATUS_PASS


def supplemental_status_blocks_pilot(status: str | None) -> bool:
    """
    True when a stored result is present and does not unlock ready.

    Missing / None is handled by recommend as not_evaluated (provisional), not block.
    """
    if status is None:
        return False
    text = str(status).strip()
    if not text or text == STATUS_NOT_EVALUATED:
        return False
    return not supplemental_status_is_ready(text)
