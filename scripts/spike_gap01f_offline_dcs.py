"""
GAP-01 Slice F Phase 0 spike — prove offline DCS bypass (no live Shopify/Manago).

Run from klints_backend with venv:
  .venv/Scripts/python.exe scripts/spike_gap01f_offline_dcs.py

Patches ``run_import`` with the bootstrap test helper (same pattern as
``test_dcs_fresh_import_before_score``). Deletes the spike tenant when done.
"""
from __future__ import annotations

import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from django.core.management import call_command

from dataruns.dcs.enqueue import DCS_SCORE_KIND
from dataruns.dcs.fresh_import import refresh_connected_platforms_for_dcs
from dataruns.dcs.orchestrate import run_dcs_pipeline
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.models import CheckMaster, DataRun
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant, User
from tenants.tests.bootstrap_test_helpers import successful_run_import_side_effect

SPIKE_SLUG = f"gap01f-spike-{uuid4().hex[:8]}"


def main() -> int:
    if CheckMaster.objects.count() == 0:
        print("Seeding DCS master (empty CheckMaster)...")
        call_command("seed_dcs_master", verbosity=0)

    print(f"Creating spike tenant slug={SPIKE_SLUG} ...")
    tenant = Tenant.objects.create(name="GAP-01F Spike", slug=SPIKE_SLUG)
    company = Company.objects.create(
        tenant=tenant,
        name="GAP-01F Spike Co",
        domain=f"{SPIKE_SLUG}.test",
    )
    User.objects.create_user(
        email=f"admin@{SPIKE_SLUG}.test",
        password="TestPass123!",
        name="Spike Admin",
        tenant=tenant,
        role=User.Role.ADMIN,
        email_verified=True,
        is_active=True,
    )
    Connector.objects.create(
        company=company,
        name="shopify",
        type="ecommerce",
        status="connected",
        config=encrypt_config(
            {
                "shop_domain": f"{SPIKE_SLUG}.myshopify.com",
                "access_token": "spike-token",
            }
        ),
    )
    Connector.objects.create(
        company=company,
        name="manago_ai",
        type="crm",
        status="connected",
        config=encrypt_config(
            {
                "client_id": "spike-client",
                "api_secret": "spike-secret",
            }
        ),
    )

    dcs_run = DataRun.objects.create(
        tenant=tenant,
        name="dcs-score",
        status=DataRun.Status.PENDING,
        metadata={
            "kind": DCS_SCORE_KIND,
            "company_id": str(company.id),
            "triggered_by": "gap01f_phase0_spike",
            "erp_in_scope": False,
            "live_revalidate": False,
        },
    )

    print("Running DCS pipeline with offline run_import patch...")
    try:
        with ExitStack() as stack:
            stack.enter_context(patch("dataruns.dcs.fresh_import._ensure_shopify_token"))
            stack.enter_context(
                patch(
                    "dataruns.architecture.enqueue.maybe_enqueue_architecture_after_dcs"
                )
            )
            stack.enter_context(patch("dataruns.dcs.orchestrate._audit_dcs_completed"))
            stack.enter_context(patch("dataruns.dcs.orchestrate._notify_dcs_completed"))
            stack.enter_context(
                patch("tenants.manago_topology_service.ensure_manago_primary_owner")
            )
            stack.enter_context(
                patch(
                    "dataruns.dcs.fresh_import.run_import",
                    side_effect=successful_run_import_side_effect,
                )
            )
            stack.enter_context(
                patch(
                    "dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs",
                    wraps=refresh_connected_platforms_for_dcs,
                )
            )
            result = run_dcs_pipeline(dcs_run)
    except Exception as exc:  # noqa: BLE001
        print(f"SPIKE FAIL: {exc}")
        _cleanup(tenant)
        return 1

    dcs_run.refresh_from_db()
    headline = (dcs_run.metadata or {}).get("dcs_run", {}).get("headline_score")
    run_state = (dcs_run.metadata or {}).get("dcs_run", {}).get("run_state")
    status = resolve_dcs_app_status(company=company)
    latest = (status or {}).get("latest_run") or {}

    print("\n=== GAP-01F Phase 0 spike result ===")
    print(f"ok:              {result.get('ok')}")
    print(f"data_run status: {dcs_run.status}")
    print(f"headline_score:  {headline}")
    print(f"run_state:       {run_state}")
    print(f"fresh_imports:   {list((dcs_run.metadata or {}).get('fresh_imports') or {})}")
    print(f"app latest_run:  {latest.get('run_state')} / {latest.get('headline_score')}")

    ok = bool(result.get("ok")) and dcs_run.status == DataRun.Status.SUCCEEDED
    _cleanup(tenant)
    if ok:
        print("\nSPIKE PASS — offline DCS bypass works (no live connector HTTP).")
        return 0
    print("\nSPIKE FAIL — pipeline did not succeed.")
    return 1


def _cleanup(tenant: Tenant) -> None:
    print(f"Cleaning spike tenant {tenant.slug}...")
    tenant.delete()


if __name__ == "__main__":
    sys.exit(main())
