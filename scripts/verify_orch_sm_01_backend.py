"""
PRD-GAP-01 Slice A1 — orchestration 8-state SM acceptance verify (Phases 1–4).

Run from klints_backend:
  python scripts/verify_orch_sm_01_backend.py
  python scripts/verify_orch_sm_01_backend.py --run-tests
  python scripts/verify_orch_sm_01_backend.py --run-tests --with-ho02-regression
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

ORCH_STATUSES = (
    "PENDING",
    "BLOCKED",
    "READY",
    "IN_PROGRESS",
    "AWAITING_APPROVAL",
    "DONE",
    "FAILED",
    "CANCELLED",
)

ORCH_TEST_MODULES = [
    "dataruns.tests.test_orch_sm_phase1",
    "dataruns.tests.test_orch_sm_phase2",
    "dataruns.tests.test_orch_sm_phase3",
    "dataruns.tests.test_orch_sm_pack_alignment",
    "dataruns.tests.test_orch_plan_api",
]

HO02_REGRESSION_MODULE = "dataruns.tests.test_handoff_ho02_phase3"


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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run Django ORCH SM test modules (requires venv deps).",
    )
    parser.add_argument(
        "--with-ho02-regression",
        action="store_true",
        help="With --run-tests, also run HO-02 phase3 API regression module.",
    )
    args = parser.parse_args()

    print("\nGAP-01A — OrchestrationTask 8-state SM (Phases 1–4)\n")

    gaps = read("docs/sahil/GAP_01_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md")
    assert_true(bool(gaps), "GAP_01_WORKING_GAPS doc exists")
    assert_true("Slice A1" in gaps, "Slice A1 documented in WORKING_GAPS")
    assert_true("verify_orch_sm_01_backend.py" in gaps, "verify script documented in WORKING_GAPS")
    assert_true("verify_orch_sm_01_backend.py" in prd, "verify script referenced in PRD")

    print("\n  Phase 1 — constants, model, migration")
    constants = read("dataruns/orchestration/task_constants.py")
    for status in ORCH_STATUSES:
        assert_true(f'ORCH_STATUS_{status}' in constants or f'"{status}"' in constants, f"status {status}")
    assert_true("len(ORCH_STATUS_ENUM), 8)" in read("dataruns/tests/test_orch_sm_phase1.py"), "8-status test")
    assert_true("ORCH_ALLOWED_STATUS_TRANSITIONS" in constants, "transition matrix")
    assert_true("is_allowed_orch_transition" in constants, "transition helper")
    assert_true("is_orch_idempotent_transition" in constants, "idempotent helper")
    assert_true("serialize_orch_task" in constants, "serialize helper")
    assert_true(
        'AUDIT_ACTION_ORCH_TASK_CREATED = "workflow.orchestration_task_created"'
        in constants,
        "audit create action",
    )
    assert_true(
        'AUDIT_ACTION_ORCH_TASK_TRANSITIONED = "workflow.orchestration_task_transitioned"'
        in constants,
        "audit transition action",
    )
    assert_true('ORCH_ERROR_INVALID_TRANSITION = "invalid_transition"' in constants, "error code invalid_transition")
    assert_true('ORCH_ERROR_FORBIDDEN = "forbidden"' in constants, "error code forbidden")
    assert_true('ORCH_ERROR_NOT_FOUND = "not_found"' in constants, "error code not_found")
    assert_true(
        "test_transition_matrix_edge_count" in read("dataruns/tests/test_orch_sm_phase1.py"),
        "16-edge transition test",
    )

    pack_schema = ROOT / (
        "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
        "/03_Machine_Contracts/orchestration_task.schema.json"
    )
    assert_true(pack_schema.is_file(), "pack orchestration_task.schema.json exists")
    pack_alignment = read("dataruns/tests/test_orch_sm_pack_alignment.py")
    assert_true("test_pack_status_enum_matches_constants" in pack_alignment, "pack status parity test")
    assert_true(
        "test_plan_fix_task_fields_compatible_with_persisted_create" in pack_alignment,
        "plan-to-persisted alignment test",
    )

    models = read("dataruns/orchestration/models.py")
    assert_true("class OrchestrationTask" in models, "OrchestrationTask model")
    assert_true("orch_task_co_idempotency_uniq" in models, "idempotency unique constraint")

    migration = read("dataruns/migrations/0032_orchestrationtask.py")
    assert_true("OrchestrationTask" in migration, "0032 migration")
    assert_true('default="PENDING"' in migration, "default status PENDING in migration")

    apps = read("dataruns/apps.py")
    assert_true(
        "dataruns.orchestration import models" in apps,
        "orchestration models registered in apps.py",
    )

    print("\n  Phase 2 — services")
    transitions = read("dataruns/orchestration/task_transitions.py")
    assert_true("create_orchestration_task" in transitions, "create service")
    assert_true("transition_orchestration_task" in transitions, "transition service")
    assert_true("OrchTransitionError" in transitions, "OrchTransitionError")
    assert_true("select_for_update" in transitions, "row lock on transition")
    assert_true("get_orchestration_task" in transitions, "company-scoped getter")
    assert_true("ORCH_TERMINAL_STATUSES" in transitions, "terminal status guard on create")
    assert_true("AWAITING_APPROVAL" in transitions and "ADMIN" in transitions, "admin approval gate in service")

    print("\n  Phase 3 — HTTP APIs")
    task_views = read("dataruns/orchestration/task_views.py")
    assert_true("OrchestrationTaskListCreateView" in task_views, "list/create view")
    assert_true("OrchestrationTaskDetailView" in task_views, "detail view")
    assert_true("OrchestrationTaskTransitionView" in task_views, "transition view")

    orch_urls = read("dataruns/orchestration_urls.py")
    assert_true('name="orchestration-plan"' in orch_urls, "plan URL preserved")
    assert_true('name="orchestration-task-list-create"' in orch_urls, "tasks list/create URL")
    assert_true('name="orchestration-task-detail"' in orch_urls, "task detail URL")
    assert_true('name="orchestration-task-transition"' in orch_urls, "task transition URL")
    assert_true(
        orch_urls.index("plan/") < orch_urls.index("tasks/"),
        "plan/ registered before tasks/",
    )

    plan_view = read("dataruns/orchestration/views.py")
    assert_true("OrchestrationPlanView" in plan_view, "plan view unchanged file")
    assert_true("build_plan" in plan_view, "plan view still uses build_plan")

    print("\n  Scope guards")
    assert_true("HandoffPackage" not in transitions, "services do not import HandoffPackage")
    assert_true("handoff_package" not in task_views, "views do not import handoff_package")

    print("\n  Phase 1–3 — test counts")
    expected_test_counts = {
        "dataruns/tests/test_orch_sm_phase1.py": 19,
        "dataruns/tests/test_orch_sm_phase2.py": 19,
        "dataruns/tests/test_orch_sm_phase3.py": 16,
        "dataruns/tests/test_orch_sm_pack_alignment.py": 8,
    }
    total_orch_tests = 0
    for rel, expected in expected_test_counts.items():
        body = read(rel)
        actual = body.count("\n    def test_")
        total_orch_tests += actual
        assert_true(
            actual == expected,
            f"ORCH SM test count {rel}",
            f"expected {expected}, found {actual}",
        )
    assert_true(total_orch_tests == 62, "ORCH SM BE test total", f"expected 62, found {total_orch_tests}")

    assert_true(
        "16-edge" in gaps or "16 edges" in gaps or "matrix count test" in gaps,
        "transition graph documented in WORKING_GAPS",
    )

    if args.run_tests:
        modules = list(ORCH_TEST_MODULES)
        if args.with_ho02_regression:
            modules.append(HO02_REGRESSION_MODULE)
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
                    (proc.stderr or proc.stdout)[-500:],
                )
        except Exception as exc:
            fail("Django test modules pass", str(exc))
    else:
        pass_("ORCH SM test modules listed (run with --run-tests when Django env ready)")

    print(f"\n{'OK' if failed == 0 else 'FAILED'} — {failed} failure(s)\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
