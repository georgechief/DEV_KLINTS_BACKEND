"""PRD-WB-08 — catalogue wave 2 verification (LE-01 ship; SP-01 not MVP1 42)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.possible_sheet import load_possible_sheet
from dataruns.writebacks.registry import (
    MappingDisabled,
    _load_registry,
    get_check_mapping,
    list_mapping_entries,
)


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-08 VERIFICATION (LE-01; SP-01 out of MVP1 42) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }

    le01_entry = by_id.get("LE-01")
    if not le01_entry or not le01_entry.get("enabled"):
        return _fail("LE-01 must be enabled in registry.json")
    print("Registry LE-01 enabled: OK")

    sp01_entry = by_id.get("SP-01")
    if sp01_entry and sp01_entry.get("enabled"):
        return _fail("SP-01 must stay disabled (not in MVP1 42)")
    try:
        get_check_mapping("SP-01")
        return _fail("SP-01 get_check_mapping should raise MappingDisabled")
    except MappingDisabled:
        print("SP-01 MappingDisabled (not MVP1 42): OK")

    import json
    from pathlib import Path

    sp01_path = (
        Path(__file__).resolve().parents[1]
        / "dataruns"
        / "writebacks"
        / "mappings"
        / "SP-01.tag_consolidation.v1.json"
    )
    sp01_spec = json.loads(sp01_path.read_text(encoding="utf-8"))
    if sp01_spec.get("enabled") or (sp01_spec.get("operations") or []):
        return _fail("SP-01 mapping must stay stub: enabled=false and operations=[]")
    print("SP-01 mapping stub (ops empty): OK")

    for check_id in ("LE-04", "CI-03"):
        entry = by_id.get(check_id)
        if entry and entry.get("enabled"):
            return _fail(f"{check_id} must stay disabled")
        try:
            get_check_mapping(check_id)
            return _fail(f"{check_id} get_check_mapping should raise MappingDisabled")
        except MappingDisabled:
            print(f"{check_id} MappingDisabled: OK")

    le01 = get_check_mapping("LE-01")
    if not le01.get("irreversible"):
        return _fail("LE-01 must be irreversible")
    le_ops = le01.get("operations") or []
    if not le_ops or le_ops[0].get("op_kind") != "event_ingest":
        return _fail("LE-01 must have event_ingest operation")
    match = ((le_ops[0].get("from_evidence") or {}).get("match") or {})
    if match.get("const") != "shopify_only":
        return _fail("LE-01 match.const must be shopify_only")
    print("LE-01 mapping: event_ingest shopify_only irreversible: OK")

    allowlisted = set(
        WritebackAllowedCheck.objects.filter(enabled=True).values_list(
            "check_id", flat=True
        )
    )
    if "LE-01" not in allowlisted:
        return _fail("LE-01 missing from WritebackAllowedCheck (run migrate)")
    print("Allowlist LE-01: OK")
    for check_id in ("SP-01", "LE-04", "CI-03"):
        if check_id in allowlisted:
            return _fail(f"{check_id} must not be allowlisted")
    print("SP-01 / LE-04 / CI-03 not allowlisted: OK")

    _source, rows = load_possible_sheet()
    by_check = {row["check_id"]: row for row in rows}
    le_row = by_check.get("LE-01")
    sp_row = by_check.get("SP-01")
    if not le_row or le_row.get("write_possible_today") != "yes":
        return _fail("possible sheet LE-01 write_possible_today must be yes")
    if le_row.get("rollback_possible_today") != "limited":
        return _fail("possible sheet LE-01 rollback_possible_today must be limited")
    if not le_row.get("registry_enabled"):
        return _fail("possible sheet LE-01 registry_enabled must be true")
    if not sp_row or sp_row.get("write_possible_today") != "disabled":
        return _fail("possible sheet SP-01 must be disabled (not MVP1 42)")
    print("Possible sheet LE-01 yes / SP-01 disabled: OK")

    fe_writebacks = os.path.join(
        os.path.dirname(ROOT), "klints_frontend", "src", "lib", "writebacks.ts"
    )
    if os.path.isfile(fe_writebacks):
        text = open(fe_writebacks, encoding="utf-8").read()
        if '"LE-01"' not in text:
            return _fail("FE writebacks.ts missing LE-01 allowlist entry")
        # SP-01 must not be on the FE approve allowlist
        allow_block = text.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split(
            "] as const"
        )[0]
        if '"SP-01"' in allow_block:
            return _fail("FE approve allowlist must not include SP-01")
        for needle in (
            "writebackIrreversibleHonestyNotice",
            "PURCHASE event backfill",
        ):
            if needle not in text:
                return _fail(f"FE writebacks.ts missing {needle!r}")
        print("FE LE-01 allowlist + disclosure; SP-01 absent: OK")
    else:
        print("FE writebacks.ts not found (skip optional FE string check)")

    print("\nWB-08 verification passed (LE-01 only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
