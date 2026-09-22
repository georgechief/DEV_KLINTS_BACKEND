"""PRD-WB-09 — SP-07 namespace clean verification."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.dcs.segment_join import is_klints_owned_detail
from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.possible_sheet import load_possible_sheet
from dataruns.writebacks.registry import _load_registry, get_check_mapping, list_mapping_entries


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-09 VERIFICATION (SP-07 namespace clean) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("SP-07")
    if not entry or not entry.get("enabled"):
        return _fail("SP-07 must be enabled in registry.json")
    print("Registry SP-07 enabled: OK")

    mapping = get_check_mapping("SP-07")
    if mapping.get("requires_consent_namespace_clean"):
        return _fail("SP-07 must have requires_consent_namespace_clean=false")
    if mapping.get("irreversible"):
        return _fail("SP-07 must not be irreversible")
    rollback = mapping.get("rollback") or {}
    if rollback.get("strategy") != "reverse_rename_map":
        return _fail("SP-07 rollback.strategy must be reverse_rename_map")
    ops = mapping.get("operations") or []
    kinds = {op.get("op_kind") for op in ops if isinstance(op, dict)}
    if kinds != {"detail_set", "tag_add"}:
        return _fail(f"SP-07 ops must be detail_set + tag_add, got {kinds}")
    entity_key = (ops[0].get("from_evidence") or {}).get("entity_key") or {}
    if entity_key.get("path") != "entity_key":
        return _fail("SP-07 entity_key must use path entity_key (email or contactId)")
    print("SP-07 mapping (no self-preflight, reverse_rename_map): OK")

    from dataruns.writebacks.capabilities import capability_batch_max

    cap = capability_batch_max("RESTV2.CONTACT.UPSERT") or 1000
    if min(int(cap), 1000) < 100:
        return _fail("SP-07 default row cap depends on UPSERT batch_max >= 100")
    print(f"SP-07 default row ceiling (UPSERT batch_max={cap}): OK")

    if not is_klints_owned_detail("klints_backfill"):
        return _fail("owned allowlist missing klints_backfill")
    if not is_klints_owned_detail("klints_consent_evidence"):
        return _fail("owned allowlist missing klints_consent_evidence")
    if not is_klints_owned_detail("klints_net_ltv"):
        return _fail("klints_net_ltv must be owned when PT-04 mapping enabled (WB-11)")
    print("Owned allowlist (backfill + consent_evidence + net_ltv): OK")

    allowlisted = set(
        WritebackAllowedCheck.objects.filter(enabled=True).values_list(
            "check_id", flat=True
        )
    )
    if "SP-07" not in allowlisted:
        return _fail("SP-07 missing from WritebackAllowedCheck (run migrate)")
    print("Allowlist SP-07: OK")

    _source, rows = load_possible_sheet()
    sp_rows = [r for r in rows if r.get("check_id") == "SP-07"]
    if len(sp_rows) < 2:
        return _fail("possible sheet must have SP-07 detail + tag rows")
    for row in sp_rows:
        if row.get("write_possible_today") != "yes":
            return _fail("possible sheet SP-07 write_possible_today must be yes")
        if row.get("rollback_possible_today") != "yes":
            return _fail("possible sheet SP-07 rollback_possible_today must be yes")
        if not row.get("registry_enabled"):
            return _fail("possible sheet SP-07 registry_enabled must be true")
    print("Possible sheet SP-07: OK")

    fe_writebacks = os.path.join(
        os.path.dirname(ROOT), "klints_frontend", "src", "lib", "writebacks.ts"
    )
    if os.path.isfile(fe_writebacks):
        text = open(fe_writebacks, encoding="utf-8").read()
        allow_block = text.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split(
            "] as const"
        )[0]
        if '"SP-07"' not in allow_block:
            return _fail("FE writebacks.ts missing SP-07 allowlist entry")
        print("FE SP-07 allowlist: OK")
    else:
        print("FE writebacks.ts not found (skip optional FE string check)")

    print("\nWB-09 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
