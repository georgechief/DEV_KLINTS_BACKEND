"""Read-only WB-01 / WB-01B writeback backend verification."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from django.conf import settings

from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.capabilities import list_supported_op_kinds
from dataruns.writebacks.gates import is_writeback_execute_enabled
from dataruns.writebacks.registry import (
    MappingDisabled,
    get_check_mapping,
    list_mapping_entries,
    list_mappings,
)
from tenants.models import Company


def main() -> int:
    company_id = (os.environ.get("VERIFY_COMPANY_ID") or "").strip()
    company = None
    if company_id:
        company = Company.objects.filter(id=company_id).first()
    if company is None:
        company = Company.objects.filter(writeback_execute_enabled=True).first()
    if company is None:
        company = Company.objects.first()
    if company is None:
        print("No company found.")
        return 1

    allowlist = list(
        WritebackAllowedCheck.objects.filter(enabled=True)
        .order_by("check_id")
        .values_list("check_id", flat=True)
    )

    print("=== WB-01 / WB-01B BACKEND VERIFICATION ===")
    print(f"Company: {company.id} ({company.name})")
    print(f"WRITEBACKS_ENABLED={settings.WRITEBACKS_ENABLED}")
    print(f"writeback_execute_enabled={company.writeback_execute_enabled}")
    print(f"DB allowlist={allowlist}")

    entries = list_mapping_entries()
    enabled = [row for row in entries if row.get("enabled")]
    print(f"Registry entries: {len(entries)} total, {len(enabled)} enabled")
    for row in enabled:
        print(f"  enabled: {row.get('check_id')}")

    le04 = next((row for row in entries if row.get("check_id") == "LE-04"), None)
    print(f"LE-04 enabled={bool(le04 and le04.get('enabled'))} (must be False)")
    try:
        get_check_mapping("LE-04")
        print("ERROR: LE-04 get_check_mapping should raise MappingDisabled")
        return 1
    except MappingDisabled:
        print("LE-04 MappingDisabled: OK")

    try:
        shop = get_check_mapping("WB-SHOP-01")
        print(f"WB-SHOP-01 loaded: op={shop['operations'][0]['op_kind']}")
    except Exception as exc:
        print(f"ERROR: WB-SHOP-01 load failed: {exc}")
        return 1

    mappings = list_mappings()
    distinct_kinds = sorted({kind for item in mappings for kind in item.op_kinds})
    print(f"Distinct op kinds in file-backed mappings: {', '.join(distinct_kinds)}")

    kinds = list_supported_op_kinds()
    implemented = [row["op_kind"] for row in kinds if row["adapter_status"] == "implemented"]
    print(f"Implemented op kinds: {', '.join(implemented)}")

    execute_enabled = is_writeback_execute_enabled(company)
    print(f"Company writeback execute eligible: {execute_enabled}")

    print("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
