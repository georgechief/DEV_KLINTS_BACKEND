"""MVP1 pilot constants (PRD-UC-01)."""

from pathlib import Path

# Authoritative pack paths (relative to BASE_DIR).
DEFAULT_BUILD_PACK_DIR = Path(
    "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718",
)
DEFAULT_MANIFEST_REL = (
    DEFAULT_BUILD_PACK_DIR / "04_MVP1_Pilot_Blueprints" / "pilot_manifest.json"
)
DEFAULT_BLUEPRINT_SCHEMA_REL = (
    DEFAULT_BUILD_PACK_DIR
    / "03_Machine_Contracts"
    / "workflow_blueprint.schema.json"
)
DEFAULT_BLUEPRINTS_DIR_REL = (
    DEFAULT_BUILD_PACK_DIR / "04_MVP1_Pilot_Blueprints"
)

MVP1_PILOT_COUNT = 16

# Locked MVP1 pilot IDs (PRD §3.1) — UC-06B not UC-06A; UC-01 excluded.
MVP1_PILOT_IDS = frozenset(
    {
        "UC-02",
        "UC-04",
        "UC-05",
        "UC-06B",
        "UC-08",
        "UC-09",
        "UC-10",
        "UC-11",
        "UC-12",
        "UC-13",
        "UC-16",
        "UC-17",
        "UC-21",
        "UC-23",
        "UC-28",
        "UC-36",
    }
)

# WF-12 primary stage mapping (PRD §6).
PILOT_PRIMARY_STAGES: dict[str, tuple[str, ...]] = {
    "UC-02": ("stage_02", "stage_04"),
    "UC-04": ("stage_03",),
    "UC-05": ("stage_02",),
    "UC-06B": ("stage_05",),
    "UC-08": ("stage_04",),
    "UC-09": ("stage_04",),
    "UC-10": ("stage_04",),
    "UC-11": ("stage_06",),
    "UC-12": ("stage_07",),
    "UC-13": ("stage_08",),
    "UC-16": ("stage_09",),
    "UC-17": ("stage_10",),
    "UC-21": ("stage_03",),
    "UC-23": ("stage_12",),
    "UC-28": ("stage_14",),
    "UC-36": ("stage_15",),
}

USE_CASE_ID_RE = r"^UC-[0-9]{2}[A-Z]?$"
