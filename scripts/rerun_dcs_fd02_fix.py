"""Re-run DCS score synchronously (uses current code, not stale Celery worker)."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.enqueue import enqueue_dcs_score
from dataruns.dcs.orchestrate import run_dcs_pipeline
from tenants.models import Company, Connector


def main() -> None:
    connector = (
        Connector.objects.filter(name="shopify", status="connected")
        .order_by("-updated_at")
        .first()
    )
    if connector is None:
        print("No connected Shopify connector.")
        sys.exit(1)

    company = connector.company
    print(f"Re-running DCS for company={company.id} ...")

    enqueued = enqueue_dcs_score(
        company,
        triggered_by="manual_fd02_fix",
        queue=False,
        live_revalidate=True,
    )
    data_run = enqueued.data_run
    if data_run is None:
        print("Failed to create DCS DataRun.")
        sys.exit(1)

    print(f"Created data_run={data_run.id}, running pipeline (may take ~40s)...")
    result = run_dcs_pipeline(data_run)
    print("Pipeline result:", json.dumps(result, indent=2, default=str))

    data_run.refresh_from_db()
    meta = data_run.metadata or {}
    dcs_run = meta.get("dcs_run") or {}
    check_results = meta.get("check_results") or []
    fd02 = next(
        (row for row in check_results if isinstance(row, dict) and row.get("check_id") == "FD-02"),
        None,
    )
    print(f"\nrun_state={dcs_run.get('run_state')} headline_score={dcs_run.get('headline_score')}")
    if fd02:
        print(f"FD-02: {fd02.get('status')} — {fd02.get('message')}")
        for ev in fd02.get("evidence") or []:
            if isinstance(ev, dict) and "scope" in str(ev.get("locator", "")):
                print("evidence:", json.dumps(ev.get("value"), indent=2))


if __name__ == "__main__":
    main()
