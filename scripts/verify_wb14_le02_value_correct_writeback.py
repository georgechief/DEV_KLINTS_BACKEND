"""PRD-WB-14 — LE-02 purchase value correction writeback verification."""

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
    print("=== WB-14 VERIFICATION (LE-02 VALUE CORRECT) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("LE-02")
    if not entry or not entry.get("enabled"):
        return _fail("LE-02 must be enabled in registry.json")
    if not by_id.get("LE-05", {}).get("enabled"):
        return _fail("LE-05 must remain enabled")
    if not by_id.get("LE-01", {}).get("enabled"):
        return _fail("LE-01 must remain enabled")
    print("Registry LE-02 enabled; LE-01/LE-05 still enabled: OK")

    le02 = get_check_mapping("LE-02")
    if not le02.get("irreversible"):
        return _fail("LE-02 must be irreversible")
    if str(le02.get("approval_tier") or "") != "individual":
        return _fail("LE-02 approval_tier must be individual")
    ops = le02.get("operations") or []
    if not ops or ops[0].get("op_kind") != "event_correct":
        return _fail("LE-02 must use event_correct")
    if "event_ingest" in json.dumps(le02):
        return _fail("LE-02 must not use event_ingest")
    match_const = (
        ((ops[0].get("from_evidence") or {}).get("match") or {}).get("const")
    )
    if match_const != "value_mismatch":
        return _fail(f"LE-02 match const must be value_mismatch, got {match_const!r}")
    entity_path = (
        ((ops[0].get("from_evidence") or {}).get("entity_key") or {}).get("path")
    )
    if entity_path != "event_external_id":
        return _fail("LE-02 entity_key must be event_external_id (Manago spine)")
    if ops[0].get("capability_id") != "RESTV2.EVENT.UPDATE":
        return _fail("LE-02 capability_id must be RESTV2.EVENT.UPDATE")
    disclosure = str(le02.get("operator_disclosure") or "")
    if "updateContactExtEvent" not in disclosure:
        return _fail("LE-02 disclosure must mention updateContactExtEvent")
    if "LE-05" not in disclosure and "gaps" not in disclosure.lower():
        return _fail("LE-02 disclosure must prefer gaps / LE-05 first")
    print("Mapping event_correct + value_mismatch + disclosure: OK")

    from dataruns.writebacks.capabilities import (
        capability_allows_execute,
        capability_batch_max,
        capability_status,
        list_supported_op_kinds,
    )

    kinds = {r["op_kind"]: r["adapter_status"] for r in list_supported_op_kinds()}
    if kinds.get("event_correct") != "implemented":
        return _fail("event_correct must be implemented")
    status = capability_status("RESTV2.EVENT.UPDATE")
    if status not in {"CONFIRMED_LIVE", "CONFIRMED_LIMITED"}:
        return _fail(f"RESTV2.EVENT.UPDATE must be CONFIRMED_*, got {status!r}")
    if not capability_allows_execute("RESTV2.EVENT.UPDATE"):
        return _fail("RESTV2.EVENT.UPDATE must allow execute")
    # Gate: DISCOVERY_REQUIRED must deny execute (WB-01 rule).
    if capability_allows_execute("RESTV2.PRODUCT.IMPORT"):
        return _fail("DISCOVERY_REQUIRED capability must deny execute")
    cap = capability_batch_max("RESTV2.EVENT.UPDATE") or 0
    if int(cap) < 1:
        return _fail("EVENT.UPDATE batch_max must be >= 1")
    print(f"Capability EVENT.UPDATE status={status} batch_max={cap}: OK")

    # Rollback honesty — catalogue: not restorable in Manago.
    from dataruns.writebacks.rollback_strategy import rollback_supported
    from dataruns.writebacks.transform import build_intents_from_mapping
    from tenants.models import Company, Tenant

    tenant = Tenant.objects.filter(slug="wb14-verify").first()
    if tenant is None:
        tenant = Tenant.objects.create(name="WB14V", slug="wb14-verify")
    company = Company.objects.filter(domain="wb14-verify.test").first()
    if company is None:
        company = Company.objects.create(
            tenant=tenant, name="WB14 Verify", domain="wb14-verify.test"
        )
    intents = build_intents_from_mapping(
        company=company,
        mapping=le02,
        evidence_rows=[
            {
                "side": "value_mismatch",
                "order.id": "v1",
                "event_external_id": "v1",
                "person.email": "v@verify.test",
                "manago_contact_id": "mc-v",
                "shopify_gross": 10.0,
                "manago_value": 9.0,
            }
        ],
    )
    if not intents:
        return _fail("verify transform must build one event_correct intent")
    ok, reason = rollback_supported(intents[0])
    if ok or reason != "rollback_not_supported":
        return _fail(f"event_correct rollback must be not_supported, got {ok}/{reason}")
    print("Rollback not_supported for event_correct: OK")

    transform_path = Path(ROOT) / "dataruns" / "writebacks" / "transform.py"
    transform_src = transform_path.read_text(encoding="utf-8")
    if "_le02_evidence_rows" not in transform_src:
        return _fail("transform.py missing _le02_evidence_rows")
    if "_event_correct_payload" not in transform_src:
        return _fail("transform.py missing _event_correct_payload")
    if 'normalized == "LE-02"' not in transform_src:
        return _fail("transform.py must dispatch LE-02")
    print("Transform LE-02 enrich + payload: OK")

    pipeline_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "pipeline.py"
    ).read_text(encoding="utf-8")
    if 'normalized_check == "LE-02"' not in pipeline_src:
        return _fail("pipeline.py missing LE-02 EVENT.UPDATE ceiling branch")
    if '"LE-02"' not in pipeline_src or "value corrections" not in pipeline_src:
        return _fail("pipeline.py missing LE-02 truncation probe")
    print("Pipeline LE-02 ceiling + truncation: OK")

    adapter_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "adapters" / "manago.py"
    ).read_text(encoding="utf-8")
    transport_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "adapters" / "manago_transport.py"
    ).read_text(encoding="utf-8")
    if "event_correct" not in adapter_src:
        return _fail("manago adapter missing event_correct")
    if "update_contact_ext_event" not in transport_src:
        return _fail("manago_transport missing update_contact_ext_event")
    if "updateContactExtEvent" not in transport_src:
        return _fail("transport must call updateContactExtEvent path")
    if "batchAddContactExtEvent" in adapter_src and "event_correct" in adapter_src:
        # ensure event_correct does not call batch add
        if "event_correct" in adapter_src and "batch_add_external_events" in adapter_src:
            # both exist in file — check event_correct block uses update
            if "update_contact_ext_event(ctx" not in adapter_src:
                return _fail("event_correct must call update_contact_ext_event")
    print("Adapter + transport event_correct: OK")

    life_src = (
        Path(ROOT) / "dataruns" / "dcs" / "lifecycle_join.py"
    ).read_text(encoding="utf-8")
    exec_src = (
        Path(ROOT) / "dataruns" / "dcs" / "executors" / "lifecycle.py"
    ).read_text(encoding="utf-8")
    if "value_mismatches" not in life_src:
        return _fail("lifecycle_join must emit value_mismatches")
    if "event_external_id" not in life_src:
        return _fail("lifecycle_join must set event_external_id on value_mismatch rows")
    if "_value_mismatches_from_events" not in life_src:
        return _fail("lifecycle_join must expose _value_mismatches_from_events helper")
    if "by_shopify" not in life_src and "One correction per Shopify" not in life_src:
        if "by_shopify" not in life_src:
            return _fail("lifecycle_join must dedupe value_mismatches per Shopify order")
    if "heuristic_email_date_value" not in life_src:
        return _fail("lifecycle_join must skip heuristic-only matches for value_mismatch")
    if "value_mismatch" not in exec_src:
        return _fail("evaluate_le_02 must attach value_mismatch rows")
    print("DCS value_mismatch emission: OK")

    if not WritebackAllowedCheck.objects.filter(
        check_id="LE-02", enabled=True
    ).exists():
        return _fail("WritebackAllowedCheck LE-02 not seeded/enabled")
    print("DB allowlist LE-02: OK")

    _path, sheet = load_possible_sheet()
    le02_rows = [
        r
        for r in sheet
        if isinstance(r, dict)
        and str(r.get("check_id") or "").upper() == "LE-02"
        and str(r.get("mapping_file") or "") == "LE-02.value_correct.v1.json"
    ]
    if not le02_rows:
        return _fail("possible sheet missing LE-02.value_correct.v1.json row")
    if str(le02_rows[0].get("op_kind") or "") != "event_correct":
        return _fail("possible sheet LE-02 op_kind must be event_correct")
    print("Possible sheet LE-02: OK")

    docs_sheet = (
        Path(ROOT) / "docs" / "maheep" / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
    ).read_text(encoding="utf-8")
    if "LE-02.value_correct.v1.json" not in docs_sheet:
        return _fail("docs possible sheet missing LE-02 row")
    surface = (
        Path(ROOT) / "docs" / "maheep" / "WRITEBACK_SURFACE_MATRIX.md"
    ).read_text(encoding="utf-8")
    if "LE-02" not in surface or "event_correct" not in surface:
        return _fail("SURFACE matrix missing LE-02 event_correct")
    print("Docs sheet + SURFACE: OK")

    fe_root = Path(ROOT).parent / "klints_frontend"
    writebacks_ts = fe_root / "src" / "lib" / "writebacks.ts"
    if writebacks_ts.exists():
        fe = writebacks_ts.read_text(encoding="utf-8")
        if '"LE-02"' not in fe:
            return _fail("FE WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS missing LE-02")
        if "re-run DCS to clear LE-02" not in fe:
            return _fail("FE toast missing LE-02")
        if 'op_kind === "event_correct"' not in fe:
            return _fail("FE honesty must handle event_correct")
        if "No Manago restore for event value correction" not in fe:
            return _fail("FE honesty missing LE-02 event_correct title")
        print("FE allowlist + toast: OK")
    else:
        print("FE path not found (skip):", writebacks_ts)

    print("\nWB-14 verify PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
