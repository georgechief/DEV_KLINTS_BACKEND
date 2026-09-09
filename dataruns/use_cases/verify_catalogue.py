"""OPS-UC-01 — verify MVP1 pilot catalogue is seeded."""

from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from dataruns.use_cases.constants import (
    MVP1_PILOT_COUNT,
    MVP1_PILOT_IDS,
    PILOT_PRIMARY_STAGES,
)
from dataruns.use_cases.models import PilotStageMap, UseCaseBlueprint, UseCasePilot

REQUIRED_PILOT_IDS = frozenset({"UC-02"})


def verify_pilot_catalogue(*, verbose: bool = True) -> tuple[bool, list[str]]:
    """
    Return (ok, messages). Safe to import from tests and post-deploy scripts.
    """
    messages: list[str] = []
    ok = True

    def check(condition: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        line = f"  [ok] {label}" if condition else f"  [FAIL] {label}"
        if not condition and detail:
            line = f"{line} — {detail}"
        messages.append(line)
        if not condition:
            ok = False

    try:
        pilot_count = UseCasePilot.objects.count()
        blueprint_count = UseCaseBlueprint.objects.count()
        stage_map_count = PilotStageMap.objects.count()
    except (OperationalError, ProgrammingError) as exc:
        messages.append(f"  [FAIL] database tables unavailable — {exc}")
        messages.append("  Run: python manage.py migrate")
        return False, messages

    pilot_ids = set(UseCasePilot.objects.values_list("use_case_id", flat=True))
    ordered_ids = list(
        UseCasePilot.objects.order_by("pilot_rank").values_list(
            "use_case_id", flat=True
        )
    )

    check(
        pilot_count == MVP1_PILOT_COUNT,
        f"UseCasePilot count = {MVP1_PILOT_COUNT}",
        f"got {pilot_count}",
    )
    check(
        blueprint_count == MVP1_PILOT_COUNT,
        f"UseCaseBlueprint count = {MVP1_PILOT_COUNT}",
        f"got {blueprint_count}",
    )
    check(
        pilot_ids == set(MVP1_PILOT_IDS),
        "pilot id set matches MVP1 manifest",
        f"missing={sorted(set(MVP1_PILOT_IDS) - pilot_ids)!r} "
        f"extra={sorted(pilot_ids - set(MVP1_PILOT_IDS))!r}",
    )
    for required in sorted(REQUIRED_PILOT_IDS):
        check(required in pilot_ids, f"{required} present")

    ranks = list(
        UseCasePilot.objects.order_by("pilot_rank").values_list("pilot_rank", flat=True)
    )
    check(
        len(ranks) == len(set(ranks)) == MVP1_PILOT_COUNT,
        "pilot ranks are unique",
        f"ranks={ranks!r}",
    )

    missing_blueprints = [
        pid
        for pid in ordered_ids
        if not UseCaseBlueprint.objects.filter(pilot_id=pid).exists()
    ]
    check(
        not missing_blueprints,
        "every pilot has a blueprint row",
        f"missing={missing_blueprints!r}",
    )

    expected_stage_maps = sum(
        len(PILOT_PRIMARY_STAGES.get(pid, ())) for pid in MVP1_PILOT_IDS
    )
    check(
        stage_map_count == expected_stage_maps,
        f"PilotStageMap count = {expected_stage_maps}",
        f"got {stage_map_count}",
    )

    uc02 = UseCaseBlueprint.objects.filter(pilot_id="UC-02").first()
    if uc02 and isinstance(uc02.body, dict):
        gates = uc02.body.get("gates") if isinstance(uc02.body.get("gates"), dict) else {}
        check(bool(gates.get("gating_check_ids")), "UC-02 blueprint has gating_check_ids")
        check(gates.get("min_dcs") == 70, "UC-02 min_dcs = 70", f"got {gates.get('min_dcs')!r}")

    if verbose and ordered_ids:
        messages.append(f"\n  Ordered pilots: {', '.join(ordered_ids)}")

    return ok, messages
