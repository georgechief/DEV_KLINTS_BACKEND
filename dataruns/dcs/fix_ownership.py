"""Excel sheet 02 Fix Type / Fix Owner helpers (Klints vs tenant ownership)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dataruns.dcs.types import CheckResult

# Exact Excel sheet 02 "Fix Owner" value for Klints-owned remediations.
KLINTS_AUTOMATED_OWNER = "Klints (automated)"


def is_klints_automated_fix(fix_owner: str | None) -> bool:
    """True when Excel Fix Owner is Klints (automated) — fix in Klints."""
    return (fix_owner or "").strip().casefold() == KLINTS_AUTOMATED_OWNER.casefold()


def fix_ownership_fields(
    *,
    fix_type: str | None = None,
    fix_owner: str | None = None,
    suggested_fix: str | None = None,
) -> dict[str, Any]:
    """Normalize ownership fields for API / issue payloads."""
    owner = (fix_owner or "").strip()
    ftype = (fix_type or "").strip()
    suggested = (suggested_fix or "").strip()
    return {
        "fix_type": ftype,
        "fix_owner": owner,
        "fix_in_klints": is_klints_automated_fix(owner),
        "suggested_fix": suggested,
    }


def enrich_check_results_from_master(check_results: list[CheckResult]) -> None:
    """
    Attach Excel Fix Type / Fix Owner onto check results (in place).

    Prefer existing result values; fill gaps from CheckMaster when seeded.
    """
    from dataruns.models import CheckMaster

    if not check_results:
        return

    by_id = {
        row.check_id: row
        for row in CheckMaster.objects.filter(is_active=True).only(
            "check_id",
            "fix_type",
            "fix_owner",
            "suggested_fix",
        )
    }
    for result in check_results:
        master = by_id.get(result.check_id)
        if master is None:
            if result.fix_owner:
                result.fix_in_klints = is_klints_automated_fix(result.fix_owner)
            continue
        if not result.fix_type:
            result.fix_type = master.fix_type or None
        if not result.fix_owner:
            result.fix_owner = master.fix_owner or None
        if not result.suggested_fix:
            result.suggested_fix = master.suggested_fix or None
        result.fix_in_klints = is_klints_automated_fix(result.fix_owner)
