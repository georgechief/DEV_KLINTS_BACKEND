#!/usr/bin/env python
"""Compare last two succeeded DCS runs per company (headline + check deltas)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django

django.setup()

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.models import DataRun, QaCheck


def main() -> None:
    runs = list(
        DataRun.objects.filter(
            metadata__kind=DCS_SCORE_KIND,
            status=DataRun.Status.SUCCEEDED,
        ).order_by("-created_at")[:20]
    )
    if not runs:
        print("No succeeded DCS runs in DB.")
        return

    by_company: dict[str, list[DataRun]] = {}
    for dr in runs:
        cid = (dr.metadata or {}).get("company_id") or "unknown"
        by_company.setdefault(str(cid), []).append(dr)

    for cid, company_runs in by_company.items():
        company_runs.sort(key=lambda r: r.created_at, reverse=True)
        print(f"\n=== Company {cid[:8]}... ({len(company_runs)} recent succeeded) ===")
        for dr in company_runs[:4]:
            meta = dr.metadata or {}
            dcs = meta.get("dcs_run") or {}
            print(
                f"  DataRun {dr.id}: headline={dcs.get('headline_score')} "
                f"state={dcs.get('run_state')} at={dr.finished_at or dr.created_at}"
            )

        if len(company_runs) < 2:
            continue

        newer, older = company_runs[0], company_runs[1]
        nh = (newer.metadata or {}).get("dcs_run", {}).get("headline_score")
        oh = (older.metadata or {}).get("dcs_run", {}).get("headline_score")
        print(f"\n  Delta: {oh} -> {nh} ({(nh or 0) - (oh or 0):+.1f})" if nh and oh else "")

        new_run_id = (newer.metadata or {}).get("run_id")
        old_run_id = (older.metadata or {}).get("run_id")
        if not new_run_id or not old_run_id:
            continue

        new_checks = {
            q.check_type: q.result
            for q in QaCheck.objects.filter(run_id=new_run_id)
        }
        old_checks = {
            q.check_type: q.result
            for q in QaCheck.objects.filter(run_id=old_run_id)
        }
        deltas = []
        for check_id in sorted(set(new_checks) | set(old_checks)):
            n, o = new_checks.get(check_id), old_checks.get(check_id)
            if n != o:
                deltas.append((check_id, o, n))
        if deltas:
            print("  Check status changes (older -> newer):")
            for check_id, o, n in deltas:
                print(f"    {check_id}: {o} -> {n}")
        else:
            print("  No check status changes between last two succeeded runs.")


if __name__ == "__main__":
    main()
