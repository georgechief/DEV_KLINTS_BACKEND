"""PRD-WB-10 — LE-09 return/cancellation writeback verification."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.possible_sheet import load_possible_sheet
from dataruns.writebacks.registry import _load_registry, get_check_mapping, list_mapping_entries


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-10 VERIFICATION (LE-09 RETURN/CANCELLATION) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("LE-09")
    if not entry or not entry.get("enabled"):
        return _fail("LE-09 must be enabled in registry.json")
    print("Registry LE-09 enabled: OK")

    le09 = get_check_mapping("LE-09")
    if not le09.get("irreversible"):
        return _fail("LE-09 must be irreversible")
    ops = le09.get("operations") or []
    if not ops or ops[0].get("op_kind") != "event_ingest":
        return _fail("LE-09 must use event_ingest")
    match_const = (
        ((ops[0].get("from_evidence") or {}).get("match") or {}).get("const")
    )
    if match_const != "shopify_only_return":
        return _fail(f"LE-09 match const must be shopify_only_return, got {match_const!r}")
    print("Mapping match shopify_only_return + irreversible: OK")

    if not WritebackAllowedCheck.objects.filter(check_id="LE-09", enabled=True).exists():
        return _fail("WritebackAllowedCheck LE-09 missing — run migrate (0038)")
    print("Allowlist LE-09: OK")

    _source, sheet = load_possible_sheet()
    le09_rows = [r for r in sheet if str(r.get("check_id") or "").upper() == "LE-09"]
    if not le09_rows:
        return _fail("possible sheet missing LE-09 row")
    row = le09_rows[0]
    if row.get("write_possible_today") != "yes":
        return _fail("LE-09 write_possible_today must be yes")
    if row.get("rollback_possible_today") != "limited":
        return _fail("LE-09 rollback_possible_today must be limited")
    print("Possible sheet LE-09 yes/limited: OK")

    fe_path = Path(ROOT).parent / "klints_frontend" / "src" / "lib" / "writebacks.ts"
    if fe_path.exists():
        text = fe_path.read_text(encoding="utf-8")
        if '"LE-09"' not in text and "'LE-09'" not in text:
            return _fail("FE writebacks.ts missing LE-09 allowlist entry")
        print("FE allowlist LE-09: OK")
    else:
        print("FE writebacks.ts not found (skip)")

    mapping_path = (
        Path(ROOT)
        / "dataruns"
        / "writebacks"
        / "mappings"
        / "LE-09.event_backfill.v1.json"
    )
    spec = json.loads(mapping_path.read_text(encoding="utf-8"))
    if spec.get("check_id") != "LE-09" or not spec.get("enabled"):
        return _fail("LE-09 mapping file invalid")
    print("Mapping file: OK")

    print("\nWB-10 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
