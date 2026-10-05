"""PRD-WB-13 — LE-05 order-level PURCHASE gap writeback verification."""

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
    print("=== WB-13 VERIFICATION (LE-05 PURCHASE GAP) ===\n")

    _load_registry.cache_clear()

    by_id = {
        str(row.get("check_id") or "").strip().upper(): row
        for row in list_mapping_entries()
    }
    entry = by_id.get("LE-05")
    if not entry or not entry.get("enabled"):
        return _fail("LE-05 must be enabled in registry.json")
    if not by_id.get("LE-01", {}).get("enabled"):
        return _fail("LE-01 must remain enabled (WB-13 overlap lock)")
    print("Registry LE-05 enabled; LE-01 still enabled: OK")

    le05 = get_check_mapping("LE-05")
    if not le05.get("irreversible"):
        return _fail("LE-05 must be irreversible")
    ops = le05.get("operations") or []
    if not ops or ops[0].get("op_kind") != "event_ingest":
        return _fail("LE-05 must use event_ingest")
    match_const = (
        ((ops[0].get("from_evidence") or {}).get("match") or {}).get("const")
    )
    if match_const != "shopify_only":
        return _fail(f"LE-05 match const must be shopify_only, got {match_const!r}")
    fields = (ops[0].get("from_evidence") or {}).get("fields") or {}
    if "event_type" in fields:
        return _fail("LE-05 must not require evidence event_type (PURCHASE default)")
    disclosure = str(le05.get("operator_disclosure") or "")
    if "Manago-only" not in disclosure and "manago_only" not in disclosure.lower():
        return _fail("LE-05 disclosure must mention Manago-only / no delete")
    if "dual Approve" not in disclosure and "LE-01" not in disclosure:
        return _fail("LE-05 disclosure must warn about LE-01 dual Approve")
    print("Mapping match shopify_only + irreversible disclosure: OK")

    from dataruns.writebacks.capabilities import capability_batch_max

    cap = capability_batch_max("RESTV2.EVENT.INGEST") or 1000
    if min(int(cap), 1000) < 50:
        return _fail("LE-05 default row cap depends on EVENT.INGEST batch_max >= 50")
    print(f"LE-05 default row ceiling (EVENT.INGEST batch_max={cap}): OK")

    transform_path = Path(ROOT) / "dataruns" / "writebacks" / "transform.py"
    transform_src = transform_path.read_text(encoding="utf-8")
    if "_le05_evidence_rows" not in transform_src:
        return _fail("transform.py missing _le05_evidence_rows")
    if "LE-05" not in transform_src or "_le01_sandbox_evidence_rows" not in transform_src:
        pass  # sandbox helper exists for LE-01; LE-05 must not call it
    if (
        'normalized == "LE-05"' not in transform_src
        and "normalized == 'LE-05'" not in transform_src
    ):
        return _fail("collect_evidence_rows missing LE-05 branch")
    # Ensure LE-05 path does not call sandbox helper
    le05_fn_start = transform_src.find("def _le05_evidence_rows")
    le05_fn_end = transform_src.find("\ndef _", le05_fn_start + 1)
    le05_body = transform_src[le05_fn_start:le05_fn_end]
    if "_le01_sandbox_evidence_rows" in le05_body:
        return _fail("LE-05 must not call _le01_sandbox_evidence_rows")
    if "gap_sample" not in le05_body:
        return _fail("LE-05 must expand value.gap_sample when mismatches missing")
    print("Transform LE-05 no-sandbox + gap_sample expand: OK")

    enrich_start = transform_src.find("def _enrich_le01_row")
    enrich_end = transform_src.find("\ndef _", enrich_start + 1)
    enrich_body = transform_src[enrich_start:enrich_end]
    if '***' not in enrich_body:
        return _fail("_enrich_le01_row must refuse PII-masked emails (LE-05 reuses it)")
    print("Enrich LE-01/LE-05 rejects masked emails: OK")

    pipeline_path = Path(ROOT) / "dataruns" / "writebacks" / "pipeline.py"
    pipeline_src = pipeline_path.read_text(encoding="utf-8")
    if 'normalized_check in ("LE-09", "LE-05")' not in pipeline_src and (
        '"LE-05"' not in pipeline_src or "EVENT.INGEST" not in pipeline_src
    ):
        return _fail("pipeline.py must give LE-05 EVENT.INGEST ceiling (not sandbox 10)")
    if '"LE-05"' not in pipeline_src or "purchase events" not in pipeline_src:
        return _fail("pipeline.py missing LE-05 truncation disclosure")
    print("Pipeline LE-05 EVENT.INGEST ceiling + truncation: OK")

    if not WritebackAllowedCheck.objects.filter(check_id="LE-05", enabled=True).exists():
        return _fail("WritebackAllowedCheck LE-05 missing — run migrate (0040)")
    print("Allowlist LE-05: OK")

    _source, sheet = load_possible_sheet()
    le05_rows = [r for r in sheet if str(r.get("check_id") or "").upper() == "LE-05"]
    if not le05_rows:
        return _fail("possible sheet missing LE-05 row")
    row = le05_rows[0]
    if row.get("write_possible_today") != "yes":
        return _fail("LE-05 write_possible_today must be yes")
    if row.get("rollback_possible_today") != "limited":
        return _fail("LE-05 rollback_possible_today must be limited")
    if row.get("op_kind") != "event_ingest":
        return _fail("LE-05 sheet op_kind must be event_ingest")
    print("Possible sheet LE-05 yes/limited: OK")

    docs_sheet = (
        Path(ROOT) / "docs" / "writebacks" / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
    )
    runtime_sheet = (
        Path(ROOT) / "dataruns" / "writebacks" / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
    )
    for path in (docs_sheet, runtime_sheet):
        text = path.read_text(encoding="utf-8")
        if "LE-05," not in text and ",LE-05," not in text:
            if not any(line.startswith("LE-05,") for line in text.splitlines()):
                return _fail(f"{path.name} missing LE-05 row")
    print("Both possible-sheet CSV copies include LE-05: OK")

    fe_path = Path(ROOT).parent / "klints_frontend" / "src" / "lib" / "writebacks.ts"
    if fe_path.exists():
        text = fe_path.read_text(encoding="utf-8")
        if '"LE-05"' not in text and "'LE-05'" not in text:
            return _fail("FE writebacks.ts missing LE-05 allowlist entry")
        if "re-run DCS to clear LE-05" not in text:
            return _fail("FE missing LE-05 success toast honesty")
        if "LE-01 / LE-05 / LE-09" not in text:
            return _fail("FE honesty blurb must mention LE-05 with LE-01/LE-09")
        if "suppressFixProceedToStudio" in text and (
            'id === "LE-05"' in text or "id === 'LE-05'" in text
        ):
            # suppress lives in use-cases.ts — check that file
            pass
        print("FE allowlist + toast + blurb LE-05: OK")
    else:
        print("FE writebacks.ts not found (skip)")

    use_cases = (
        Path(ROOT).parent / "klints_frontend" / "src" / "lib" / "use-cases.ts"
    )
    if use_cases.exists():
        uc = use_cases.read_text(encoding="utf-8")
        # suppressFixProceedToStudio must remain PT-04 only
        fn_start = uc.find("function suppressFixProceedToStudio")
        fn_end = uc.find("\nexport ", fn_start + 1)
        body = uc[fn_start:fn_end] if fn_start >= 0 else ""
        if "LE-05" in body:
            return _fail("Do not add LE-05 to suppressFixProceedToStudio")
        print("suppressFixProceedToStudio unchanged (no LE-05): OK")

    mapping_path = (
        Path(ROOT)
        / "dataruns"
        / "writebacks"
        / "mappings"
        / "LE-05.purchase_gap.v1.json"
    )
    spec = json.loads(mapping_path.read_text(encoding="utf-8"))
    if spec.get("check_id") != "LE-05" or not spec.get("enabled"):
        return _fail("LE-05 mapping file invalid")
    if "event_correct" in json.dumps(spec):
        return _fail("LE-05 must not use event_correct")
    print("Mapping file: OK")

    wb02 = Path(ROOT) / "docs" / "writebacks" / "PRD_WB_02_FIX_APPROVE_WRITEBACK_EXECUTE.md"
    if wb02.exists():
        text = wb02.read_text(encoding="utf-8")
        # OFF list line should not include LE-05 any more
        if "`LE-05`" in text and "Approve must stay OFF" in text:
            # Look at the backtick list after the OFF heading
            off_idx = text.find("Approve must stay OFF")
            next_heading = text.find("### ", off_idx + 1)
            off_block = text[off_idx:next_heading]
            # The shipped note should say LE-05 removed
            if "LE-05 removed" not in off_block and "`LE-05`" in off_block.split("\n")[0:20].__str__():
                # Still listed in the comma OFF set?
                for line in off_block.splitlines():
                    if line.strip().startswith("`CI-03`") and "LE-05" in line:
                        return _fail("WB-02 §3.2 still lists LE-05 as Approve OFF")
        print("WB-02 OFF list updated: OK")

    print("\nWB-13 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
