"""
PRD-HO-02 — full acceptance verify (Phases 1–5): static + optional Django tests.

Run from klints_backend:
  python scripts/verify_ho02_backend.py
  python scripts/verify_ho02_backend.py --run-tests
  python scripts/verify_ho02_backend.py --run-tests --with-ho01-regression
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE_ROOT = ROOT.parent / "klints_frontend"
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


def read(rel: str, *, base: Path = ROOT) -> str:
    path = base / rel
    if not path.is_file():
        fail(f"file exists: {rel}")
        return ""
    return path.read_text(encoding="utf-8")


HO02_TEST_MODULES = [
    "dataruns.tests.test_handoff_ho02_phase1",
    "dataruns.tests.test_handoff_ho02_phase2",
    "dataruns.tests.test_handoff_ho02_phase3",
    "dataruns.tests.test_audit.AuditDeepLinkTests",
]

HO01_HANDOFF_REGRESSION = [
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
        help="Run Django HO-02 test modules (requires installed deps).",
    )
    parser.add_argument(
        "--with-ho01-regression",
        action="store_true",
        help="With --run-tests, also run HO-01 handoff regression modules.",
    )
    args = parser.parse_args()

    print("\nHO-02 — BE acceptance (Phases 1–5)\n")

    gaps = read("docs/sahil/HO_02_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md")
    assert_true(bool(gaps), "HO_02_WORKING_GAPS doc exists")
    assert_true("Phase 5" in gaps, "Phase 5 documented in WORKING_GAPS")
    assert_true("workflow.handoff_approved_for_activation" in gaps, "audit actions documented")
    assert_true("verify:ho02" in gaps, "FE verify command documented")
    assert_true("feature/ho-02-handoff-send-human-activation" in gaps, "branch name documented")

    print("\n  Phase 1–3 — backend core")
    activation = read("dataruns/use_cases/handoff_activation.py")
    assert_true("approve_handoff_for_activation" in activation, "approve service")
    assert_true("reject_handoff" in activation, "reject service")
    assert_true("confirm_handoff_activated" in activation, "confirm service")
    assert_true("build_approve_response" in activation, "approve response builder")

    package = read("dataruns/use_cases/handoff_package.py")
    assert_true("activation_meta" in package, "activation_meta on model helpers")
    assert_true("build_activation_meta_for_approve" in package, "activation_meta approve builder")
    assert_true('"activation_guide"' in package, "GET serialize activation_guide")

    handoffs_urls = read("dataruns/handoffs_urls.py")
    assert_true('name="handoff-approve"' in handoffs_urls, "handoff-approve URL")
    assert_true('name="handoff-reject"' in handoffs_urls, "handoff-reject URL")
    assert_true(
        'name="handoff-confirm-activated"' in handoffs_urls,
        "handoff-confirm-activated URL",
    )

    views = read("dataruns/use_cases/views.py")
    assert_true("HandoffApproveView" in views, "HandoffApproveView")
    assert_true("HandoffRejectView" in views, "HandoffRejectView")
    assert_true("HandoffConfirmActivatedView" in views, "HandoffConfirmActivatedView")

    migration = read("dataruns/migrations/0031_handoffpackage_activation_meta.py")
    assert_true("activation_meta" in migration, "activation_meta migration")

    package_py = read("dataruns/use_cases/handoff_package.py")
    assert_true(
        'AUDIT_ACTION_HANDOFF_APPROVED = "workflow.handoff_approved_for_activation"'
        in package_py,
        "audit approve action constant",
    )
    assert_true(
        'AUDIT_ACTION_HANDOFF_REJECTED = "workflow.handoff_rejected"' in package_py,
        "audit reject action constant",
    )
    assert_true(
        'AUDIT_ACTION_HANDOFF_ACTIVATED = "workflow.handoff_activated"' in package_py,
        "audit activated action constant",
    )

    stage = read("dataruns/use_cases/handoff_stage.py")
    assert_true("handoff_activation" not in stage, "HO-01 stage path does not import HO-02")

    print("\n  Phase 5 — audit deep-links (PRD §7.3, §9)")
    audit_py = read("dataruns/audit.py")
    assert_true("_HANDOFF_ACTION_PREFIX" in audit_py, "handoff audit action prefix")
    assert_true("_build_handoff_href" in audit_py, "handoff href builder")
    assert_true('"/handoff?' in audit_py, "handoff href targets /handoff")

    audit_tests = read("dataruns/tests/test_audit.py")
    assert_true("test_resolve_handoff_approved_for_activation" in audit_tests, "audit approved href test")
    assert_true("test_resolve_handoff_activated" in audit_tests, "audit activated href test")
    assert_true("test_resolve_handoff_staged" in audit_tests, "audit staged href test")
    assert_true("test_resolve_handoff_rejected" in audit_tests, "audit rejected href test")
    assert_true(
        "test_serialized_handoff_audit_event_includes_handoff_href" in audit_tests,
        "audit API serializes handoff href",
    )
    assert_true(
        "test_extract_link_fields_includes_handoff_ids" in audit_tests,
        "audit extract handoff link fields",
    )
    handoff_href_tests = sum(
        1
        for name in (
            "test_resolve_handoff_approved_for_activation",
            "test_resolve_handoff_activated",
            "test_resolve_handoff_staged",
            "test_resolve_handoff_rejected",
        )
        if name in audit_tests
    )
    assert_true(handoff_href_tests == 4, "four handoff href unit tests", str(handoff_href_tests))

    audit_views = read("dataruns/audit_views.py")
    assert_true('"handoff_id"' in audit_views, "audit API exposes handoff_id")

    print("\n  Phase 4–5 — frontend static (sibling klints_frontend)")
    if FE_ROOT.is_dir():
        fe_handoff = read("src/lib/handoff.ts", base=FE_ROOT)
        fe_route = read("src/routes/handoff.tsx", base=FE_ROOT)
        fe_audit = read("src/lib/audit.ts", base=FE_ROOT)
        fe_pkg = read("package.json", base=FE_ROOT)
        fe_verify = FE_ROOT / "scripts" / "verify-ho02-frontend.mjs"
        assert_true("approveHandoffForActivation" in fe_handoff, "FE approve API client")
        assert_true("HandoffApproveButton" in fe_route, "FE live approve control")
        assert_true("workflow.handoff" in fe_audit, "FE audit handoff deep-link")
        assert_true("handoffBypassesQaGate" in fe_handoff, "FE post-STAGE QA bypass")
        assert_true("verify:ho02" in fe_pkg, "package.json verify:ho02")
        assert_true(fe_verify.is_file(), "verify-ho02-frontend.mjs exists")
    else:
        fail("klints_frontend sibling repo present")

    print("\n  Phase 1–3 — test counts")
    expected_test_counts = {
        "dataruns/tests/test_handoff_ho02_phase1.py": 16,
        "dataruns/tests/test_handoff_ho02_phase2.py": 21,
        "dataruns/tests/test_handoff_ho02_phase3.py": 20,
    }
    total_ho02_tests = 0
    for rel, expected in expected_test_counts.items():
        body = read(rel)
        actual = body.count("\n    def test_")
        total_ho02_tests += actual
        assert_true(
            actual == expected,
            f"HO-02 test count {rel}",
            f"expected {expected}, found {actual}",
        )
    assert_true(total_ho02_tests == 57, "HO-02 BE test total", f"expected 57, found {total_ho02_tests}")

    assert_true(
        "verify_ho02_backend.py" in prd and "npm run verify:ho02" in prd,
        "PRD §10 verify commands referenced",
    )
    assert_true("- [x] Send/Approve works" in prd, "PRD §11 acceptance checked off")
    assert_true(
        "**Right:**" in gaps and "**Gap:**" in gaps,
        "PR note draft in WORKING_GAPS",
    )

    if args.run_tests:
        modules = list(HO02_TEST_MODULES)
        if args.with_ho01_regression:
            modules.extend(HO01_HANDOFF_REGRESSION)
        print("\n  Running Django test modules…")
        try:
            proc = subprocess.run(
                [sys.executable, "manage.py", "test", *modules, "--verbosity=1"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                pass_(f"Django test modules pass ({len(modules)} modules)")
            else:
                fail(
                    "Django test modules pass",
                    (proc.stderr or proc.stdout)[-400:],
                )
        except Exception as exc:
            fail("Django test modules pass", str(exc))
    else:
        pass_("HO-02 test modules listed (run with --run-tests when Django env ready)")

    print(f"\n{'OK' if failed == 0 else 'FAILED'} — {failed} failure(s)\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
