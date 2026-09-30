"""PRD-WB-17 — CC-01 email consent reconcile plan (Phase A) verification."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.models import WritebackAllowedCheck
from dataruns.writebacks.messages import writeback_execute_denial_detail
from dataruns.writebacks.possible_sheet import load_possible_sheet
from dataruns.writebacks.registry import _load_registry, get_check_mapping, list_mapping_entries


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-17 VERIFICATION (CC-01 CONSENT RECONCILE PLAN — PHASE A) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("CC-01")
    if not entry or not entry.get("enabled"):
        return _fail("CC-01 must be enabled in registry.json")
    if not by_id.get("CC-03", {}).get("enabled"):
        return _fail("CC-03 must remain enabled")
    print("Registry CC-01 enabled; CC-03 still enabled: OK")

    cc01 = get_check_mapping("CC-01")
    if str(cc01.get("template_id") or "") != "T8":
        return _fail("CC-01 template_id must be T8")
    if str(cc01.get("approval_tier") or "") != "batch":
        return _fail("CC-01 approval_tier must be batch")
    if not cc01.get("irreversible"):
        return _fail("CC-01 must be irreversible")
    if cc01.get("requires_consent_namespace_clean"):
        return _fail("CC-01 requires_consent_namespace_clean must be false")
    if str(cc01.get("execute_mode") or "") != "plan_only":
        return _fail("CC-01 execute_mode must be plan_only")
    rollback = cc01.get("rollback") or {}
    if str(rollback.get("strategy") or "") != "none":
        return _fail("CC-01 rollback must be none")
    ops = cc01.get("operations") or []
    if len(ops) != 2:
        return _fail("CC-01 must have exactly two const operations")
    consts = {
        ((o.get("from_evidence") or {}).get("match") or {}).get("const") for o in ops
    }
    if consts != {"out_in", "in_out"}:
        return _fail(f"CC-01 match consts must be out_in+in_out, got {consts!r}")
    for o in ops:
        match = (o.get("from_evidence") or {}).get("match") or {}
        if "oneOf" in match:
            return _fail("CC-01 must not use oneOf (unsupported)")
        if o.get("op_kind") != "contact_upsert":
            return _fail("CC-01 ops must be contact_upsert")
        if "plan_only" not in (o.get("guards") or []):
            return _fail("CC-01 guards must include plan_only")
    disclosure = str(cc01.get("operator_disclosure") or "")
    if "Data lead" not in disclosure:
        return _fail("CC-01 disclosure must mention Data lead")
    if "forceOpt" not in disclosure and "forceOpt" not in disclosure.lower():
        if "forceOptOut" not in disclosure:
            return _fail("CC-01 disclosure must mention forceOpt")
    print("Mapping contact_upsert + plan_only + two const ops + irreversible: OK")

    detail = writeback_execute_denial_detail("cc01_plan_only")
    if "Data lead" not in detail or "forceOpt" not in detail:
        return _fail(f"cc01_plan_only message incomplete: {detail!r}")
    print("messages.cc01_plan_only: OK")

    if WritebackAllowedCheck.objects.filter(check_id="CC-01", enabled=True).exists():
        return _fail("WritebackAllowedCheck CC-01 must NOT be seeded in Phase A")
    print("WritebackAllowedCheck CC-01 absent: OK")

    _path, sheet = load_possible_sheet()
    rows = [
        r
        for r in sheet
        if isinstance(r, dict)
        and str(r.get("check_id") or "").strip().upper() == "CC-01"
    ]
    if not rows:
        return _fail("Possible sheet missing CC-01 row")
    row = rows[0]
    if str(row.get("write_possible_today") or "") != "preview_only":
        return _fail("CC-01 write_possible_today must be preview_only")
    if str(row.get("pack_fix_owner") or "") != "Data lead":
        return _fail("CC-01 pack_fix_owner must be Data lead")
    if "plan_only" not in str(row.get("blocker") or ""):
        return _fail("CC-01 blocker must mention plan_only")
    print("Possible sheet CC-01 preview_only: OK")

    fe_path = os.path.join(
        ROOT,
        "..",
        "klints_frontend",
        "src",
        "lib",
        "writebacks.ts",
    )
    fe_path = os.path.normpath(fe_path)
    if os.path.isfile(fe_path):
        text = open(fe_path, encoding="utf-8").read()
        if '"CC-01"' in text.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split(
            "] as const"
        )[0]:
            return _fail("FE WRITEBACK_APPROVE_EXECUTABLE must NOT include CC-01")
        if 'id === "CC-01"' not in text and "id === 'CC-01'" not in text:
            return _fail("FE writebackNonExecutableHonesty must special-case CC-01")
        print("FE allowlist excludes CC-01; honesty case present: OK")
    else:
        print("FE writebacks.ts not found (skip allowlist check)")

    print("\n=== WB-17 PHASE A VERIFICATION PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
