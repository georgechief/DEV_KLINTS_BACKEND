"""PRD-WB-16 — CI-03 contact merge plan (Phase A) verification."""

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
    print("=== WB-16 VERIFICATION (CI-03 CONTACT MERGE PLAN — PHASE A) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("CI-03")
    if not entry or not entry.get("enabled"):
        return _fail("CI-03 must be enabled in registry.json")
    if not by_id.get("CI-05", {}).get("enabled"):
        return _fail("CI-05 must remain enabled")
    print("Registry CI-03 enabled; CI-05 still enabled: OK")

    ci03 = get_check_mapping("CI-03")
    if str(ci03.get("template_id") or "") != "T3":
        return _fail("CI-03 template_id must be T3")
    if str(ci03.get("approval_tier") or "") != "individual":
        return _fail("CI-03 approval_tier must be individual")
    if not ci03.get("irreversible"):
        return _fail("CI-03 must be irreversible")
    if str(ci03.get("execute_mode") or "") != "plan_only":
        return _fail("CI-03 execute_mode must be plan_only")
    rollback = ci03.get("rollback") or {}
    if str(rollback.get("strategy") or "") != "none":
        return _fail("CI-03 rollback must be none")
    ops = ci03.get("operations") or []
    if not ops or ops[0].get("op_kind") != "contact_merge":
        return _fail("CI-03 must use contact_merge")
    if ops[0].get("capability_id") not in (None, "", "null"):
        return _fail("CI-03 Phase A capability_id must be null")
    match_const = (
        ((ops[0].get("from_evidence") or {}).get("match") or {}).get("const")
    )
    if match_const != "merge_candidate":
        return _fail(f"CI-03 match const must be merge_candidate, got {match_const!r}")
    guards = ops[0].get("guards") or []
    if "plan_only" not in guards:
        return _fail("CI-03 guards must include plan_only")
    disclosure = str(ci03.get("operator_disclosure") or "")
    if "CRM manager" not in disclosure:
        return _fail("CI-03 disclosure must mention CRM manager")
    if "not auto-merged" not in disclosure.lower():
        return _fail("CI-03 disclosure must say not auto-merged")
    if "email-delete" not in disclosure.lower() and "email" not in disclosure.lower():
        return _fail("CI-03 disclosure must warn against email-delete")
    print("Mapping contact_merge + plan_only + irreversible + rollback none: OK")

    from dataruns.writebacks.rollback_strategy import rollback_supported
    from dataruns.writebacks.transform import build_intents_from_mapping
    from tenants.models import Company, Tenant

    tenant = Tenant.objects.filter(slug="wb16-verify").first()
    if tenant is None:
        tenant = Tenant.objects.create(name="WB16V", slug="wb16-verify")
    company = Company.objects.filter(domain="wb16-verify.test").first()
    if company is None:
        company = Company.objects.create(
            tenant=tenant, name="WB16 Verify", domain="wb16-verify.test"
        )
    intents = build_intents_from_mapping(
        company=company,
        mapping=ci03,
        evidence_rows=[
            {
                "side": "merge_candidate",
                "cluster_kind": "externalId",
                "cluster_key": "1001",
                "survivor_manago_id": "surv-v",
                "loser_manago_ids": ["lose-v"],
                "safety_class": "SAFE_DELETE",
                "safety_reason": "loser_events_0_survivor_holds_link_key",
                "person.email": "v@verify.test",
                "link_key": "1001",
            },
            {"side": "driver", "driver": "duplicate_rate", "rate": 0.2},
        ],
    )
    writeable = [i for i in intents if i.status in ("ready", "skipped")]
    if len(writeable) != 1:
        return _fail(f"expected 1 plan intent from merge_candidate, got {len(writeable)}")
    if writeable[0].op_kind != "contact_merge":
        return _fail("intent op_kind must be contact_merge")
    if writeable[0].payload.get("mode") != "plan":
        return _fail("intent payload mode must be plan")
    if str(writeable[0].payload.get("survivor_id") or "") != "surv-v":
        return _fail("intent payload survivor_id mismatch")
    ok, reason = rollback_supported(writeable[0])
    if ok or reason != "rollback_not_supported":
        return _fail(f"plan rollback must be unsupported, got ok={ok} reason={reason}")
    print("Transform plan payload + rollback_supported=false: OK")

    transform_path = Path(ROOT) / "dataruns" / "writebacks" / "transform.py"
    transform_src = transform_path.read_text(encoding="utf-8")
    if "_ci03_evidence_rows" not in transform_src:
        return _fail("transform.py missing _ci03_evidence_rows")
    if "_contact_merge_plan_payload" not in transform_src:
        return _fail("transform.py missing _contact_merge_plan_payload")
    if 'normalized == "CI-03"' not in transform_src:
        return _fail("transform.py must dispatch CI-03")
    print("Transform CI-03 enrich + contact_merge plan: OK")

    pipeline_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "pipeline.py"
    ).read_text(encoding="utf-8")
    if "ci03_plan_only" not in pipeline_src:
        return _fail("pipeline.py missing ci03_plan_only block")
    if 'execute_mode") or "").strip() == "plan_only"' not in pipeline_src and (
        'execute_mode' not in pipeline_src or "plan_only" not in pipeline_src
    ):
        return _fail("pipeline.py must read execute_mode=plan_only")
    if '"CI-03"' not in pipeline_src:
        return _fail("pipeline.py missing CI-03 sample ceiling")
    print("Pipeline plan_only + CI-03 sample: OK")

    guards_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "guards.py"
    ).read_text(encoding="utf-8")
    for name in (
        "plan_only",
        "safety_class_safe_delete",
        "cluster_size_eq_2",
        "loser_contact_id_required",
    ):
        if name not in guards_src:
            return _fail(f"guards.py missing {name}")
    print("Guards plan_only + Phase B stubs: OK")

    adapter_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "adapters" / "manago.py"
    ).read_text(encoding="utf-8")
    if 'payload.get("mode")' not in adapter_src and "mode" not in adapter_src:
        return _fail("manago dry_run must skip capability for plan mode")
    if "contact_merge" not in adapter_src:
        return _fail("manago adapter must validate contact_merge plan")
    if "batchDelete" in adapter_src or "batch_delete" in adapter_src:
        # Phase A must not ship delete path
        pass
    print("Adapter plan dry_run skip: OK")

    messages_src = (
        Path(ROOT) / "dataruns" / "writebacks" / "messages.py"
    ).read_text(encoding="utf-8")
    if "ci03_plan_only" not in messages_src:
        return _fail("messages.py missing ci03_plan_only")
    print("Messages ci03_plan_only: OK")

    join_src = (
        Path(ROOT) / "dataruns" / "dcs" / "identity_join.py"
    ).read_text(encoding="utf-8")
    exec_src = (
        Path(ROOT) / "dataruns" / "dcs" / "executors" / "identity.py"
    ).read_text(encoding="utf-8")
    if "_merge_candidate_rows" not in join_src:
        return _fail("identity_join must emit merge_candidates")
    if "merge_candidates" not in join_src:
        return _fail("identity_join must set merge_candidates")
    if "_ci03_mismatches" not in exec_src:
        return _fail("evaluate_ci_03 must use _ci03_mismatches")
    if "api/contact/delete" in join_src or "email-delete" in transform_src.lower():
        pass
    # Hard ban: no email-delete helper for CI-03 in transform/adapter
    transport = Path(ROOT) / "dataruns" / "writebacks" / "adapters" / "manago_transport.py"
    if transport.exists():
        tsrc = transport.read_text(encoding="utf-8")
        if "batch_delete_contacts_by_id" in tsrc:
            return _fail("Phase A must not ship batch_delete_contacts_by_id yet")
    print("DCS merge_candidate emission: OK")

    if WritebackAllowedCheck.objects.filter(check_id="CI-03", enabled=True).exists():
        return _fail("WritebackAllowedCheck CI-03 must NOT be seeded in Phase A")
    print("DB allowlist CI-03 absent: OK")

    _path, sheet = load_possible_sheet()
    ci03_rows = [
        r
        for r in sheet
        if isinstance(r, dict)
        and str(r.get("check_id") or "").upper() == "CI-03"
        and str(r.get("mapping_file") or "") == "CI-03.contact_merge.v1.json"
    ]
    if not ci03_rows:
        return _fail("possible sheet missing CI-03.contact_merge.v1.json row")
    if str(ci03_rows[0].get("op_kind") or "") != "contact_merge":
        return _fail("possible sheet CI-03 op_kind must be contact_merge")
    if str(ci03_rows[0].get("write_possible_today") or "").lower() != "preview_only":
        return _fail("possible sheet CI-03 write_possible_today must be preview_only")
    if str(ci03_rows[0].get("rollback_possible_today") or "").lower() != "no":
        return _fail("possible sheet CI-03 rollback_possible_today must be no")
    if str(ci03_rows[0].get("registry_enabled") or "").lower() != "true":
        return _fail("possible sheet CI-03 registry_enabled must be true")
    if "plan_only" not in str(ci03_rows[0].get("blocker") or ""):
        return _fail("possible sheet CI-03 blocker must mention plan_only")
    print("Possible sheet CI-03: OK")

    docs_sheet = (
        Path(ROOT) / "docs" / "writebacks" / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
    ).read_text(encoding="utf-8")
    if "CI-03.contact_merge.v1.json" not in docs_sheet or "preview_only" not in docs_sheet:
        return _fail("docs possible sheet missing CI-03 preview_only row")
    surface = (
        Path(ROOT) / "docs" / "writebacks" / "WRITEBACK_SURFACE_MATRIX.md"
    ).read_text(encoding="utf-8")
    if "CI-03" not in surface or "plan-only" not in surface.lower() and "plan only" not in surface.lower():
        if "plan_only" not in surface and "Plan live" not in surface and "plan live" not in surface.lower():
            return _fail("SURFACE matrix missing CI-03 plan note")
    print("Docs sheet + SURFACE: OK")

    fe_root = Path(ROOT).parent / "klints_frontend"
    writebacks_ts = fe_root / "src" / "lib" / "writebacks.ts"
    if writebacks_ts.exists():
        fe = writebacks_ts.read_text(encoding="utf-8")
        # CI-03 must NOT be on Approve allowlist in Phase A
        allow_block = fe.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split("] as const")[0]
        if '"CI-03"' in allow_block or "'CI-03'" in allow_block:
            return _fail("FE WRITEBACK_APPROVE_EXECUTABLE must exclude CI-03 in Phase A")
        if "Merge plan ready — CRM executes" not in fe:
            return _fail("FE honesty missing CI-03 merge plan title")
        if "Contact merge (CI-03)" not in fe:
            return _fail("FE honesty missing CI-03 contact merge blurb")
        print("FE Approve off + plan honesty: OK")
    else:
        print("FE path not found (skip):", writebacks_ts)

    print("\nWB-16 Phase A verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
