"""PRD-WB-20 — PT-03 catalog completeness reconcile verification."""

from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from dataruns.writebacks.capabilities import (
    capability_allows_execute,
    capability_status,
    list_supported_op_kinds,
)
from dataruns.writebacks.possible_sheet import load_possible_sheet
from dataruns.writebacks.registry import _load_registry, get_check_mapping, list_mapping_entries
from dataruns.writebacks.rollback_strategy import rollback_supported
from dataruns.writebacks.types import WriteIntent


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def main() -> int:
    print("=== WB-20 VERIFICATION (PT-03 CATALOG RECONCILE) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("PT-03")
    if not entry or not entry.get("enabled"):
        return _fail("PT-03 must be enabled in registry.json")
    print("Registry PT-03 enabled: OK")

    pt03 = get_check_mapping("PT-03")
    if str(pt03.get("template_id") or "") != "T7":
        return _fail("PT-03 template_id must be T7")
    if not pt03.get("irreversible"):
        return _fail("PT-03 must be irreversible")
    if pt03.get("archive_enabled"):
        return _fail("PT-03 archive_enabled must be false until Loom")
    rollback = pt03.get("rollback") or {}
    if str(rollback.get("strategy") or "") != "none":
        return _fail("PT-03 rollback must be none")
    ops = pt03.get("operations") or []
    if len(ops) != 2:
        return _fail("PT-03 must have exactly two operations")
    if any(op.get("op_kind") != "product_upsert" for op in ops):
        return _fail("PT-03 ops must be product_upsert")
    if any(op.get("namespace") != "native" for op in ops):
        return _fail("PT-03 namespace must be native")
    print("Mapping T7 + irreversible + archive_enabled=false: OK")

    if capability_status("RESTV2.PRODUCT.IMPORT") != "DISCOVERY_REQUIRED":
        return _fail("PRODUCT.IMPORT must remain DISCOVERY_REQUIRED until Loom")
    if capability_allows_execute("RESTV2.PRODUCT.IMPORT"):
        return _fail("PRODUCT.IMPORT must not allow execute yet")
    kinds = {row["op_kind"]: row["adapter_status"] for row in list_supported_op_kinds()}
    if kinds.get("product_upsert") != "implemented":
        return _fail("product_upsert must be implemented in capabilities.py")
    print("Capability DISCOVERY_REQUIRED; product_upsert implemented: OK")

    probe = WriteIntent(
        check_id="PT-03",
        op_kind="product_upsert",
        operation="x",
        target_system="manago",
        entity_type="product",
        entity_key="1",
        namespace="native",
        rollback_strategy="none",
    )
    ok, reason = rollback_supported(probe)
    if ok or reason != "rollback_not_supported":
        return _fail(f"rollback none must be unsupported, got {ok} {reason}")
    print("rollback none -> not supported: OK")

    _path, sheet = load_possible_sheet()
    rows = [
        r
        for r in sheet
        if isinstance(r, dict)
        and str(r.get("check_id") or "").strip().upper() == "PT-03"
    ]
    if not rows:
        return _fail("Possible sheet missing PT-03 row")
    row = rows[0]
    if str(row.get("write_possible_today") or "") != "no":
        return _fail("PT-03 write_possible_today must be no until Loom")
    if str(row.get("pack_fix_owner") or "") != "Klints (automated)":
        return _fail("PT-03 pack_fix_owner must be Klints (automated)")
    print("Possible sheet PT-03 Preview/no-execute: OK")

    fe_path = os.path.normpath(
        os.path.join(ROOT, "..", "klints_frontend", "src", "lib", "writebacks.ts")
    )
    if os.path.isfile(fe_path):
        text = open(fe_path, encoding="utf-8").read()
        allow = text.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split(
            "] as const"
        )[0]
        if '"PT-03"' in allow:
            return _fail(
                "FE WRITEBACK_APPROVE_EXECUTABLE must NOT include PT-03 until CONFIRMED_*"
            )
        print("FE allowlist correctly omits PT-03 until Loom: OK")
    else:
        print("FE writebacks.ts not found (skip allowlist check)")

    print("\n=== WB-20 VERIFICATION PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
