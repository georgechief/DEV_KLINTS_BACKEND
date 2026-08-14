"""Sheet 07 canonical lifecycle stages (PRD-AF-01 Phase E / WF-12 prep)."""

from __future__ import annotations

from typing import Any

# Pack sheet 07 — 16 stages · phases · 7 UC groups.
LIFECYCLE_STAGES: tuple[dict[str, Any], ...] = (
    {
        "stage": 1,
        "stage_id": "stage_01",
        "phase": "Acquisition",
        "customer_state": "Unknown visitor",
        "uc_group": "1 Acquisition & Welcome",
        "job": "Capture",
    },
    {
        "stage": 2,
        "stage_id": "stage_02",
        "phase": "Acquisition",
        "customer_state": "Known lead",
        "uc_group": "1 Acquisition & Welcome",
        "job": "Consent",
    },
    {
        "stage": 3,
        "stage_id": "stage_03",
        "phase": "Activation",
        "customer_state": "First purchase intent",
        "uc_group": "1 Acquisition & Welcome",
        "job": "Convert",
    },
    {
        "stage": 4,
        "stage_id": "stage_04",
        "phase": "Activation",
        "customer_state": "New customer",
        "uc_group": "2 Second Purchase & Onboarding",
        "job": "Onboard",
    },
    {
        "stage": 5,
        "stage_id": "stage_05",
        "phase": "Activation",
        "customer_state": "Second-purchase window",
        "uc_group": "2 Second Purchase & Onboarding",
        "job": "Repeat",
    },
    {
        "stage": 6,
        "stage_id": "stage_06",
        "phase": "Repeat",
        "customer_state": "Consumable cycle",
        "uc_group": "3 Replenishment & Repeat",
        "job": "Replenish",
    },
    {
        "stage": 7,
        "stage_id": "stage_07",
        "phase": "Repeat",
        "customer_state": "Availability wait",
        "uc_group": "3 Replenishment & Repeat",
        "job": "Recover demand",
    },
    {
        "stage": 8,
        "stage_id": "stage_08",
        "phase": "Repeat",
        "customer_state": "Price sensitivity",
        "uc_group": "3 Replenishment & Repeat",
        "job": "Convert interest",
    },
    {
        "stage": 9,
        "stage_id": "stage_09",
        "phase": "Retention",
        "customer_state": "Early risk",
        "uc_group": "4 Churn & Winback",
        "job": "Save",
    },
    {
        "stage": 10,
        "stage_id": "stage_10",
        "phase": "Retention",
        "customer_state": "Lapsed",
        "uc_group": "4 Churn & Winback",
        "job": "Reactivate",
    },
    {
        "stage": 11,
        "stage_id": "stage_11",
        "phase": "Retention",
        "customer_state": "Return/service risk",
        "uc_group": "4 Churn & Winback",
        "job": "Recover relationship",
    },
    {
        "stage": 12,
        "stage_id": "stage_12",
        "phase": "Loyalty",
        "customer_state": "VIP candidate",
        "uc_group": "5 VIP & Loyalty",
        "job": "Progress",
    },
    {
        "stage": 13,
        "stage_id": "stage_13",
        "phase": "Loyalty",
        "customer_state": "Milestone",
        "uc_group": "5 VIP & Loyalty",
        "job": "Recognise",
    },
    {
        "stage": 14,
        "stage_id": "stage_14",
        "phase": "Expansion",
        "customer_state": "Complementary need",
        "uc_group": "6 Cross-sell & Expansion",
        "job": "Cross-sell",
    },
    {
        "stage": 15,
        "stage_id": "stage_15",
        "phase": "Expansion",
        "customer_state": "Premium readiness",
        "uc_group": "6 Cross-sell & Expansion",
        "job": "Upsell",
    },
    {
        "stage": 16,
        "stage_id": "stage_16",
        "phase": "Reactivation",
        "customer_state": "Paid suppression/reactivation",
        "uc_group": "7 Paid & Reactivation",
        "job": "Coordinate",
    },
)

# FE Lifecycle mock today uses 5 phase cards; map pack phases → card keys.
FE_PHASE_CARD_KEYS: dict[str, str] = {
    "Acquisition": "acq",
    "Activation": "act",
    "Repeat": "act",
    "Retention": "ret",
    "Loyalty": "loy",
    "Expansion": "exp",
    "Reactivation": "ret",
}

PHASE_ORDER: tuple[str, ...] = (
    "Acquisition",
    "Activation",
    "Repeat",
    "Retention",
    "Loyalty",
    "Expansion",
    "Reactivation",
)


def stage_id_for_number(stage: int) -> str:
    return f"stage_{int(stage):02d}"


def normalize_lifecycle_stage(value: str | None) -> str | None:
    """Accept stage_01, stage-1, 1, Stage 1, etc. → stage_XX."""
    if not value:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text.startswith("stage_"):
        digits = "".join(ch for ch in text[6:] if ch.isdigit())
        if digits:
            n = int(digits)
            if 1 <= n <= 16:
                return stage_id_for_number(n)
    if text.isdigit():
        n = int(text)
        if 1 <= n <= 16:
            return stage_id_for_number(n)
    return None
