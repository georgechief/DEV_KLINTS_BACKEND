#!/usr/bin/env python
"""PRD-WB-21 — verify sandbox contract matrix vs FE allowlist + sheet."""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "dataruns" / "writebacks" / "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
HELPERS = ROOT / "dataruns" / "tests" / "writeback_helpers.py"
CONTRACT = ROOT / "dataruns" / "tests" / "test_writeback_sandbox_contract.py"


def _frontend_writebacks_path() -> Path:
    """Optional CI override: KLINTS_FRONTEND_WRITEBACKS=/path/to/writebacks.ts"""
    override = os.environ.get("KLINTS_FRONTEND_WRITEBACKS", "").strip()
    if override:
        return Path(override)
    return ROOT.parent / "klints_frontend" / "src" / "lib" / "writebacks.ts"


FE_WRITEBACKS = _frontend_writebacks_path()

_CHECK_ID_RE = re.compile(r'"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)"')
_TIER_A_TEST_RE = re.compile(
    r"def test_tier_a_([a-z0-9]+(?:_[a-z0-9]+)*)_sandbox_pass\b"
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _check_id_from_test_slug(slug: str) -> str:
    """Map test_tier_a_ci01_… → CI-01; test_tier_a_wb_shop_01_… → WB-SHOP-01."""
    raw = slug.strip().upper()
    if raw.startswith("WB_SHOP_"):
        return "WB-SHOP-" + raw.rsplit("_", 1)[-1]
    compact = raw.replace("_", "")
    m = re.match(r"^([A-Z]+)(\d{2})$", compact)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return raw.replace("_", "-")


def _contract_tier_a_test_ids() -> set[str]:
    text = CONTRACT.read_text(encoding="utf-8")
    return {_check_id_from_test_slug(m.group(1)) for m in _TIER_A_TEST_RE.finditer(text)}


def _parse_helper_tuple(name: str) -> set[str]:
    text = HELPERS.read_text(encoding="utf-8")
    m = re.search(rf"{name}\s*=\s*\((.*?)\)", text, flags=re.S)
    if not m:
        raise ValueError(f"missing {name} in {HELPERS.name}")
    return set(_CHECK_ID_RE.findall(m.group(1)))


def _tier_sets() -> tuple[set[str], set[str], set[str], set[str]]:
    """Load tiers from writeback_helpers (SoT) — no Django import."""
    return (
        _parse_helper_tuple("TIER_A_SANDBOX_CHECK_IDS"),
        _parse_helper_tuple("TIER_B_PLAN_ONLY_CHECK_IDS"),
        _parse_helper_tuple("TIER_C_EXECUTE_BLOCKED_CHECK_IDS"),
        _parse_helper_tuple("TIER_D_DISABLED_CHECK_IDS"),
    )


def _fe_allowlist() -> set[str]:
    text = FE_WRITEBACKS.read_text(encoding="utf-8")
    # Take the const array body only (before `] as const`).
    block = text.split("WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS")[1].split("]")[0]
    return set(_CHECK_ID_RE.findall(block))


def _sheet_states() -> dict[str, set[str]]:
    # Same comment-skip as dataruns.writebacks.possible_sheet.load_possible_sheet.
    lines = [
        line
        for line in SHEET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    rows = list(csv.DictReader(lines))
    out: dict[str, set[str]] = {}
    for row in rows:
        cid = (row.get("check_id") or "").strip()
        state = (row.get("write_possible_today") or "").strip().lower()
        if not cid:
            continue
        out.setdefault(cid, set()).add(state)
    return out


def main() -> int:
    if not SHEET.is_file():
        return _fail(f"missing sheet {SHEET}")
    if not FE_WRITEBACKS.is_file():
        return _fail(f"missing FE {FE_WRITEBACKS}")
    if not HELPERS.is_file():
        return _fail(f"missing helpers {HELPERS}")
    if not CONTRACT.is_file():
        return _fail(f"missing contract tests {CONTRACT}")

    try:
        tier_a, tier_b, tier_c, tier_d = _tier_sets()
    except ValueError as exc:
        return _fail(str(exc))

    fe = _fe_allowlist()
    sheet = _sheet_states()
    covered = _contract_tier_a_test_ids()

    if fe != tier_a:
        only_fe = sorted(fe - tier_a)
        only_tier = sorted(tier_a - fe)
        return _fail(
            f"FE allowlist must equal Tier A "
            f"(extra_FE={only_fe or '-'} missing_FE={only_tier or '-'})"
        )

    missing_tests = sorted(tier_a - covered)
    if missing_tests:
        return _fail(f"Tier A missing harness test methods: {missing_tests}")

    for cid in sorted(tier_a):
        states = sheet.get(cid) or set()
        if "yes" not in states:
            return _fail(f"Tier A {cid} sheet must include write_possible_today=yes ({states})")

    for cid in sorted(tier_b):
        if cid in fe:
            return _fail(f"Tier B {cid} must NOT be on FE execute allowlist")
        states = sheet.get(cid) or set()
        if "preview_only" not in states:
            return _fail(f"Tier B {cid} sheet must be preview_only ({states})")

    for cid in sorted(tier_c):
        if cid in fe:
            return _fail(f"Tier C {cid} must NOT be on FE execute allowlist yet")
        states = sheet.get(cid) or set()
        if "no" not in states and "preview_only" not in states:
            return _fail(f"Tier C {cid} sheet unexpected {states}")

    for cid in sorted(tier_d):
        states = sheet.get(cid) or set()
        if "disabled" not in states and "no" not in states:
            return _fail(f"Tier D {cid} sheet unexpected {states}")

    print(
        "WB-21 matrix OK:",
        f"TierA={len(tier_a)} TierB={len(tier_b)} TierC={len(tier_c)} TierD={len(tier_d)}",
        f"FE_allowlist={len(fe)} harness_tests={len(covered)}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
