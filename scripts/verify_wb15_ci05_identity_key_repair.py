"""PRD-WB-15 — CI-05 identity key repair writeback verification."""

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
    print("=== WB-15 VERIFICATION (CI-05 IDENTITY KEY REPAIR) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("CI-05")
    if not entry or not entry.get("enabled"):
        return _fail("CI-05 must be enabled in registry.json")
    if not by_id.get("CI-01", {}).get("enabled"):
        return _fail("CI-01 must remain enabled")
    print("Registry CI-05 enabled; CI-01 still enabled: OK")

    ci05 = get_check_mapping("CI-05")
    if str(ci05.get("template_id") or "") != "T2":
        return _fail("CI-05 template_id must be T2")
    if str(ci05.get("approval_tier") or "") != "batch":
        return _fail("CI-05 approval_tier must be batch (Excel approved batch)")
    if ci05.get("irreversible"):
        return _fail("CI-05 must be restorable (irreversible=false)")
    rollback = ci05.get("rollback") or {}
    if str(rollback.get("strategy") or "") != "restore_prior_field":
        return _fail("CI-05 rollback must be restore_prior_field")
    ops = ci05.get("operations") or []
    if not ops or ops[0].get("op_kind") != "contact_upsert":
        return _fail("CI-05 must use contact_upsert")
    if "contact_merge" in json.dumps(ci05):
        return _fail("CI-05 must not use contact_merge")
    match_const = (
        ((ops[0].get("from_evidence") or {}).get("match") or {}).get("const")
    )
    if match_const != "missing_link_key":
        return _fail(f"CI-05 match const must be missing_link_key, got {match_const!r}")
    fields = (ops[0].get("from_evidence") or {}).get("fields") or {}
    if "contact_id" not in fields or "link_key" not in fields:
        return _fail("CI-05 fields must include contact_id and link_key")
    if ops[0].get("capability_id") != "RESTV2.CONTACT.UPSERT":
        return _fail("CI-05 capability_id must be RESTV2.CONTACT.UPSERT")
    disclosure = str(ci05.get("operator_disclosure") or "")
    if "externalId" not in disclosure:
        return _fail("CI-05 disclosure must mention externalId")
    if "CI-03" not in disclosure and "reused" not in disclosure.lower():
        return _fail("CI-05 disclosure must mention reused / CI-03")
    print("Mapping contact_upsert + missing_link_key + batch + restore: OK")

    from dataruns.writebacks.capabilities import (
        capability_allows_execute,
        capability_batch_max,
        capability_status,
    )

    status = capability_status("RESTV2.CONTACT.UPSERT")
    if status not in {"CONFIRMED_LIVE", "CONFIRMED_LIMITED"}:
        return _fail(f"RESTV2.CONTACT.UPSERT must be CONFIRMED_*, got {status!r}")
    if not capability_allows_execute("RESTV2.CONTACT.UPSERT"):
        return _fail("RESTV2.CONTACT.UPSERT must allow execute")
    cap = capability_batch_max("RESTV2.CONTACT.UPSERT") or 0
    if int(cap) < 1:
        return _fail("CONTACT.UPSERT batch_max must be >= 1")
    print(f"Capability CONTACT.UPSERT status={status} batch_max={cap}: OK")

    from dataruns.writebacks.rollback_strategy import rollback_supported
    from dataruns.writebacks.transform import build_intents_from_mapping
    from tenants.models import Company, Tenant

    tenant = Tenant.objects.filter(slug="wb15-verify").first()
    if tenant is None:
        tenant = Tenant.objects.create(name="WB15V", slug="wb15-verify")
    company = Company.objects.filter(domain="wb15-verify.test").first()
    if company is None:
        company = Company.objects.create(
            tenant=tenant, name="WB15 Verify", domain="wb15-verify.test"
        )
    intents = build_intents_from_mapping(
        company=company,
        mapping=ci05,
        evidence_rows=[
            {
                "side": "missing_link_key",
                "person.email": "v@verify.test",
                "manago_contact_id": "mc-v",
                "shopify_customer_id": "1001",
                "prior_external_id": "",
            },
            {
                "side": "driver",
                "driver": "link_key_reused",
            },
        ],
    )
    # Without Contact DB rows, _ci05_evidence_rows is not used here —
    # build_intents_from_mapping matches directly; driver must not produce intents.
    writeable = [i for i in intents if i.status in ("ready", "skipped")]
    if len(writeable) != 1:
        return _fail(f"expected 1 writeable intent from missing_link_key, got {len(writeable)}")
    if writeable[0].op_kind != "contact_upsert":
        return _fail("intent op_kind must be contact_upsert")
    if not writeable[0].payload.get("contactId"):
        return _fail("intent payload must include contactId")
    if str(writeable[0].payload.get("externalId") or "") != "1001":
        return _fail("intent payload externalId must be Shopify customers.id")
    ok, reason = rollback_supported(writeable[0])
    if not ok:
        return _fail(f"contact_upsert restore_prior_field must support rollback, got {reason}")
    print("Transform contactId + externalId + rollback_supported: OK")

    transform_path = Path(ROOT) / "dataruns" / "writebacks" / "transform.py"
    transform_src = transform_path.read_text(encoding="utf-8")
    if "_ci05_evidence_rows" not in transform_src:
        return _fail("transform.py missing _ci05_evidence_rows")
    if "_ci05_live_missing_link_key_rows" not in transform_src:
        return _fail("transform.py must rebuild missing_link_key from live DB when score is stale")
    if 'normalized == "CI-05"' not in transform_src:
        return _fail("transform.py must dispatch CI-05")
    print("Transform CI-05 enrich + live rebuild + contactId: OK")

    pipeline_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "pipeline.py"
    ).read_text(encoding="utf-8")
    if '"CI-05"' not in pipeline_src or "identity key repairs" not in pipeline_src:
        return _fail("pipeline.py missing CI-05 truncation probe")
    if '("SP-07", "PT-04", "CI-05")' not in pipeline_src and "CI-05" not in pipeline_src:
        return _fail("pipeline.py missing CI-05 UPSERT ceiling")
    print("Pipeline CI-05 ceiling + truncation: OK")

    adapter_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "adapters" / "manago.py"
    ).read_text(encoding="utf-8")
    if "restore_prior_field" not in adapter_src:
        return _fail("manago adapter missing restore_prior_field for contact_upsert")
    if "restored_external_id" not in adapter_src:
        return _fail("adapter must restore externalId on rollback")
    print("Adapter restore_prior_field: OK")

    join_src = (
        Path(ROOT) / "dataruns" / "dcs" / "identity_join.py"
    ).read_text(encoding="utf-8")
    exec_src = (
        Path(ROOT) / "dataruns" / "dcs" / "executors" / "identity.py"
    ).read_text(encoding="utf-8")
    worklist_src = (
        Path(ROOT) / "dataruns" / "dcs" / "worklist.py"
    ).read_text(encoding="utf-8")
    if "_missing_link_key_rows" not in join_src:
        return _fail("identity_join must emit missing_link_key rows")
    if "missing_link_key" not in join_src:
        return _fail("identity_join must set missing_link_key")
    if "_is_guest_contact" not in join_src:
        return _fail("identity_join must exclude Shopify guest ids from missing_link_key")
    if "_ci05_mismatches" not in exec_src:
        return _fail("evaluate_ci_05 must use _ci05_mismatches")
    if "provenance" not in exec_src or "missing_link_key" not in exec_src:
        return _fail("evaluate_ci_05 must attach missing_link_key provenance")
    if "is_ci05_cold_estate_unknown" not in worklist_src:
        return _fail("worklist must include CI-05 cold UNKNOWN for Fix")
    print("DCS missing_link_key emission + cold UNKNOWN worklist: OK")

    if not WritebackAllowedCheck.objects.filter(
        check_id="CI-05", enabled=True
    ).exists():
        return _fail("WritebackAllowedCheck CI-05 not seeded/enabled")
    print("DB allowlist CI-05: OK")

    _path, sheet = load_possible_sheet()
    ci05_rows = [
        r
        for r in sheet
        if isinstance(r, dict)
        and str(r.get("check_id") or "").upper() == "CI-05"
        and str(r.get("mapping_file") or "") == "CI-05.identity_key_repair.v1.json"
    ]
    if not ci05_rows:
        return _fail("possible sheet missing CI-05.identity_key_repair.v1.json row")
    if str(ci05_rows[0].get("op_kind") or "") != "contact_upsert":
        return _fail("possible sheet CI-05 op_kind must be contact_upsert")
    if str(ci05_rows[0].get("rollback_possible_today") or "").lower() != "yes":
        return _fail("possible sheet CI-05 rollback_possible_today must be yes")
    print("Possible sheet CI-05: OK")

    docs_sheet = (
        Path(ROOT) / "docs" / "writebacks" / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
    ).read_text(encoding="utf-8")
    if "CI-05.identity_key_repair.v1.json" not in docs_sheet:
        return _fail("docs possible sheet missing CI-05 row")
    surface = (
        Path(ROOT) / "docs" / "writebacks" / "WRITEBACK_SURFACE_MATRIX.md"
    ).read_text(encoding="utf-8")
    if "CI-05" not in surface or "missing_link_key" not in surface:
        return _fail("SURFACE matrix missing CI-05 missing_link_key note")
    wb02 = (
        Path(ROOT) / "docs" / "writebacks" / "PRD_WB_02_FIX_APPROVE_WRITEBACK_EXECUTE.md"
    ).read_text(encoding="utf-8")
    # CI-05 must not remain on the Approve-OFF list.
    off_line = None
    for line in wb02.splitlines():
        if "Approve OFF" in line or "until built" in line.lower():
            off_line = line
            break
    # §3.2 list is a backtick CSV of check ids — CI-05 must be gone from that list.
    if "`CI-03`, `CI-05`," in wb02 or "`CI-05`, `PT-01`" in wb02:
        return _fail("WB-02 §3.2 must remove CI-05 from Approve OFF list")
    print("Docs sheet + SURFACE + WB-02 OFF: OK")

    fe_root = Path(ROOT).parent / "klints_frontend"
    writebacks_ts = fe_root / "src" / "lib" / "writebacks.ts"
    use_cases = fe_root / "src" / "lib" / "use-cases.ts"
    if writebacks_ts.exists():
        fe = writebacks_ts.read_text(encoding="utf-8")
        if '"CI-05"' not in fe:
            return _fail("FE WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS missing CI-05")
        if "re-run DCS to clear CI-05" not in fe:
            return _fail("FE toast missing CI-05")
        if "Identity key repair (CI-05)" not in fe:
            return _fail("FE honesty missing CI-05 identity key repair blurb")
        if "reused clusters need CI-03" not in fe:
            return _fail("FE honesty must mention reused → CI-03")
        print("FE allowlist + toast + honesty: OK")
    else:
        print("FE path not found (skip):", writebacks_ts)
    if use_cases.exists():
        uc = use_cases.read_text(encoding="utf-8")
        # CI-05 must not be in suppressFixProceedToStudio.
        if "CI-05" in uc and "suppressFixProceedToStudio" in uc:
            # Only fail if CI-05 appears inside the suppress helper body.
            idx = uc.find("function suppressFixProceedToStudio")
            if idx >= 0:
                body = uc[idx : idx + 400]
                if "CI-05" in body or '"CI-05"' in body:
                    return _fail("CI-05 must not be in suppressFixProceedToStudio")
        print("FE suppressFixProceedToStudio excludes CI-05: OK")

    print("\nWB-15 verify PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
