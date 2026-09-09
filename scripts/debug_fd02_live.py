"""Live FD-02 evaluation + latest stored DCS result."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.db_context import build_foundation_context_for_company
from dataruns.dcs.executors.foundation import evaluate_fd_02, evaluate_foundation_gates
from dataruns.models import DataRun
from tenants.models import Company, Connector


def _fd02_from_results(results) -> dict | None:
    if not isinstance(results, list):
        return None
    for row in results:
        if isinstance(row, dict) and row.get("check_id") == "FD-02":
            return row
    return None


def main() -> None:
    connector = (
        Connector.objects.filter(name="shopify", status="connected")
        .order_by("-updated_at")
        .first()
    )
    if connector is None:
        print("No connected Shopify connector.")
        return

    company = connector.company
    print(f"company={company.id} connector_status={connector.status}")

    ctx, _resolved = build_foundation_context_for_company(
        company=company,
        tenant_id=str(company.tenant_id),
        run_id="debug-live",
        live_revalidate=True,
    )
    fd02 = evaluate_fd_02(ctx)
    print(f"\nLIVE evaluate_fd_02: {fd02.status}")
    print(f"message: {fd02.message}")
    if fd02.evidence:
        print("evidence:", json.dumps(fd02.evidence[0].value, indent=2))

    gates = {g.check_id: g.status for g in evaluate_foundation_gates(ctx)}
    print("all foundation gates:", gates)

    print("\n=== Latest DCS-related DataRuns ===")
    runs = (
        DataRun.objects.filter(metadata__company_id=str(company.id))
        .order_by("-created_at")[:10]
    )
    for run in runs:
        meta = run.metadata or {}
        name = run.name or ""
        if "dcs" not in name.lower() and meta.get("kind") not in {
            "dcs_run",
            "dcs_orchestrate",
            "dcs_sweep",
        }:
            continue
        results = meta.get("check_results") or meta.get("results") or []
        stored = _fd02_from_results(results)
        print(f"run={run.id} name={name} status={run.status} created={run.created_at}")
        if stored:
            print(f"  stored FD-02: {stored.get('status')} — {stored.get('message')}")
            for ev in stored.get("evidence") or []:
                if isinstance(ev, dict) and "scope" in str(ev.get("locator", "")):
                    print("  stored evidence:", json.dumps(ev.get("value"), indent=2))


if __name__ == "__main__":
    main()
