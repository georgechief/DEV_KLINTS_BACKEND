"""PRD-WB-19 — SP-03 detail schema normalise verification."""

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
from dataruns.writebacks.registry import _load_registry, get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.types import WriteIntent


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-19 VERIFICATION (SP-03 DETAIL SCHEMA NORMALISE) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("SP-03")
    if not entry or not entry.get("enabled"):
        return _fail("SP-03 must be enabled in registry.json")
    if not by_id.get("SP-07", {}).get("enabled"):
        return _fail("SP-07 must remain enabled (gate)")
    print("Registry SP-03 enabled; SP-07 still enabled: OK")

    sp03 = get_check_mapping("SP-03")
    if str(sp03.get("template_id") or "") != "T4":
        return _fail("SP-03 template_id must be T4")
    if not sp03.get("requires_consent_namespace_clean"):
        return _fail("SP-03 requires_consent_namespace_clean must be true")
    if sp03.get("irreversible"):
        return _fail("SP-03 must not be irreversible")
    rollback = sp03.get("rollback") or {}
    if str(rollback.get("strategy") or "") != "revert_detail":
        return _fail("SP-03 rollback must be revert_detail")
    contract = sp03.get("format_contract")
    if not isinstance(contract, dict) or "ORDER_NUMBER" not in contract:
        return _fail("SP-03 format_contract must include ORDER_NUMBER")
    ops = sp03.get("operations") or []
    if len(ops) != 1:
        return _fail("SP-03 must have exactly one operation")
    op = ops[0]
    if op.get("op_kind") != "detail_set":
        return _fail("SP-03 op must be detail_set")
    match = (op.get("from_evidence") or {}).get("match") or {}
    if "oneOf" in match:
        return _fail("SP-03 must not use oneOf")
    if match.get("const") != "inconsistent_detail_format":
        return _fail("SP-03 match const must be inconsistent_detail_format")
    entity_key = (op.get("from_evidence") or {}).get("entity_key") or {}
    if entity_key.get("path") != "write_entity_key":
        return _fail("SP-03 entity_key must be write_entity_key")
    if "Data lead" in str(sp03.get("operator_disclosure") or ""):
        return _fail("SP-03 disclosure must not say Data lead")
    if "Klints" not in str(sp03.get("operator_disclosure") or ""):
        return _fail("SP-03 disclosure must mention Klints")
    print("Mapping T4 + revert_detail + format_contract + detail_set: OK")

    probe = WriteIntent(
        check_id="SP-03",
        op_kind="detail_set",
        operation="manago.detail_set.normalize_format",
        target_system="manago",
        entity_type="contact",
        entity_key="a@b.com",
        namespace="native",
        payload={"properties": {"ORDER_NUMBER": "1.0"}},
        before={"ORDER_NUMBER": "1"},
        after={"ORDER_NUMBER": "1.0"},
        rollback_snapshot={"ORDER_NUMBER": "1"},
        rollback_strategy="revert_detail",
    )
    ok, reason = rollback_supported(probe)
    if not ok:
        return _fail(f"revert_detail must be supported for detail_set, got {reason!r}")
    bad = WriteIntent(
        check_id="SP-03",
        op_kind="detail_set",
        operation="x",
        target_system="manago",
        entity_type="contact",
        entity_key="a@b.com",
        namespace="native",
        rollback_strategy="restore_prior_field",
    )
    ok2, reason2 = rollback_supported(bad)
    if ok2 or reason2 != "rollback_strategy_mismatch":
        return _fail("restore_prior_field must mismatch on detail_set")
    print("rollback_strategy revert_detail OK; restore_prior_field rejected: OK")

    if not WritebackAllowedCheck.objects.filter(check_id="SP-03", enabled=True).exists():
        return _fail("WritebackAllowedCheck SP-03 must be seeded enabled")
    print("WritebackAllowedCheck SP-03 seeded: OK")

    _path, sheet = load_possible_sheet()
    rows = [
        r
        for r in sheet
        if isinstance(r, dict)
        and str(r.get("check_id") or "").strip().upper() == "SP-03"
    ]
    if not rows:
        return _fail("Possible sheet missing SP-03 row")
    row = rows[0]
    if str(row.get("write_possible_today") or "") != "yes":
        return _fail("SP-03 write_possible_today must be yes")
    if str(row.get("pack_fix_owner") or "") != "Klints (automated)":
        return _fail("SP-03 pack_fix_owner must be Klints (automated)")
    print("Possible sheet SP-03 yes: OK")

    from dataruns.dcs.segment_join import SP_DOWNLOAD_CONTACT_CAP, SP_SAMPLE

    if SP_SAMPLE != 50:
        return _fail("SP_SAMPLE must remain 50")
    if SP_DOWNLOAD_CONTACT_CAP < SP_SAMPLE:
        return _fail("SP_DOWNLOAD_CONTACT_CAP must be >= SP_SAMPLE (Download fuller)")
    print(f"SP_SAMPLE={SP_SAMPLE}; Download contact cap={SP_DOWNLOAD_CONTACT_CAP}: OK")

    fe_path = os.path.normpath(
        os.path.join(ROOT, "..", "klints_frontend", "src", "lib", "writebacks.ts")
    )
    if os.path.isfile(fe_path):
        text = open(fe_path, encoding="utf-8").read()
        allow = text.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split(
            "] as const"
        )[0]
        if '"SP-03"' not in allow:
            return _fail("FE WRITEBACK_APPROVE_EXECUTABLE must include SP-03")
        print("FE allowlist includes SP-03: OK")
    else:
        print("FE writebacks.ts not found (skip allowlist check)")

    print("\n=== WB-19 VERIFICATION PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
