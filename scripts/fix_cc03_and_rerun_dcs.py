"""
Fix CC-03 (consent provenance) for Lumira Skin, rerun DCS without live re-import,
and print dimension score + score_delta before/after.
"""

from __future__ import annotations

import copy
import os
import sys
from unittest.mock import patch

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")
django.setup()

from dataruns.dcs.enqueue import enqueue_dcs_score  # noqa: E402
from dataruns.dcs.orchestrate import run_dcs_pipeline  # noqa: E402
from dataruns.dcs.status import resolve_dcs_app_status  # noqa: E402
from dataruns.dcs.worklist import (  # noqa: E402
    build_worklist_payload,
    extract_dcs_payload,
    get_latest_terminal_dcs_run,
)
from dataruns.models import DataRun  # noqa: E402
from tenants.models import Company, Connector, ConnectorSnapshot  # noqa: E402

COMPANY_NAME = "Lumira Skin"
TARGET_CHECK = "CC-03"
TARGET_EMAIL = "rohan@klints.io"
CONSENT_FIX = {
    "source": "shopify_checkout",
    "reason": "email_marketing",
    "agreementDate": "2026-01-15T10:00:00Z",
}


def print_status(label: str) -> dict:
    company = Company.objects.filter(name=COMPANY_NAME).first()
    status = resolve_dcs_app_status(company=company)
    wl = build_worklist_payload(company=company)
    cc = next((i for i in wl["issues"] if i.get("check_id") == TARGET_CHECK), None)
    print(f"\n========== {label} ==========")
    if cc:
        print(f"{TARGET_CHECK}: {cc.get('status')} — {cc.get('title')}")
    else:
        print(f"{TARGET_CHECK}: PASS (not in open issues)")
    dims = status.get("dimensions") or {}
    for name, dim in dims.items():
        if not isinstance(dim, dict):
            continue
        print(
            f"  {name}: score={round(float(dim['score']))} "
            f"score_delta={dim.get('score_delta')}"
        )
    return status


def fix_manago_consent_provenance() -> bool:
    company = Company.objects.filter(name=COMPANY_NAME).first()
    if company is None:
        return False
    connector = Connector.objects.filter(company=company, name="manago_ai").first()
    if connector is None:
        return False
    snap = (
        ConnectorSnapshot.objects.filter(connector=connector)
        .order_by("-version")
        .first()
    )
    if snap is None:
        return False

    data = copy.deepcopy(snap.snapshot_data or {})
    raw = data.setdefault("raw", {})
    contacts = raw.get("contacts")
    if not isinstance(contacts, list):
        return False

    fixed = False
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        email = str(contact.get("email") or contact.get("contactEmail") or "").lower()
        if email != TARGET_EMAIL.lower():
            continue
        contact["consents"] = [CONSENT_FIX.copy()]
        fixed = True
        print(f"Fixed consent provenance on {TARGET_EMAIL} in snapshot v{snap.version}")

    if not fixed:
        print(f"ERROR: contact {TARGET_EMAIL} not found in Manago snapshot")
        return False

    snap.snapshot_data = data
    snap.save(update_fields=["snapshot_data"])
    return True


def rerun_dcs_skip_import() -> DataRun | None:
    company = Company.objects.filter(name=COMPANY_NAME).first()
    if company is None:
        return None

    latest = get_latest_terminal_dcs_run(company=company)
    if latest is None:
        return None
    meta = latest.metadata or {}
    source_runs = meta.get("source_runs") or {}
    fresh_imports = meta.get("fresh_imports") or {}
    window_days = int((meta.get("fresh_imports") or {}).get("window_days") or 30)

    def _skip_refresh(*, company, dcs_data_run, days=None):
        return {
            "source_runs": {
                "shopify": int(source_runs["shopify"]) if source_runs.get("shopify") else None,
                "manago_ai": int(source_runs["manago_ai"]) if source_runs.get("manago_ai") else None,
            },
            "fresh_imports": fresh_imports,
            "window_days": days or window_days,
        }

    with patch(
        "dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs",
        side_effect=_skip_refresh,
    ):
        result = enqueue_dcs_score(
            company,
            triggered_by="cc03_fix_verification",
            queue=False,
        )
        data_run = result.data_run
        if data_run is None:
            print("ERROR: enqueue returned no data_run")
            return None
        print(f"Running DCS pipeline for data_run id={data_run.id} ...")
        pipeline = run_dcs_pipeline(data_run)
        print("Pipeline result:", pipeline.get("ok"), pipeline.get("run_state"))
        data_run.refresh_from_db()
        return data_run


def main() -> int:
    print_status("BEFORE")
    if not fix_manago_consent_provenance():
        return 1
    run = rerun_dcs_skip_import()
    if run is None or run.status != DataRun.Status.SUCCEEDED:
        print(f"ERROR: DCS run failed status={getattr(run, 'status', None)}")
        return 1
    print_status("AFTER")
    latest = get_latest_terminal_dcs_run(
        company=Company.objects.filter(name=COMPANY_NAME).first()
    )
    payload = extract_dcs_payload(latest.metadata if latest else {})
    cc = next(
        (c for c in payload.get("check_results", []) if c.get("check_id") == TARGET_CHECK),
        None,
    )
    if cc:
        print(f"\nLatest run {latest.id}: {TARGET_CHECK} = {cc.get('status')}")
    print("\nDone. Refresh Data Center in the app to see updated tiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
