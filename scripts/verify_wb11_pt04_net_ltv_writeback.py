"""PRD-WB-11 — PT-04 klints_net_ltv writeback verification."""

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

from dataruns.dcs.segment_join import clear_klints_owned_keys_cache, is_klints_owned_detail
from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.possible_sheet import load_possible_sheet
from dataruns.writebacks.registry import _load_registry, get_check_mapping, list_mapping_entries


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-11 VERIFICATION (PT-04 klints_net_ltv) ===\n")

    _load_registry.cache_clear()
    clear_klints_owned_keys_cache()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("PT-04")
    if not entry or not entry.get("enabled"):
        return _fail("PT-04 must be enabled in registry.json")
    print("Registry PT-04 enabled: OK")

    pt04 = get_check_mapping("PT-04")
    if pt04.get("irreversible"):
        return _fail("PT-04 must not be irreversible")
    if not pt04.get("requires_consent_namespace_clean"):
        return _fail("PT-04 must require_consent_namespace_clean")
    if (pt04.get("rollback") or {}).get("strategy") != "revert_detail":
        return _fail("PT-04 rollback must be revert_detail")
    ops = pt04.get("operations") or []
    if not ops or ops[0].get("op_kind") != "detail_set":
        return _fail("PT-04 must use detail_set")
    match_const = (
        ((ops[0].get("from_evidence") or {}).get("match") or {}).get("const")
    )
    if match_const != "net_overstatement":
        return _fail(f"PT-04 match const must be net_overstatement, got {match_const!r}")
    fields = (ops[0].get("from_evidence") or {}).get("fields") or {}
    if (fields.get("detail_key") or {}).get("const") != "klints_net_ltv":
        return _fail("PT-04 detail_key must be klints_net_ltv")
    if (fields.get("detail_value") or {}).get("path") != "shopify_net":
        return _fail("PT-04 detail_value must path shopify_net")
    disclosure = str(pt04.get("operator_disclosure") or "")
    if "may not make PT-04 PASS" in disclosure:
        return _fail("PT-04 disclosure must not say may not make PT-04 PASS (WB-12)")
    if "re-run DCS" not in disclosure or "PASS" not in disclosure:
        return _fail("PT-04 disclosure must say re-run DCS / PASS when stamp matches (WB-12)")
    print("Mapping detail_set klints_net_ltv + WB-12 PASS disclosure: OK")

    if not is_klints_owned_detail("klints_net_ltv"):
        return _fail("klints_net_ltv must be owned when PT-04 enabled")
    print("Owned key klints_net_ltv: OK")

    from dataruns.writebacks.capabilities import capability_batch_max

    cap = capability_batch_max("RESTV2.CONTACT.UPSERT") or 1000
    if min(int(cap), 1000) < 50:
        return _fail("PT-04 default row cap depends on UPSERT batch_max >= 50")
    print(f"PT-04 default row ceiling (UPSERT batch_max={cap}): OK")

    if not WritebackAllowedCheck.objects.filter(check_id="PT-04", enabled=True).exists():
        return _fail("WritebackAllowedCheck PT-04 missing — run migrate (0039)")
    print("Allowlist PT-04: OK")

    _source, sheet = load_possible_sheet()
    pt04_rows = [r for r in sheet if str(r.get("check_id") or "").upper() == "PT-04"]
    if not pt04_rows:
        return _fail("possible sheet missing PT-04 row")
    row = pt04_rows[0]
    if row.get("write_possible_today") != "yes":
        return _fail("PT-04 write_possible_today must be yes")
    if row.get("rollback_possible_today") != "yes":
        return _fail("PT-04 rollback_possible_today must be yes")
    if row.get("op_kind") != "detail_set":
        return _fail("PT-04 sheet op_kind must be detail_set")
    print("Possible sheet PT-04 yes/yes detail_set: OK")

    fe_path = Path(ROOT).parent / "klints_frontend" / "src" / "lib" / "writebacks.ts"
    if fe_path.exists():
        text = fe_path.read_text(encoding="utf-8")
        if '"PT-04"' not in text and "'PT-04'" not in text:
            return _fail("FE writebacks.ts missing PT-04 allowlist entry")
        print("FE allowlist PT-04: OK")
    else:
        print("FE writebacks.ts not found (skip)")

    mapping_path = (
        Path(ROOT)
        / "dataruns"
        / "writebacks"
        / "mappings"
        / "PT-04.net_ltv.v1.json"
    )
    spec = json.loads(mapping_path.read_text(encoding="utf-8"))
    if spec.get("check_id") != "PT-04" or not spec.get("enabled"):
        return _fail("PT-04 mapping file invalid")
    if "event_correct" in json.dumps(spec):
        return _fail("PT-04 must not use event_correct")
    print("Mapping file: OK")

    print("\nWB-11 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
