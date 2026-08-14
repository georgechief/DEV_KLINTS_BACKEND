"""Inspect live DCS dimension scores and score_delta for verification."""

from __future__ import annotations

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")
django.setup()

from dataruns.dcs.history import build_dcs_score_history  # noqa: E402
from dataruns.dcs.status import resolve_dcs_app_status  # noqa: E402
from tenants.models import Company  # noqa: E402


def main() -> None:
    companies = list(Company.objects.all()[:10])
    if not companies:
        print("NO_COMPANY")
        return

    for company in companies:
        status = resolve_dcs_app_status(company=company)
        dims = status.get("dimensions") or {}
        hist = build_dcs_score_history(company=company, days=30)
        if not dims and not hist:
            continue

        print(f"\n=== COMPANY: {company.name} ({company.id}) ===")
        print("=== DIMENSIONS (latest status) ===")
        if not dims:
            print("(none)")
        for name, dim in dims.items():
            if isinstance(dim, dict):
                delta = dim.get("score_delta", "MISSING")
                print(f"  {name}: score={dim.get('score')} score_delta={delta}")
            else:
                print(f"  {name}: {dim}")

        print(f"\n=== HISTORY: {len(hist)} scored run(s) in last 30 days ===")
        for point in hist:
            dim_keys = list(point["dimensions"].keys()) if point.get("dimensions") else []
            print(
                f"  run {point['data_run_id']}: "
                f"headline={point['score']} at={point['at'][:10]} "
                f"dimensions={len(dim_keys)}"
            )

        if len(hist) < 2:
            print("NOTE: Need 2+ scored runs for score_delta.")
        return

    print("No company with dimension data found in local DB.")


if __name__ == "__main__":
    main()
