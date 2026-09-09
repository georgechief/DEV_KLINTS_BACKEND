"""
PRD-DCS-09 Step 12 — backend §10 acceptance verify (static + optional Django tests).

Run from klints_backend:
  python scripts/verify_dcs09_backend.py
  python scripts/verify_dcs09_backend.py --run-tests
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Windows consoles often default to cp1252; keep labels printable.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

failed = 0

DCS09_TEST_MODULES = [
    "dataruns.tests.test_pilot_gates_step0",
    "dataruns.tests.test_pilot_gates_step1",
    "dataruns.tests.test_pilot_gates_step2",
    "dataruns.tests.test_pilot_gates_step3",
    "dataruns.tests.test_pilot_gates_step4",
    "dataruns.tests.test_pilot_gates_step5",
    "dataruns.tests.test_pilot_gates_step6",
    "dataruns.tests.test_pilot_gates_step7",
    "dataruns.tests.test_pilot_gates_step8",
    "dataruns.tests.test_pilot_gates_step9",
    "dataruns.tests.test_pilot_gates_step10",
]

LOCKED_12 = frozenset(
    {
        "BR-03",
        "BR-09",
        "CC-06",
        "CI-08",
        "LE-07",
        "LE-10",
        "PT-05",
        "PT-06",
        "PT-11",
        "PT-13",
        "SP-04",
        "SP-10",
    }
)


def pass_(label: str) -> None:
    print(f"  [ok] {label}", flush=True)


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""), flush=True)


def assert_true(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        pass_(label)
    else:
        fail(label, detail)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail(f"file exists: {rel}")
        return ""
    return path.read_text(encoding="utf-8")


def main() -> int:
    global failed
    failed = 0

    parser = argparse.ArgumentParser(
        description="DCS-09 backend acceptance verify (PRD §10 / Step 12).",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run Django DCS-09 step0–step10 test modules (skipped if static checks fail).",
    )
    args = parser.parse_args()

    print("\nDCS-09 Step 12 — BE §10 acceptance\n", flush=True)

    gaps = read("docs/sahil/DCS_09_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md")
    assert_true(bool(gaps), "DCS_09_WORKING_GAPS exists")
    assert_true(bool(prd), "PRD_DCS_09 exists")
    assert_true(
        "feature/dcs-09-pilot-supplemental-gates" in gaps
        or "feature/dcs-09-pilot-supplemental-gates" in prd,
        "branch intent documented",
    )
    assert_true("**Right:**" in gaps or "Right:" in gaps, "PR right note present")
    assert_true("**Gap:**" in gaps or "Gap:" in gaps, "PR gap note present")
    assert_true(
        "Never touch headline 42" in gaps or "Never touch headline **42**" in gaps,
        "42 lock documented",
    )
    assert_true(
        "scripts/verify_dcs09_backend.py" in prd,
        "PRD §10 references verify script",
    )
    assert_true(
        "- [x] Verify script:" in prd or "[x] Verify script" in prd,
        "PRD §10 verify acceptance checked",
    )

    const_src = read("dataruns/use_cases/constants.py")
    assert_true(
        "SUPPLEMENTAL_PREFLIGHT_CHECKS" in const_src,
        "SUPPLEMENTAL_PREFLIGHT_CHECKS constant",
    )

    core_urls = read("core/urls.py")
    assert_true(
        'include("dataruns.dcs_urls")' in core_urls
        or "include('dataruns.dcs_urls')" in core_urls,
        "core.urls mounts dataruns.dcs_urls",
    )

    # Committed supplemental master + UC map
    master_json = ROOT / "dataruns/dcs/check_master_supplemental_mvp1.json"
    gate_map_json = ROOT / "dataruns/dcs/pilot_supplemental_gate_map.json"
    assert_true(master_json.is_file(), "check_master_supplemental_mvp1.json present")
    assert_true(gate_map_json.is_file(), "pilot_supplemental_gate_map.json present")
    if master_json.is_file():
        master_body = json.loads(master_json.read_text(encoding="utf-8"))
        checks = master_body.get("checks") if isinstance(master_body, dict) else None
        ids = {
            str(row.get("check_id")).strip()
            for row in (checks or [])
            if isinstance(row, dict) and row.get("check_id")
        }
        assert_true(ids == LOCKED_12, "supplemental master JSON has locked 12")
        assert_true(
            int(master_body.get("count") or 0) == 12,
            "supplemental master count == 12",
        )

    import django

    django.setup()

    from django.urls import reverse

    from dataruns.dcs.assemble import AssembleValidationError, assemble_dcs_score
    from dataruns.dcs.executors.registry import registered_check_ids
    from dataruns.dcs.master import load_check_master_from_json
    from dataruns.dcs.pilot_gates.contract import (
        EXPECTED_SUPPLEMENTAL_CHECK_COUNT,
        SLICE_A_CHECK_IDS,
        SLICE_B_CHECK_IDS,
        SUPPLEMENTAL_CHECK_IDS,
    )
    from dataruns.dcs.pilot_gates.master import load_supplemental_check_master
    from dataruns.dcs.types import CheckResult
    from dataruns.use_cases.constants import (
        DEFAULT_MANIFEST_REL,
        SUPPLEMENTAL_PREFLIGHT_CHECKS,
    )
    from dataruns.use_cases.recommend import (
        RecommendationContext,
        _raw_gate_status,
        is_supplemental_gate,
    )

    assert_true(
        len(SUPPLEMENTAL_PREFLIGHT_CHECKS) == 12,
        "constants has exactly 12 supplemental IDs",
    )
    assert_true(
        EXPECTED_SUPPLEMENTAL_CHECK_COUNT == 12,
        "EXPECTED_SUPPLEMENTAL_CHECK_COUNT == 12",
    )
    assert_true(
        set(SUPPLEMENTAL_CHECK_IDS) == set(SUPPLEMENTAL_PREFLIGHT_CHECKS),
        "contract IDs == constants",
    )
    assert_true(
        set(SUPPLEMENTAL_PREFLIGHT_CHECKS) == LOCKED_12,
        "12 IDs match sheet-11 lock",
    )
    assert_true(
        SLICE_A_CHECK_IDS | SLICE_B_CHECK_IDS == frozenset(SUPPLEMENTAL_PREFLIGHT_CHECKS),
        "SLICE_A | SLICE_B covers all 12",
    )
    assert_true(
        SLICE_A_CHECK_IDS & SLICE_B_CHECK_IDS == frozenset(),
        "SLICE_A and SLICE_B disjoint",
    )
    assert_true(SLICE_A_CHECK_IDS == frozenset({"CI-08", "CC-06"}), "Slice A = CI-08+CC-06")

    manifest_path = ROOT / DEFAULT_MANIFEST_REL
    assert_true(manifest_path.is_file(), f"pack manifest: {DEFAULT_MANIFEST_REL}")
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = set(manifest.get("supplemental_preflight_checks") or [])
        assert_true(listed == LOCKED_12, "pack manifest matches locked 12")

    headline_master = load_check_master_from_json()
    headline = {c.check_id for c in headline_master.checks}
    assert_true(len(headline) == 42, "headline master still 42")
    assert_true(
        headline & set(SUPPLEMENTAL_PREFLIGHT_CHECKS) == set(),
        "zero overlap with headline 42",
    )
    assert_true(
        registered_check_ids() & set(SUPPLEMENTAL_PREFLIGHT_CHECKS) == set(),
        "supplementals absent from 42 executor registry",
    )

    supp_master = load_supplemental_check_master()
    assert_true(
        len(supp_master.checks) == 12,
        "load_supplemental_check_master returns 12",
    )
    assert_true(
        {c.check_id for c in supp_master.checks} == LOCKED_12,
        "loaded supplemental master IDs match lock",
    )

    # Recommend merge wired (store-only for supplemental)
    recommend = read("dataruns/use_cases/recommend.py")
    assert_true(
        "get_latest_supplemental_status_map" in recommend,
        "recommend loads supplemental store",
    )
    assert_true("def _raw_gate_status" in recommend, "recommend _raw_gate_status")
    assert_true(
        "ctx.supplemental_results.get" in recommend,
        "supplemental status from store map only",
    )
    assert_true(
        "never invent PASS" in recommend.lower()
        or "Never invent PASS" in recommend,
        "recommend documents no invented PASS",
    )
    # Gating-check supplemental blockers must omit Data Center deep-links.
    assert_true(
        'code": "gating_check"' in recommend
        and "never deep-link to Data Center" in recommend,
        "supplemental gating_check blockers omit DCS href (documented)",
    )
    assert_true(is_supplemental_gate("CI-08"), "is_supplemental_gate(CI-08)")
    assert_true(not is_supplemental_gate("CC-03"), "CC-03 is not supplemental")

    ctx_store = RecommendationContext(
        headline_score=80.0,
        score_ready=True,
        dcs_data_run_id=1,
        check_results={"CC-03": "PASS", "CI-08": "PASS"},  # DCS inject must be ignored
        af_mode="AUGMENT",
        af_assessment_id=None,
        gap_stage_ids=[],
        as_of=None,
        supplemental_results={},
    )
    assert_true(
        _raw_gate_status("CI-08", ctx_store) is None,
        "DCS-injected supplemental ignored when store empty",
    )
    ctx_store.supplemental_results = {"CI-08": "FAIL"}
    assert_true(
        _raw_gate_status("CI-08", ctx_store) == "FAIL",
        "store supplemental status wins",
    )
    assert_true(
        _raw_gate_status("CC-03", ctx_store) == "PASS",
        "hard gate still reads DCS check_results",
    )

    # Evaluate + store + slices present
    for rel in (
        "dataruns/dcs/pilot_gates/evaluate.py",
        "dataruns/dcs/pilot_gates/store.py",
        "dataruns/dcs/pilot_gates/slice_a.py",
        "dataruns/dcs/pilot_gates/slice_b.py",
        "dataruns/dcs/pilot_gates/views.py",
    ):
        assert_true((ROOT / rel).is_file(), f"{rel} present")
    evaluate_src = read("dataruns/dcs/pilot_gates/evaluate.py")
    assert_true("def evaluate_pilot_gates" in evaluate_src, "evaluate_pilot_gates")

    # APIs mounted (source + reverse)
    dcs_urls = read("dataruns/dcs_urls.py")
    for name in (
        "dcs-pilot-gates-master",
        "dcs-pilot-gates-latest",
        "dcs-pilot-gates-evaluate",
        "dcs-pilot-supplemental-readiness",
    ):
        assert_true(f'name="{name}"' in dcs_urls, f"URL name in dcs_urls: {name}")

    try:
        assert_true(
            reverse("dcs-pilot-gates-master").endswith("/"),
            "reverse dcs-pilot-gates-master",
        )
        assert_true(
            reverse("dcs-pilot-gates-latest").endswith("/"),
            "reverse dcs-pilot-gates-latest",
        )
        assert_true(
            reverse("dcs-pilot-gates-evaluate").endswith("/"),
            "reverse dcs-pilot-gates-evaluate",
        )
        readiness = reverse(
            "dcs-pilot-supplemental-readiness",
            kwargs={"use_case_id": "UC-02"},
        )
        assert_true("UC-02" in readiness, "reverse readiness includes UC-02")
    except Exception as exc:  # pragma: no cover
        fail("django reverse pilot-gate URLs", str(exc))

    views = read("dataruns/dcs/pilot_gates/views.py")
    for cls in (
        "PilotGatesMasterView",
        "PilotGatesLatestView",
        "PilotGatesEvaluateView",
        "PilotSupplementalReadinessView",
    ):
        assert_true(f"class {cls}" in views, f"view: {cls}")

    # Isolation: assemble stays 42 and rejects supplemental IDs
    results = [
        CheckResult(check_id=c.check_id, status="PASS") for c in headline_master.checks
    ]
    run = assemble_dcs_score(results, erp_in_scope=False, master=headline_master)
    assert_true(len(run.check_result_refs) == 42, "assemble yields 42 refs")
    assert_true(
        set(run.check_result_refs) & set(SUPPLEMENTAL_PREFLIGHT_CHECKS) == set(),
        "assemble refs exclude supplementals",
    )
    rejected = False
    try:
        assemble_dcs_score(
            results + [CheckResult(check_id="CI-08", status="PASS")],
            erp_in_scope=False,
            master=headline_master,
        )
    except AssembleValidationError:
        rejected = True
    assert_true(rejected, "assemble rejects supplemental CI-08")

    # Step test modules present
    for mod in DCS09_TEST_MODULES:
        path = ROOT.joinpath(*mod.split(".")).with_suffix(".py")
        assert_true(path.is_file(), f"test module file: {mod}")

    # FE verify present (sibling repo) — soft signal for PR prep
    fe_verify = ROOT.parent / "klints_frontend" / "scripts" / "verify-dcs09-frontend.mjs"
    assert_true(
        fe_verify.is_file(),
        "FE verify-dcs09-frontend.mjs present (sibling)",
    )

    if args.run_tests:
        if failed:
            print(
                "\n--run-tests skipped: static checks already failed\n",
                flush=True,
            )
        else:
            print("\n--run-tests: Django DCS-09 step modules\n", flush=True)
            cmd = [
                sys.executable,
                "manage.py",
                "test",
                *DCS09_TEST_MODULES,
                "--verbosity=1",
            ]
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            proc = subprocess.run(cmd, cwd=str(ROOT), check=False, env=env)
            assert_true(proc.returncode == 0, "Django DCS-09 step tests pass")

    print()
    if failed:
        print(f"FAILED: {failed} check(s)", flush=True)
        return 1
    print("All DCS-09 Step 12 backend checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
