"""
PRD-QA-01 Step 9 — backend §12 acceptance verify (static + pure score).

Run from klints_backend:
  python scripts/verify_qa01_backend.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

failed = 0


def pass_(label: str) -> None:
    print(f"  [ok] {label}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


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
    print("\nQA-01 Step 9 — BE §12 acceptance\n")

    gaps = read("docs/sahil/QA_01_WORKING_GAPS.md")
    assert_true(bool(gaps), "WORKING_GAPS doc exists")
    assert_true("UC-02" in gaps, "demo path documents UC-02")
    assert_true("workflow.qa_run_completed" in gaps, "audit action documented")
    assert_true("Right:" in gaps or "**Right:**" in gaps, "PR right note present")
    assert_true("Gap:" in gaps or "**Gap:**" in gaps, "PR gap note present")

    run_src = read("dataruns/use_cases/qa_run.py")
    assert_true(
        'AUDIT_ACTION_QA_RUN_COMPLETED = "workflow.qa_run_completed"' in run_src,
        "audit action constant",
    )
    assert_true("def compute_qa_score" in run_src, "compute_qa_score present")
    assert_true("def run_qa_for_package" in run_src, "run_qa_for_package present")
    assert_true("Append-history" in run_src or "always creates a new row" in run_src, "append-history lock")

    eval_src = read("dataruns/use_cases/qa_evaluators.py")
    for tid in (
        "data_gates_pass",
        "consent_branching",
        "terminal_reachable",
        "no_orphan_nodes",
        "collision_policy",
        "measurement_wired",
        "rollback_defined",
    ):
        assert_true(tid in eval_src, f"pack hard_test id: {tid}")

    views = read("dataruns/use_cases/views.py")
    assert_true(
        "class BuildPackageQaView" in views or "BuildPackageQa" in views,
        "BuildPackageQaView present",
    )
    assert_true(
        "QA has not been run for this package" in views,
        "GET never-run 404 detail",
    )
    assert_true("Build package not found" in views, "package 404 detail")

    urls = read("dataruns/build_packages_urls.py")
    assert_true('name="build-package-qa"' in urls, "build-package-qa URL registered")
    qa_urls = read("dataruns/qa_runs_urls.py")
    assert_true('name="qa-run-detail"' in qa_urls, "qa-run-detail URL registered")

    # Pure score rules (django setup for imports)
    import django

    django.setup()

    from dataruns.use_cases.qa_evaluators import (
        HARD_TEST_IDS,
        HardTestResult,
        STATUS_FAIL,
        STATUS_PASS,
    )
    from dataruns.use_cases.qa_result import QA_STATUS_FAIL, QA_STATUS_PASS
    from dataruns.use_cases.qa_run import compute_qa_score

    assert_true(len(HARD_TEST_IDS) == 7, "exactly 7 pack hard_tests")

    all_pass = [HardTestResult(test_id=t, status=STATUS_PASS) for t in HARD_TEST_IDS]
    score, status, fails = compute_qa_score(all_pass, minimum_score=80)
    assert_true(score == 100.0 and status == QA_STATUS_PASS and fails == [], "all PASS → score 100 PASS")

    one_fail = list(all_pass)
    one_fail[0] = HardTestResult(test_id="data_gates_pass", status=STATUS_FAIL)
    score, status, fails = compute_qa_score(one_fail, minimum_score=80)
    assert_true(
        score >= 80 and status == QA_STATUS_FAIL and fails == ["data_gates_pass"],
        "one hard FAIL ⇒ overall FAIL even if score ≥ 80",
    )

    score, status, _ = compute_qa_score(all_pass, minimum_score=101)
    assert_true(
        score == 100.0 and status == QA_STATUS_FAIL,
        "all hard PASS but below minimum ⇒ FAIL",
    )

    tests = {
        "dataruns/tests/test_qa_api_step5.py": [
            "test_post_qa_returns_201_schema_and_audits",
            "test_rerun_appends_and_get_returns_newest",
        ],
        "dataruns/tests/test_qa_run_step4.py": [
            "test_uc02_golden_run_passes_and_audits",
            "test_hard_fail_forces_fail_even_when_score_ge_minimum",
            "test_rerun_appends_history",
            "test_empty_hard_tests_run_scores_fail",
        ],
        "dataruns/tests/test_qa_evaluators_step3.py": [
            "test_uc02_golden_all_seven_pass",
            "test_terminal_mixed_valid_and_dangling_branch_fails",
        ],
        "dataruns/tests/test_qa_normalize_step2.py": [
            "test_mixed_valid_and_dangling_branch_missing_terminal",
        ],
    }
    for rel, names in tests.items():
        body = read(rel)
        for name in names:
            assert_true(name in body, f"acceptance test present: {name}")

    print(f"\n{'OK' if failed == 0 else 'FAILED'} — {failed} failure(s)\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    # Avoid Windows cp1252 crashes on status glyphs in some consoles.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
