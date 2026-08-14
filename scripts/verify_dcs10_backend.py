"""Read-only DCS-10 backend verification."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.history import build_dcs_histories, resolve_dcs_score_history_for_user
from dataruns.models import DataRun
from tenants.models import Company, User

COMPANY_ID = "772587ce-497a-47db-8ace-c2eeb0e81d94"


def main() -> int:
    company = Company.objects.filter(id=COMPANY_ID).first() or Company.objects.first()
    if company is None:
        print("No company found.")
        return 1

    print("=== DCS-10 BACKEND VERIFICATION ===")
    print(f"Company: {company.id} ({company.name})")

    latest = (
        DataRun.objects.filter(
            metadata__kind=DCS_SCORE_KIND,
            status=DataRun.Status.SUCCEEDED,
            metadata__company_id=str(company.id),
        )
        .order_by("-finished_at", "-id")
        .first()
    )
    if latest:
        metadata = latest.metadata or {}
        score = (metadata.get("dcs_run") or {}).get("headline_score")
        run_diff = metadata.get("run_diff")
        print(f"Latest run {latest.id}: score={score}, run_diff={'yes' if run_diff else 'no'}")
        if run_diff:
            headline = run_diff.get("headline_score") or {}
            print(f"  consecutive delta={headline.get('delta')}, baseline={run_diff.get('baseline')}")

    histories = build_dcs_histories(company=company, days=90)
    period_compare = histories["period_compare"]
    deltas = period_compare.get("deltas") or {}
    print(f"period_compare: available={period_compare['available']}, run_count={period_compare['run_count']}")
    print(f"  headline delta={deltas.get('headline_score')}")
    print(f"  at_stake_series={len(histories['at_stake_series'])} points")

    user = User.objects.filter(tenant_id=company.tenant_id, is_active=True).order_by("created_at").first()
    if user:
        payload = resolve_dcs_score_history_for_user(user=user, days_raw="90")
        required = {"points", "value_capture", "at_stake_series", "period_compare", "since", "until"}
        missing = required - set(payload.keys())
        print(f"history API keys ok={not missing}")
        if missing:
            print(f"  missing: {sorted(missing)}")

    print("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
