"""
PRD-CAP-01 Step 11 — backend §9 acceptance verify (static + seed + optional Django tests).

Run from klints_backend:
  python scripts/verify_cap01_backend.py
  python scripts/verify_cap01_backend.py --run-tests
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

failed = 0

CAP_TEST_MODULES = [
    "dataruns.tests.test_capability_matrix_step1",
    "dataruns.tests.test_capability_matrix_step2",
    "dataruns.tests.test_capability_matrix_step3",
    "dataruns.tests.test_capability_matrix_step4",
    "dataruns.tests.test_capability_matrix_step5",
    "dataruns.tests.test_capability_matrix_step6",
    "dataruns.tests.test_capability_matrix_step7",
    "dataruns.tests.test_capability_matrix_step10",
]


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
        help="Run Django CAP-01 test modules (requires installed deps).",
    )
    args = parser.parse_args()

    print("\nCAP-01 Step 11 — BE §9 acceptance\n")

    gaps = read("docs/sahil/CAP_01_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md")
    assert_true(bool(gaps), "CAP_01_WORKING_GAPS doc exists")
    assert_true("**Right:**" in gaps or "Right:" in gaps, "PR right note present")
    assert_true("**Gap:**" in gaps or "Gap:" in gaps, "PR gap note present")
    assert_true(
        "feature/cap-01-capability-matrix-resolver" in gaps
        or "feature/cap-01-capability-matrix-resolver" in prd,
        "branch name documented",
    )
    assert_true(
        "- [x] Matrix seed committed" in prd or "Matrix seed committed" in gaps,
        "§9 seed acceptance tracked",
    )

    # §9 — Matrix seed committed; no xlsx at runtime
    seed_rel = "dataruns/capabilities/matrix_seed.json"
    seed_path = ROOT / seed_rel
    assert_true(seed_path.is_file(), f"seed committed: {seed_rel}")
    seed = {}
    if seed_path.is_file():
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    caps = seed.get("capabilities") if isinstance(seed, dict) else None
    assert_true(isinstance(caps, list), "seed capabilities list")
    assert_true(isinstance(caps, list) and len(caps) == 40, "seed count 40")
    if isinstance(seed, dict) and seed.get("count") is not None:
        assert_true(
            int(seed["count"]) == 40,
            "seed envelope count field == 40",
        )
    assert_true(
        str(seed.get("schema_version") or "") == "1.0.0",
        "seed schema_version 1.0.0",
    )

    by_id = {
        str(row.get("capability_id") or ""): row
        for row in (caps or [])
        if isinstance(row, dict)
    }
    human = by_id.get("HUMAN.WORKFLOW.BUILD") or {}
    upsert = by_id.get("MCP.WORKFLOW.UPSERT") or {}
    publish = by_id.get("MCP.WORKFLOW.PUBLISH") or {}
    rest_list = by_id.get("RESTV2.WORKFLOW.LIST") or {}
    assert_true(human.get("status") == "CONFIRMED_LIVE", "HUMAN.WORKFLOW.BUILD CONFIRMED_LIVE")
    assert_true(
        upsert.get("status") == "DISCOVERY_REQUIRED",
        "MCP.WORKFLOW.UPSERT DISCOVERY_REQUIRED",
    )
    assert_true(upsert.get("evidence") == [], "UPSERT evidence empty in seed")
    assert_true(
        publish.get("status") == "DISCOVERY_REQUIRED",
        "MCP.WORKFLOW.PUBLISH DISCOVERY_REQUIRED",
    )
    assert_true(
        rest_list.get("status") == "CONFIRMED_LIVE",
        "RESTV2.WORKFLOW.LIST CONFIRMED_LIVE (READ — does not unlock route=MCP)",
    )

    mcp_rows = [
        row
        for cid, row in by_id.items()
        if cid.startswith("MCP.")
    ]
    assert_true(len(mcp_rows) >= 1, "MCP.* rows present in seed")
    assert_true(
        all(row.get("status") == "DISCOVERY_REQUIRED" for row in mcp_rows),
        "no fabricated MCP CONFIRMED in seed",
    )
    assert_true(
        all(row.get("evidence") == [] for row in mcp_rows),
        "all MCP.* evidence empty in committed seed",
    )

    registry = read("dataruns/capabilities/registry.py")
    assert_true("def get_capability" in registry, "get_capability present")
    assert_true("def list_capabilities" in registry, "list_capabilities present")
    assert_true("matrix_seed.json" in registry, "registry reads matrix_seed.json")
    assert_true("openpyxl" not in registry.lower(), "registry does not require openpyxl/xlsx")

    # §9 — build_package uses resolver (no blind hardcode)
    build_pkg = read("dataruns/use_cases/build_package.py")
    assert_true(
        "resolve_blueprint_capabilities" in build_pkg,
        "build_package uses resolve_blueprint_capabilities",
    )
    assert_true(
        'resolved_status": "NOT_CONFIRMED"' not in build_pkg
        and "resolved_status': 'NOT_CONFIRMED'" not in build_pkg,
        "no hardcoded NOT_CONFIRMED for non-UPSERT deps",
    )
    assert_true(
        "§5.2" in build_pkg and "immutable" in build_pkg.lower(),
        "build_package §5.2 immutability note present on serialize path",
    )

    resolver = read("dataruns/capabilities/resolver.py")
    assert_true("def resolve_blueprint_capabilities" in resolver, "resolver present")
    assert_true("def resolve_package_route" in resolver, "resolve_package_route present")

    # §9 — GET capabilities API
    urls = read("core/urls.py")
    assert_true('api/v1/capabilities/' in urls, "capabilities URL mounted")
    cap_urls = read("dataruns/capabilities_urls.py")
    assert_true('name="capability-list"' in cap_urls, "capability-list URL")
    assert_true('name="capability-detail"' in cap_urls, "capability-detail URL")
    views = read("dataruns/capabilities/views.py")
    assert_true("CapabilityListView" in views, "CapabilityListView present")
    assert_true("CapabilityDetailView" in views, "CapabilityDetailView present")
    write_methods = re.findall(
        r"(?m)^\s*def (post|patch|put|delete)\s*\(",
        views,
    )
    assert_true(
        write_methods == [],
        "no write HTTP handlers on capabilities views",
        detail=str(write_methods) if write_methods else "",
    )

    # §9 — writeback option B
    wb_caps = read("dataruns/writebacks/capabilities.py")
    assert_true("option B" in wb_caps, "writeback option B documented")
    assert_true("TODO(CAP-unify)" in wb_caps, "CAP-unify TODO present")

    # Acceptance tests present
    acceptance_tests = {
        "dataruns/tests/test_capability_matrix_step2.py": [
            "test_must_seed_statuses",
            "test_no_fabricated_mcp_confirmed",
            "test_mcp_rows_have_empty_evidence",
        ],
        "dataruns/tests/test_capability_matrix_step5.py": [
            "test_uc02_package_route_human_fallback",
            "test_uc02_capability_resolution_matrix_backed",
        ],
        "dataruns/tests/test_capability_matrix_step6.py": [
            "test_list_viewer_ok_includes_mcp_and_human",
            "test_detail_unknown_404",
            "test_non_reader_role_gets_403",
        ],
        "dataruns/tests/test_capability_matrix_step7.py": [
            "test_generate_uc02_package_human_fallback_resolution",
            "test_no_fabricated_mcp_confirmed_in_committed_seed",
            "test_restv2_workflow_list_confirmed_live_does_not_unlock_mcp_route",
        ],
        "dataruns/tests/test_capability_matrix_step10.py": [
            "test_pilot_mappings_capability_ids_execute_eligible",
            "test_writeback_adapters_do_not_import_matrix_registry",
        ],
    }
    for rel, names in acceptance_tests.items():
        body = read(rel)
        for name in names:
            assert_true(name in body, f"acceptance test present: {name}")

    # FE honesty pointers (docs / sibling verify)
    assert_true("verify:cap01" in gaps or "verify-cap01" in gaps, "FE verify:cap01 documented")
    assert_true("PackageRouteHonesty" in gaps or "capability-route" in gaps, "FE route honesty documented")
    fe_verify = ROOT.parent / "klints_frontend" / "scripts" / "verify-cap01-frontend.mjs"
    assert_true(
        fe_verify.is_file(),
        "FE verify-cap01-frontend.mjs present",
        detail=str(fe_verify),
    )
    assert_true(
        "## Step 11 — §9 Acceptance" in gaps,
        "WORKING_GAPS Step 11 acceptance section present",
    )
    assert_true(
        all(
            marker in gaps
            for marker in (
                "| 10 Writeback safety | **Done**",
                "| 11 Acceptance + verify | **Done**",
            )
        ),
        "Steps 10–11 marked Done in progress table",
    )
    assert_true(
        "| 12 PR | **Ready**" in gaps or "## Step 12 — PR" in gaps,
        "Step 12 PR section Ready",
    )
    assert_true(
        "feat(CAP-01): Capability Matrix registry" in gaps
        or "feat(CAP-01): Capability Matrix registry" in prd,
        "PR title documented",
    )

    print("\nCAP-01 Step 11 — optional Django tests\n")
    if args.run_tests:
        print("  Running Django CAP-01 test modules…")
        try:
            proc = subprocess.run(
                [sys.executable, "manage.py", "test", *CAP_TEST_MODULES, "--verbosity=1"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                pass_("Django CAP-01 test modules pass")
            else:
                fail(
                    "Django CAP-01 test modules pass",
                    (proc.stderr or proc.stdout)[-500:],
                )
        except Exception as exc:
            fail("Django CAP-01 test modules pass", str(exc))
    else:
        pass_("CAP-01 test modules listed (run with --run-tests when Django env ready)")

    print(f"\n{'OK' if failed == 0 else 'FAILED'} — {failed} failure(s)\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
