"""Read-only WB-01 writeback backend verification."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from django.conf import settings

from dataruns.writebacks.capabilities import list_supported_op_kinds
from dataruns.writebacks.registry import list_mapping_entries, list_mappings
from tenants.models import Company

COMPANY_ID = "772587ce-497a-47db-8ace-c2eeb0e81d94"


def main() -> int:
    company = Company.objects.filter(id=COMPANY_ID).first() or Company.objects.first()
    if company is None:
        print("No company found.")
        return 1

    print("=== WB-01 BACKEND VERIFICATION ===")
    print(f"Company: {company.id} ({company.name})")
    print(f"WRITEBACKS_ENABLED={settings.WRITEBACKS_ENABLED}")
    print(f"WRITEBACK_SANDBOX_COMPANY_IDS={settings.WRITEBACK_SANDBOX_COMPANY_IDS}")
    print(f"WRITEBACK_CHECK_ALLOWLIST={settings.WRITEBACK_CHECK_ALLOWLIST}")

    entries = list_mapping_entries()
    enabled = [row for row in entries if row.get("enabled")]
    print(f"Registry entries: {len(entries)} total, {len(enabled)} enabled")
    for row in enabled:
        print(f"  enabled: {row.get('check_id')}")

    mappings = list_mappings()
    distinct_kinds = sorted({kind for item in mappings for kind in item.op_kinds})
    print(f"Distinct op kinds in file-backed mappings: {', '.join(distinct_kinds)}")

    kinds = list_supported_op_kinds()
    implemented = [row["op_kind"] for row in kinds if row["adapter_status"] == "implemented"]
    print(f"Implemented op kinds: {', '.join(implemented)}")

    sandbox = str(company.id) in [str(value) for value in settings.WRITEBACK_SANDBOX_COMPANY_IDS]
    print(f"Company sandbox execute eligible: {sandbox}")

    print("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
