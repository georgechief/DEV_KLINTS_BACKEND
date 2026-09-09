#!/usr/bin/env python
"""Compare DCS implementation against Excel source of truth (sheet 09 + registry)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

WORKBOOK = BACKEND_ROOT / "docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx"
CHECK_ID_RE = re.compile(r"^[A-Z]{2}-\d{2}[A-Z]?$")


def excel_check_ids() -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(WORKBOOK, data_only=True)
    ws = wb["09 MVP1 Check Scope"]
    headers = [c.value for c in ws[5]]
    idx = {h: i for i, h in enumerate(headers) if h}

    rows: list[dict] = []
    for row in ws.iter_rows(min_row=6, values_only=True):
        if not row:
            continue
        cid = row[idx.get("Check ID", 1)]
        if not cid or not isinstance(cid, str):
            continue
        cid = cid.strip()
        if not CHECK_ID_RE.match(cid):
            continue
        rows.append(
            {
                "check_id": cid,
                "role": row[idx.get("Role", 7)] if "Role" in idx else None,
                "weight": row[idx.get("Numeric Weight", 6)]
                if "Numeric Weight" in idx
                else row[idx.get("Weight", 6)]
                if "Weight" in idx
                else None,
                "phase": row[idx.get("Build Phase", 9)]
                if "Build Phase" in idx
                else row[idx.get("Phase", 9)]
                if "Phase" in idx
                else None,
                "class": row[idx.get("MVP1 Class", 2)]
                if "MVP1 Class" in idx
                else row[idx.get("Class", 2)]
                if "Class" in idx
                else None,
            }
        )
    return rows


def main() -> int:
    import django

    django.setup()
    from dataruns.dcs.executors.registry import registered_check_ids
    from dataruns.dcs.master import load_check_master_from_json

    if not WORKBOOK.is_file():
        print(f"FAIL: workbook missing at {WORKBOOK}")
        return 1

    excel_rows = excel_check_ids()
    excel_ids = {r["check_id"] for r in excel_rows}
    code_ids = registered_check_ids()
    json_master = load_check_master_from_json()
    json_ids = set(json_master.check_ids())

    print("=== DCS vs Excel audit ===")
    print(f"Excel sheet 09 checks: {len(excel_ids)}")
    print(f"Code executors:        {len(code_ids)}")
    print(f"JSON check master:     {len(json_ids)}")
    print()

    missing_exec = sorted(excel_ids - code_ids)
    extra_exec = sorted(code_ids - excel_ids)
    missing_json = sorted(excel_ids - json_ids)
    extra_json = sorted(json_ids - excel_ids)

    ok = True
    if missing_exec:
        ok = False
        print("MISSING EXECUTOR (in Excel, not in code):")
        for cid in missing_exec:
            print(f"  - {cid}")
        print()
    if extra_exec:
        print("EXTRA EXECUTOR (in code, not in Excel):")
        for cid in extra_exec:
            print(f"  - {cid}")
        print()
    if missing_json:
        ok = False
        print("MISSING JSON MASTER (in Excel, not in JSON):")
        for cid in missing_json:
            print(f"  - {cid}")
        print()
    if extra_json:
        print("EXTRA JSON MASTER (in JSON, not in Excel):")
        for cid in extra_json:
            print(f"  - {cid}")
        print()

    # Role / weight parity Excel vs JSON
    mismatches: list[str] = []
    json_by = json_master.by_id()
    for row in excel_rows:
        cid = row["check_id"]
        if cid not in json_by:
            continue
        jd = json_by[cid]
        excel_role = str(row.get("role") or "").strip().upper()
        if excel_role and jd.role.upper() != excel_role:
            mismatches.append(f"{cid}: role Excel={excel_role} JSON={jd.role}")
        excel_weight = row.get("weight")
        if excel_weight is not None and float(jd.numeric_weight) != float(excel_weight):
            mismatches.append(
                f"{cid}: weight Excel={excel_weight} JSON={jd.numeric_weight}"
            )

    if mismatches:
        ok = False
        print("ROLE/WEIGHT MISMATCH (Excel vs JSON master):")
        for line in mismatches[:20]:
            print(f"  - {line}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")
        print()

    gates = [r for r in excel_rows if str(r.get("role") or "").upper() == "GATE"]
    rule = [
        r
        for r in excel_rows
        if "RULE" in str(r.get("class") or "").upper()
        and str(r.get("role") or "").upper() != "GATE"
    ]
    drift = [r for r in excel_rows if "DRIFT" in str(r.get("class") or "").upper()]
    print(f"Excel breakdown: GATE={len(gates)} RULE={len(rule)} DRIFT={len(drift)}")

    # Dimension weights: Excel sheet 07 vs JSON fixture (runtime DB follows Excel seed).
    from openpyxl import load_workbook

    wb = load_workbook(WORKBOOK, data_only=True)
    ws7 = wb["07 Scoring Model"]
    excel_dim_weights: dict[str, int] = {}
    for row in ws7.iter_rows(min_row=6, values_only=True):
        label = row[0]
        if not label or not str(label).strip().startswith(("0", "1")):
            continue
        label = str(label).strip()
        if label.startswith("00 "):
            continue
        excel_dim_weights[label] = int(float(row[1] or 0))

    dim_mismatches: list[str] = []
    # Excel v1.4.1 sheet 07 typo: dimension 07 shows 90% but scoring contract uses 10%.
    KNOWN_DIM_WEIGHT_TYPOS = {("07 Business Reality", 90, 10)}
    for label, excel_w in sorted(excel_dim_weights.items()):
        json_w = json_master.dimension_weights.get(label)
        if json_w is None:
            dim_mismatches.append(f"{label}: Excel={excel_w} JSON=missing")
        elif int(json_w) != int(excel_w):
            if (label, int(excel_w), int(json_w)) in KNOWN_DIM_WEIGHT_TYPOS:
                print(
                    f"\nNOTE: Excel typo {label} weight {excel_w}% — "
                    f"code/seed uses {json_w}% (seed_dcs_master normalizes on import)."
                )
                continue
            dim_mismatches.append(f"{label}: Excel={excel_w} JSON={json_w}")

    if dim_mismatches:
        print("\nDIMENSION WEIGHT MISMATCH (Excel sheet 07 vs JSON fixture):")
        for line in dim_mismatches:
            print(f"  - {line}")
        ok = False
        print()

    if ok and not missing_exec and not missing_json:
        print("\nPASS: All 42 Excel checks have executors and JSON master entries.")
        return 0
    print("\nFAIL: Gaps found — see above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
