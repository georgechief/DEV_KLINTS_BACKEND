"""
PRD-DCS-10 Step 4 — backend v1 acceptance verify (static + optional Django tests).

Run from klints_backend:
  python scripts/verify_dcs10_fresh_import_backend.py
  python scripts/verify_dcs10_fresh_import_backend.py --run-tests
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

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

DCS10_V1_TEST_MODULES = [
    "dataruns.tests.test_dcs_fresh_import_before_score",
    "dataruns.tests.test_dcs_slice_e_pin_joins",
    "dataruns.tests.test_dcs_orchestrate",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_latest_run_includes_fresh_imports_summary",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_failed_run_includes_fresh_import_failed_platform",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_active_run_exposes_fresh_imports_when_present",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_legacy_run_without_fresh_imports_omits_field",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_running_active_run_without_fresh_imports_omits_field",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_fresh_imports_coerces_string_data_run_id",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_status_api_includes_fresh_import_fields",
    "dataruns.tests.test_dcs_app_status.DcsAppStatusTests.test_invalid_fresh_import_failed_platform_is_omitted",
]


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
        description="DCS-10 fresh import v1 backend verify (PRD §8 / Step 4).",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run Django DCS-10 v1 test modules (skipped if static checks fail).",
    )
    args = parser.parse_args()

    print("\nDCS-10 Step 4 — BE v1 acceptance (slices A+B+C)\n", flush=True)

    gaps = read("docs/sahil/DCS_10_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md")
    verify_self = ROOT / "scripts/verify_dcs10_fresh_import_backend.py"
    assert_true(verify_self.is_file(), "verify_dcs10_fresh_import_backend.py present")
    assert_true(bool(gaps), "DCS_10_WORKING_GAPS exists")
    assert_true(bool(prd), "PRD_DCS_10 exists")
    assert_true(
        "feature/dcs-10-fresh-import-before-score" in gaps,
        "branch intent documented",
    )
    assert_true(
        "## Step 4" in gaps and "verify_dcs10_fresh_import_backend.py" in gaps,
        "Step 4 verify section in WORKING_GAPS",
    )
    assert_true("Slice A" in gaps and "Slice B" in gaps and "Slice C" in gaps, "v1 slices documented")

    fresh = read("dataruns/dcs/fresh_import.py")
    orchestrate = read("dataruns/dcs/orchestrate.py")
    status = read("dataruns/dcs/status.py")
    tests = read("dataruns/tests/test_dcs_fresh_import_before_score.py")
    orch_tests = read("dataruns/tests/test_dcs_orchestrate.py")
    bootstrap_helpers = read("tenants/tests/bootstrap_test_helpers.py")
    connector_views = read("tenants/connector_views.py")
    bootstrap_health = read("dataruns/connectors/bootstrap_health.py")
    connector_list_tests = read("tenants/tests/test_connector_list_latest_bootstrap.py")
    dcs01 = read("docs/dcs_scoring/PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md")

    assert_true(
        "def assert_fresh_imports_cover_connected" in fresh,
        "Slice A: assert_fresh_imports_cover_connected",
    )
    assert_true(
        "assert_fresh_imports_cover_connected(" in fresh
        and fresh.count("assert_fresh_imports_cover_connected(") >= 2,
        "Slice A: assert called after import loop",
    )
    assert_true(
        "dcs-fresh-import:" in fresh and 'triggered_by": "dcs_score"' in fresh,
        "fresh import DataRun naming + triggered_by",
    )
    assert_true(
        "ELIGIBLE_CONNECTOR_NAMES" in fresh and "ELIGIBLE_CONNECTOR_STATUSES" in fresh,
        "Slice A: eligibility constants from enqueue (no drift)",
    )
    assert_true(
        "assert_fresh_imports_cover_connected(" in orchestrate,
        "Slice A: orchestrate guard before snapshot",
    )
    refresh_idx = orchestrate.find("refresh = refresh_connected_platforms_for_dcs")
    snapshot_idx = orchestrate.find("snapshot = build_dcs_run_snapshot")
    assert_true(
        refresh_idx != -1 and snapshot_idx != -1 and refresh_idx < snapshot_idx,
        "orchestrate: refresh before build_dcs_run_snapshot",
    )
    assert_true(
        "fresh_import_failed_platform" in orchestrate,
        "orchestrate sets fresh_import_failed_platform on failure",
    )
    assert_true(
        "def _serialize_fresh_imports_for_status" in status,
        "Slice B: status serializer",
    )
    assert_true(
        '"fresh_imports"' in status or "'fresh_imports'" in status,
        "Slice B: fresh_imports on run summary",
    )
    assert_true(
        "fresh_import_failed_platform" in status,
        "Slice B: fresh_import_failed_platform on run summary",
    )
    assert_true(
        "ELIGIBLE_CONNECTOR_NAMES" in status,
        "Slice B: platform allowlist on status payload",
    )
    assert_true(
        "DcsFreshImportPipelineIntegrationTests" in tests,
        "Slice C: integration test class",
    )
    assert_true(
        "wraps=refresh_connected_platforms_for_dcs" in tests,
        "Slice C: refresh spy (G9)",
    )
    assert_true(
        "test_pipeline_fresh_imports_both_connected_platforms" in tests,
        "Slice C: dual-platform integration",
    )
    assert_true(
        "platform=platform" in bootstrap_helpers
        or "platform=platform," in bootstrap_helpers,
        "bootstrap helper passes platform to persist_normalized_records",
    )
    assert_true(
        "mock_assert_fresh_imports.assert_called_once_with" in orch_tests,
        "orchestrate unit test invokes assert guard on success path",
    )
    assert_true(
        "PRD-DCS-10" in dcs01 or "fresh import" in dcs01.lower(),
        "DCS-01 pointer to mandatory fresh import",
    )
    assert_true(
        "verify_dcs10_fresh_import_backend.py" in prd,
        "PRD references verify script",
    )
    assert_true(
        "verify_dcs10_fresh_import_backend.py --run-tests" in prd,
        "PRD §8 verify command documented",
    )
    assert_true(
        "find_latest_dcs_fresh_import_data_run" in read("dataruns/connectors/base.py"),
        "Slice F: find latest DCS fresh import helper",
    )
    assert_true(
        "resolve_last_data_refresh_data_run" in bootstrap_health,
        "Slice F: resolve last data refresh helper",
    )
    assert_true(
        "last_data_refresh" in connector_views,
        "Slice F: last_data_refresh on connector list API",
    )
    assert_true(
        "test_last_data_refresh_prefers_newer_dcs_fresh_import" in connector_list_tests,
        "Slice F: connector list test for DCS fresh import stats",
    )
    assert_true(
        "test_last_data_refresh_falls_back_to_bootstrap_when_fresh_import_failed"
        in connector_list_tests,
        "Slice F: failed fresh import falls back to bootstrap counts",
    )
    slice_e_tests = read("dataruns/tests/test_dcs_slice_e_pin_joins.py")
    assert_true(
        "_connector_raw_for_import_data_run" in read("dataruns/dcs/lifecycle_join.py"),
        "Slice E: pin helper on lifecycle_join",
    )
    assert_true(
        "pinned_snapshot_ids=pinned_snapshot_ids" in read("dataruns/dcs/snapshot.py"),
        "Slice E: snapshot passes pinned snapshot ids to joins",
    )
    assert_true(
        "test_connector_raw_for_platform_pins_not_latest" in slice_e_tests,
        "Slice E: pin beats latest snapshot test",
    )

    import django

    django.setup()

    from dataruns.dcs.fresh_import import (
        assert_fresh_imports_cover_connected,
        refresh_connected_platforms_for_dcs,
    )
    from dataruns.dcs.status import _serialize_fresh_imports_for_status

    assert_true(callable(assert_fresh_imports_cover_connected), "assert importable")
    assert_true(callable(refresh_connected_platforms_for_dcs), "refresh importable")
    sample = _serialize_fresh_imports_for_status(
        {
            "fresh_imports": {
                "shopify": {
                    "data_run_id": 1,
                    "window_end": "2026-08-28T00:00:00Z",
                    "counts": {"contacts": 9},
                }
            }
        }
    )
    assert_true(
        sample == {
            "shopify": {"data_run_id": 1, "window_end": "2026-08-28T00:00:00Z"}
        },
        "status serializer strips internal fields",
    )

    print(f"\nStatic: {failed} failure(s)\n", flush=True)

    if failed and args.run_tests:
        print("Skipping --run-tests (fix static checks first).\n", flush=True)
        return 1

    if args.run_tests:
        print("Running Django tests …\n", flush=True)
        cmd = [
            sys.executable,
            "manage.py",
            "test",
            *DCS10_V1_TEST_MODULES,
            "--verbosity=1",
        ]
        result = subprocess.run(cmd, cwd=ROOT, check=False)
        if result.returncode != 0:
            fail("Django test suite", f"exit {result.returncode}")
        else:
            pass_("Django DCS-10 v1 test modules")

    print(
        f"\n{'ALL PASS' if failed == 0 else f'{failed} CHECK(S) FAILED'} — "
        "manual QA §9 still required on staging (Re-run without reconnect).\n",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
