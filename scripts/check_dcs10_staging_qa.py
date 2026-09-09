"""Local/staging QA probe for DCS-10 fresh import (PRD §9)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.models import DataRun
from tenants.models import Company, Connector


def main() -> int:
    print("=== DCS-10 STAGING QA PROBE (local DB) ===\n")

    company = (
        Company.objects.filter(
            id=os.environ.get("DCS10_QA_COMPANY_ID", "")
        ).first()
        if os.environ.get("DCS10_QA_COMPANY_ID")
        else None
    )
    if company is None:
        latest_any = (
            DataRun.objects.filter(metadata__kind=DCS_SCORE_KIND)
            .order_by("-id")
            .first()
        )
        if latest_any:
            cid = (latest_any.metadata or {}).get("company_id")
            company = Company.objects.filter(id=cid).first()
    if company is None:
        company = Company.objects.order_by("-created_at").first()
    if company is None:
        print("No company in database.")
        return 1

    print(f"Company: {company.name} ({company.id})")
    connectors = Connector.objects.filter(
        company=company, name__in=("shopify", "manago_ai")
    )
    for conn in connectors:
        print(f"  Connector {conn.name}: status={conn.status}")

    latest = (
        DataRun.objects.filter(
            name="dcs-score",
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
        )
        .order_by("-finished_at", "-id")
        .first()
    )
    if latest is None:
        print("\nNo dcs-score DataRun found for this company.")
        return 1

    meta = latest.metadata or {}
    fresh = meta.get("fresh_imports") or {}
    print(f"\nLatest dcs-score: id={latest.id} status={latest.status} finished={latest.finished_at}")

    if isinstance(fresh, dict) and fresh:
        print("fresh_imports:")
        for platform, block in fresh.items():
            if not isinstance(block, dict):
                continue
            print(
                f"  {platform}: data_run_id={block.get('data_run_id')} "
                f"window_end={block.get('window_end')}"
            )
    else:
        print("fresh_imports: MISSING or empty (fail-closed violation if connectors connected)")

    if meta.get("fresh_import_failed_platform"):
        print(f"fresh_import_failed_platform: {meta.get('fresh_import_failed_platform')}")

    print("\nSibling dcs-fresh-import runs (latest per platform):")
    for platform in ("shopify", "manago_ai"):
        dr = (
            DataRun.objects.filter(
                name=f"dcs-fresh-import:{platform}",
                metadata__company_id=str(company.id),
            )
            .order_by("-id")
            .first()
        )
        if dr is None:
            print(f"  {platform}: none")
            continue
        m = dr.metadata or {}
        print(
            f"  {platform}: id={dr.id} status={dr.status} "
            f"triggered_by={m.get('triggered_by')} dcs_data_run_id={m.get('dcs_data_run_id')}"
        )

    status = resolve_dcs_app_status(company=company)
    latest_run = status.get("latest_run") or {}
    status_fresh = latest_run.get("fresh_imports")
    print("\nGET /dcs/status/ equivalent (resolve_dcs_app_status):")
    print(f"  latest_run.id={latest_run.get('id')} status={latest_run.get('status')}")
    if status_fresh:
        print(f"  latest_run.fresh_imports platforms={list(status_fresh.keys())}")
    else:
        print("  latest_run.fresh_imports: omitted (legacy run or no imports)")

    connected = [
        c.name
        for c in connectors
        if c.status in ("connected", "degraded")
    ]
    print("\n=== QA CHECKLIST (automated portion) ===")
    checks = []
    if latest.status == "succeeded" and connected:
        has_both = all(
            isinstance(fresh.get(p), dict) and fresh.get(p, {}).get("data_run_id")
            for p in connected
        )
        checks.append(("Succeeded run has fresh_imports per connected platform", has_both))
    if status_fresh and isinstance(fresh, dict) and fresh:
        api_match = set(status_fresh.keys()) >= set(fresh.keys())
        checks.append(("Status API fresh_imports matches latest run metadata", api_match))

    sibling_ok = True
    if latest.status == "succeeded" and isinstance(fresh, dict):
        for platform, block in fresh.items():
            if not isinstance(block, dict):
                continue
            dr_id = block.get("data_run_id")
            if dr_id is None:
                continue
            try:
                sibling = DataRun.objects.get(pk=dr_id)
            except DataRun.DoesNotExist:
                sibling_ok = False
                break
            if sibling.metadata.get("triggered_by") != "dcs_score":
                sibling_ok = False
                break
    checks.append(("Fresh import DataRuns exist with triggered_by=dcs_score", sibling_ok))

    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    manual = [
        "Change data in Shopify/Manago without reconnect",
        "Re-run checks with Celery worker running",
        "Confirm worklist/score reflects the change",
        "Negative: Celery down -> Re-run must not false-succeed",
    ]
    print("\nManual steps still required:")
    for step in manual:
        print(f"  - {step}")

    return 0 if all(ok for _, ok in checks) else 2


if __name__ == "__main__":
    sys.exit(main())
