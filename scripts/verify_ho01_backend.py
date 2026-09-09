"""
PRD-HO-01 Step 11 — backend §9 acceptance verify (static + optional Django tests).

Run from klints_backend:
  python scripts/verify_ho01_backend.py
  python scripts/verify_ho01_backend.py --run-tests
"""

from __future__ import annotations

import argparse
import os
import subprocess
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


HANDOFF_TEST_MODULES = [
    "dataruns.tests.test_handoff_package_step1",
    "dataruns.tests.test_handoff_package_step2",
    "dataruns.tests.test_handoff_package_step3",
    "dataruns.tests.test_handoff_package_step4",
    "dataruns.tests.test_handoff_package_step5",
    "dataruns.tests.test_handoff_package_step6",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run Django handoff test modules (requires installed deps).",
    )
    args = parser.parse_args()

    print("\nHO-01 Step 11 — BE §9 acceptance\n")

    gaps = read("docs/sahil/HO_01_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_HO_01_HANDOFF_PACKAGE_BIND.md")
    assert_true(bool(gaps), "HO_01_WORKING_GAPS doc exists")
    assert_true("Demo path — UC-02" in gaps, "demo path documents UC-02")
    assert_true("workflow.handoff_staged" in gaps, "audit action documented")
    assert_true("**Right:**" in gaps, "PR right note present")
    assert_true("**Gap:**" in gaps, "PR gap note present")
    assert_true(
        "Staged `handoff_package`-shaped record" in prd or "- [x]" in prd,
        "PRD §9 acceptance tracked",
    )

    schema = read("dataruns/use_cases/handoff_package.py")
    assert_true("HANDOFF_STATUS_STAGED" in schema, "STAGED status lock")
    assert_true(
        'AUDIT_ACTION_HANDOFF_STAGED = "workflow.handoff_staged"' in schema,
        "audit action constant",
    )
    assert_true("build_handoff_staged_audit_metadata" in schema, "audit metadata builder")
    assert_true("serialize_handoff" in schema, "serialize_handoff present")

    stage = read("dataruns/use_cases/handoff_stage.py")
    assert_true("create_or_get_staged_handoff" in stage, "create service present")
    assert_true("stage_handoff_for_package" in stage, "POST stage helper present")

    handoffs_urls = read("dataruns/handoffs_urls.py")
    assert_true('name="handoff-detail"' in handoffs_urls, "handoff-detail URL")
    assert_true('name="handoff-list"' in handoffs_urls, "handoff-list URL")

    build_urls = read("dataruns/build_packages_urls.py")
    assert_true('name="build-package-handoff"' in build_urls, "build-package-handoff URL")

    views = read("dataruns/use_cases/views.py")
    assert_true("HandoffPackage" in views, "HandoffPackage wired in views")
    assert_true("Handoff has not been staged" in views, "never-staged 404 detail")

    acceptance_tests = {
        "dataruns/tests/test_handoff_package_step3.py": [
            "test_qa_pass_auto_creates_handoff",
            "test_fail_qa_raises_409",
            "test_qa_package_mismatch_raises_409",
        ],
        "dataruns/tests/test_handoff_package_step5.py": [
            "test_create_audits_once_with_full_metadata",
            "test_http_post_audits_get_does_not",
        ],
        "dataruns/tests/test_handoff_package_step6.py": [
            "test_s8_qa_pass_auto_creates_staged_handoff",
            "test_s8_qa_fail_post_handoff_409",
            "test_audit_workflow_handoff_staged_on_create_only",
            "test_uc02_be_journey_studio_qa_pass_to_handoff_apis",
        ],
    }
    for rel, names in acceptance_tests.items():
        body = read(rel)
        for name in names:
            assert_true(name in body, f"acceptance test present: {name}")

    expected_test_counts = {
        "dataruns/tests/test_handoff_package_step1.py": 9,
        "dataruns/tests/test_handoff_package_step2.py": 6,
        "dataruns/tests/test_handoff_package_step3.py": 12,
        "dataruns/tests/test_handoff_package_step4.py": 12,
        "dataruns/tests/test_handoff_package_step5.py": 8,
        "dataruns/tests/test_handoff_package_step6.py": 12,
    }
    total_tests = 0
    for rel, expected in expected_test_counts.items():
        body = read(rel)
        actual = body.count("\n    def test_")
        total_tests += actual
        assert_true(
            actual == expected,
            f"test count {rel}",
            f"expected {expected}, found {actual}",
        )
    assert_true(total_tests == 59, "handoff BE test total", f"expected 59, found {total_tests}")

    print("\nHO-01 Step 12 — PR readiness\n")
    assert_true("## Step 12 — PR (manual)" in gaps, "Step 12 PR section in WORKING_GAPS")
    assert_true("feature/ho-01-handoff-package-bind" in gaps, "branch name documented")
    assert_true("verify:ho01" in gaps or "verify_ho01" in gaps, "verify commands in Step 12")
    assert_true("Frontend PR title" in prd, "split FE/BE PR titles in PRD §11")

    if args.run_tests:
        print("\n  Running Django handoff test modules…")
        try:
            proc = subprocess.run(
                [sys.executable, "manage.py", "test", *HANDOFF_TEST_MODULES, "--verbosity=1"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                pass_("Django handoff test modules pass")
            else:
                fail(
                    "Django handoff test modules pass",
                    (proc.stderr or proc.stdout)[-400:],
                )
        except Exception as exc:
            fail("Django handoff test modules pass", str(exc))
    else:
        pass_("handoff test modules listed (run with --run-tests when Django env ready)")

    print(f"\n{'OK' if failed == 0 else 'FAILED'} — {failed} failure(s)\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
