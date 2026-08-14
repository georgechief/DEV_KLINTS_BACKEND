"""
End-to-end test: create a new scored run with changed dimension scores
and verify score_delta updates in status API.
"""

from __future__ import annotations

import copy
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")
django.setup()

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND  # noqa: E402
from dataruns.dcs.status import resolve_dcs_app_status  # noqa: E402
from dataruns.dcs.worklist import extract_dimensions, get_latest_terminal_dcs_run  # noqa: E402
from dataruns.models import DataRun  # noqa: E402
from django.utils import timezone  # noqa: E402
from tenants.models import Company  # noqa: E402

COMPANY_NAME = "Lumira Skin"
TARGET_DIMENSION = "06 Measurement"
SCORE_BUMP = 5


def print_deltas(label: str, status: dict) -> dict[str, object]:
    dims = status.get("dimensions") or {}
    print(f"\n--- {label} ---")
    snapshot: dict[str, object] = {}
    for name, dim in dims.items():
        if not isinstance(dim, dict):
            continue
        score = dim.get("score")
        delta = dim.get("score_delta", "MISSING")
        print(f"  {name}: score={score} score_delta={delta}")
        snapshot[name] = {"score": score, "score_delta": delta}
    return snapshot


def main() -> int:
    company = Company.objects.filter(name=COMPANY_NAME).first()
    if company is None:
        print(f"ERROR: company '{COMPANY_NAME}' not found")
        return 1

    latest = get_latest_terminal_dcs_run(company=company)
    if latest is None:
        print("ERROR: no terminal DCS run")
        return 1

    before = print_deltas("BEFORE (latest run)", resolve_dcs_app_status(company=company))

    metadata = copy.deepcopy(latest.metadata or {})
    dcs_run = metadata.setdefault("dcs_run", {})
    dimensions = extract_dimensions(metadata)
    if not dimensions or TARGET_DIMENSION not in dimensions:
        print(f"ERROR: {TARGET_DIMENSION} not in latest run dimensions")
        return 1

    prev_score = float(dimensions[TARGET_DIMENSION]["score"])
    new_score = prev_score + SCORE_BUMP
    dimensions[TARGET_DIMENSION] = {
        **dimensions[TARGET_DIMENSION],
        "score": new_score,
    }
    dcs_run["dimensions"] = dimensions
    headline = dcs_run.get("headline_score")
    if headline is not None:
        try:
            dcs_run["headline_score"] = float(headline) + 1.0
        except (TypeError, ValueError):
            pass

    test_run = DataRun.objects.create(
        tenant=company.tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        status=DataRun.Status.SUCCEEDED,
        finished_at=timezone.now(),
        metadata={
            **metadata,
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
            "triggered_by": "delta_verification_test",
        },
    )
    print(f"\nCreated test run id={test_run.id}")
    print(f"  {TARGET_DIMENSION}: {prev_score} -> {new_score} (expected delta +{SCORE_BUMP})")

    after = print_deltas("AFTER (new test run is latest)", resolve_dcs_app_status(company=company))

    target_after = after.get(TARGET_DIMENSION, {})
    actual_delta = target_after.get("score_delta")
    expected_delta = SCORE_BUMP

    passed = actual_delta == expected_delta
    print("\n=== RESULT ===")
    if passed:
        print(f"PASS: {TARGET_DIMENSION} score_delta={actual_delta} (expected +{expected_delta})")
    else:
        print(f"FAIL: {TARGET_DIMENSION} score_delta={actual_delta} (expected +{expected_delta})")

    # Cleanup: remove synthetic run so tenant data stays unchanged
    test_run.delete()
    restored = print_deltas("RESTORED (test run deleted)", resolve_dcs_app_status(company=company))
    restored_delta = (restored.get(TARGET_DIMENSION) or {}).get("score_delta")
    print(f"\nCleanup done. {TARGET_DIMENSION} score_delta back to {restored_delta}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
