#!/usr/bin/env python3
"""
PRD-M3-DEMO-01 Phase 5 — static acceptance gate + optional Django tests.

Live Shopify klints-dev demo path (not seed_demo_tenant as M3 AC).

Run from klints_backend:
  python scripts/verify_m3_demo01_backend.py
  python scripts/verify_m3_demo01_backend.py --run-tests
"""

from __future__ import annotations

import argparse
import os
import re
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

DEMO01_TEST_MODULES = [
    "dataruns.tests.test_bootstrap_health",
    "tenants.tests.test_connector_list_latest_bootstrap",
]

PHASE_DOCS = [
    "docs/sahil/M3_DEMO_01_PHASE_0.md",
    "docs/sahil/M3_DEMO_01_PHASE_1.md",
    "docs/sahil/M3_DEMO_01_PHASE_2.md",
    "docs/sahil/M3_DEMO_01_PHASE_3.md",
    "docs/sahil/M3_DEMO_01_PHASE_4.md",
    "docs/sahil/M3_DEMO_01_PHASE_5.md",
    "docs/sahil/M3_DEMO_01_PHASE_6.md",
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


def _fn_body(src: str, name: str) -> str:
    m = re.search(rf"def {re.escape(name)}\([\s\S]*?(?=\ndef |\Z)", src)
    return m.group(0) if m else ""


def main() -> int:
    global failed
    failed = 0

    parser = argparse.ArgumentParser(
        description="M3-DEMO-01 backend verify (Phase 5 static + optional tests).",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run Django bootstrap_health tests (skipped if static checks fail).",
    )
    args = parser.parse_args()

    print("\nM3-DEMO-01 — Live Shopify demo path verify (Phase 5)\n", flush=True)

    print("  Docs + phase chain", flush=True)
    prd = read("docs/sahil/PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md")
    gaps = read("docs/sahil/M3_DEMO_01_WORKING_GAPS.md")
    shopify_path = read("docs/sahil/M3_DEMO_01_SHOPIFY_PATH.md")
    gap01f = read("docs/sahil/GAP_01F_DEMO_PATH.md")
    readme = read("docs/sahil/README.md")
    phase0 = read("docs/sahil/M3_DEMO_01_PHASE_0.md")
    verify_self = ROOT / "scripts/verify_m3_demo01_backend.py"
    assert_true(verify_self.is_file(), "verify_m3_demo01_backend.py present")
    assert_true(bool(prd), "PRD_M3_DEMO_01 exists")
    assert_true(bool(gaps), "M3_DEMO_01_WORKING_GAPS exists")
    assert_true(bool(shopify_path), "M3_DEMO_01_SHOPIFY_PATH.md exists")
    assert_true(
        "verify_m3_demo01_backend.py" in prd,
        "verify script referenced in PRD brief",
    )
    assert_true(
        "verify_m3_demo01_backend.py" in gaps,
        "WORKING_GAPS references verify script",
    )
    assert_true(
        "feature/m3-demo-01-shopify-klints-dev" in gaps,
        "branch documented in WORKING_GAPS",
    )
    assert_true(
        "PRD_M3_DEMO_01" in readme
        and "M3_DEMO_01_SHOPIFY_PATH" in readme
        and "M3_DEMO_01_PHASE_6" in readme,
        "README links PRD + SHOPIFY_PATH + PHASE_6",
    )
    for rel in PHASE_DOCS:
        assert_true((ROOT / rel).is_file(), f"phase doc {rel.split('/')[-1]}")
    assert_true(
        "M3_DEMO_01_PHASE_6.md" in prd,
        "PRD progress links PHASE_6",
    )
    phase5 = read("docs/sahil/M3_DEMO_01_PHASE_5.md")
    assert_true(bool(phase5), "M3_DEMO_01_PHASE_5.md exists")
    assert_true(
        "verify_m3_demo01_backend.py" in phase5,
        "Phase 5 documents verify script",
    )
    assert_true(
        "--run-tests" in phase5,
        "Phase 5 documents --run-tests",
    )

    print("\n  Live shop + runbook (klints-dev)", flush=True)
    assert_true("klints-dev" in shopify_path, "SHOPIFY_PATH names klints-dev")
    assert_true(
        "simple-sample-data" in shopify_path.lower(),
        "SHOPIFY_PATH links Simple Sample Data app",
    )
    assert_true(
        "admin.shopify.com/store/klints-dev/apps/simple-sample-data" in shopify_path,
        "SHOPIFY_PATH has concrete Simple Sample Data Admin URL",
    )
    assert_true(
        "PRD_DCS_10" in shopify_path or "DCS-10" in shopify_path,
        "SHOPIFY_PATH cites DCS-10 fresh import",
    )
    assert_true(
        "Credential checklist" in shopify_path or "credential checklist" in shopify_path.lower(),
        "SHOPIFY_PATH has credential checklist",
    )
    assert_true(
        "apis.klints.io/api/v1/connectors/shopify/callback" in shopify_path,
        "SHOPIFY_PATH documents staging OAuth callback host",
    )
    assert_true(
        "apis.klints.io" in phase0,
        "PHASE_0 locks staging callback host",
    )
    for route, label in (
        ("/integrations", "connect"),
        ("/data-consistency", "score"),
        ("/fix", "fix"),
        ("/workflow", "studio"),
        ("/qa", "qa"),
        ("/handoff", "handoff"),
    ):
        assert_true(route in shopify_path, f"SHOPIFY_PATH route {label} ({route})")
    assert_true(
        "read_locations" in shopify_path,
        "SHOPIFY_PATH documents read_locations scope",
    )
    assert_true(
        "GAP_01F_DEMO_PATH" in shopify_path
        and ("not** M3 AC" in shopify_path or "not M3 AC" in shopify_path),
        "SHOPIFY_PATH cites GAP_01F as non-AC",
    )
    assert_true(
        "stop-and-flag" in shopify_path.lower(),
        "SHOPIFY_PATH documents Manago stop-and-flag",
    )

    print("\n  Theater register + honesty locks", flush=True)
    assert_true(
        "seed_demo_tenant" in prd
        and "NOT the M3 demo AC" in prd,
        "PRD D2: seed is NOT the M3 demo AC",
    )
    assert_true(
        "OBS-01B" in prd or "PRD_M3_OBS_01B" in prd,
        "PRD points Grafana to OBS-01B (separate)",
    )
    assert_true("Gate B" in prd, "PRD documents Gate B for DP1 partner cutover")
    assert_true("HO-02" in prd, "PRD documents human Handoff HO-02")
    assert_true(
        "## 8. Theater register" in prd or "## Theater register" in prd,
        "PRD has theater register section",
    )
    assert_true(
        "## 7. Theater register" in shopify_path
        or "## Theater register" in shopify_path,
        "SHOPIFY_PATH has theater register",
    )
    assert_true(
        "Contacts filled by `seed_demo_tenant` for M3" in prd
        and "Wrong SoT" in prd,
        "PRD theater rejects seed-for-M3",
    )
    assert_true(
        "Contacts filled by `seed_demo_tenant` for M3" in shopify_path
        and "Wrong SoT" in shopify_path,
        "SHOPIFY_PATH theater rejects seed-for-M3",
    )
    assert_true(
        "Grafana alerts done in this PR" in prd and "OBS-01B" in prd,
        "PRD theater lists Grafana as OBS-01B (not done here)",
    )
    assert_true(
        "MCP publish" in shopify_path or "MCP publish" in prd,
        "Theater forbids MCP publish claim",
    )
    assert_true(
        "score &lt; 70" in shopify_path
        or "score < 70" in shopify_path
        or "until DCS ≥ **70**" in shopify_path
        or "below 70" in shopify_path.lower(),
        "SHOPIFY_PATH documents Studio gate at score < 70",
    )
    assert_true(
        "seed_demo_tenant is the M3 demo AC" not in prd,
        "PRD does not affirm seed as M3 AC",
    )
    assert_true(
        "Do not claim" in gaps or "Do not claim" in shopify_path,
        "WORKING_GAPS / path has do-not-claim register",
    )

    print("\n  Phase 2 connect/import code", flush=True)
    settings = read("core/settings/base.py")
    env_ex = read(".env.example")
    bootstrap = read("dataruns/connectors/bootstrap_health.py")
    tests = read("dataruns/tests/test_bootstrap_health.py")
    assert_true(
        "read_locations" in settings and "SHOPIFY_SCOPES" in settings,
        "settings SHOPIFY_SCOPES includes read_locations",
    )
    assert_true(
        "read_locations" in env_ex and "SHOPIFY_SCOPES" in env_ex,
        ".env.example SHOPIFY_SCOPES includes read_locations",
    )
    assert_true(
        "SHOPIFY_ADMIN_SCOPE_CAPABILITY_HANDLES" in bootstrap
        and (
            '"read_locations"' in bootstrap or "'read_locations'" in bootstrap
        ),
        "bootstrap_health read_locations capability handle",
    )
    assert_true(
        "recompute_health_report_summary" in bootstrap,
        "stale health recompute helper present",
    )
    assert_true(
        "reconcile_connector_status_from_summary" in bootstrap,
        "connector status reconcile helper present",
    )
    payload_fn = _fn_body(bootstrap, "build_latest_bootstrap_payload")
    assert_true(bool(payload_fn), "build_latest_bootstrap_payload defined")
    assert_true(
        "recompute_health_report_summary" in payload_fn,
        "latest_bootstrap payload recomputes health from snapshot",
    )
    partial_fn = _fn_body(bootstrap, "_partial_fetch_issues")
    assert_true(bool(partial_fn), "_partial_fetch_issues defined")
    assert_true(
        "% 250" not in partial_fn and "mod 250" not in partial_fn.lower(),
        "PARTIAL_FETCH %250 heuristic removed",
    )
    assert_true(
        "truncat" in partial_fn and "partial" in partial_fn,
        "PARTIAL_FETCH from snapshot notes only",
    )

    connector_views = read("tenants/connector_views.py")
    assert_true(
        "reconcile_connector_status_from_summary" in connector_views,
        "connector list reconciles status from recomputed summary",
    )
    assert_true(
        "Recompute health / reconcile status before reading connector.status"
        in connector_views,
        "connector list reads status after bootstrap reconcile",
    )
    list_tests = read("tenants/tests/test_connector_list_latest_bootstrap.py")
    assert_true(
        "test_list_reconciles_stale_degraded_status_after_partial_fetch_retire"
        in list_tests,
        "connector list stale-degraded reconcile test present",
    )
    assert_true(
        "StaleHealthReportRecomputeTests" in tests,
        "stale health recompute tests present",
    )
    assert_true(
        "test_shopify_exact_page_size_orders_not_partial_fetch" in tests,
        "exact page-size orders not PARTIAL_FETCH test",
    )

    print("\n  Full path + DP1 (Phase 4 docs)", flush=True)
    phase4 = read("docs/sahil/M3_DEMO_01_PHASE_4.md")
    assert_true(bool(phase4), "M3_DEMO_01_PHASE_4.md exists")
    assert_true(
        "blocked_dcs_score" in phase4,
        "Phase 4 documents blocked_dcs_score at low score",
    )
    assert_true(
        "DP1 readiness" in phase4,
        "Phase 4 DP1 readiness section",
    )
    assert_true(
        "GAP_01F" in phase4,
        "Phase 4 contrasts live path vs GAP_01F seed",
    )
    assert_true(
        "/api/v1/use-cases/recommendations/" in phase4,
        "Phase 4 cites recommendations API",
    )
    assert_true(
        "Gate B" in phase4,
        "Phase 4 DP1 blocked on Gate B",
    )
    assert_true(
        "HO-02" in phase4,
        "Phase 4 documents HO-02 human Send",
    )

    print("\n  Legacy seed path stays separate (GAP-01F)", flush=True)
    assert_true(bool(gap01f), "GAP_01F_DEMO_PATH exists for contrast")
    assert_true("seed_demo_tenant" in gap01f, "GAP-01F documents seed command")
    assert_true(
        "gap01f_demo_seed" in gap01f,
        "GAP-01F documents stub marker",
    )
    assert_true(
        "not live OAuth" in gap01f.lower() or "demo stubs" in gap01f.lower(),
        "GAP-01F documents stubs / not live OAuth",
    )
    assert_true(
        "M3-DEMO-01" not in gap01f,
        "GAP-01F not rebranded as M3-DEMO-01 AC",
    )

    print("\n  Phase 3 smoke evidence documented", flush=True)
    phase3 = read("docs/sahil/M3_DEMO_01_PHASE_3.md")
    assert_true(bool(phase3), "M3_DEMO_01_PHASE_3.md exists")
    assert_true(
        "Simple Sample Data" in phase3,
        "Phase 3 cites Simple Sample Data source",
    )
    assert_true(
        "local" in phase3.lower() and "contacts" in phase3.lower() and "orders" in phase3.lower(),
        "Phase 3 documents local contact/order evidence",
    )
    assert_true(
        bool(re.search(r"\b\d{2,}\b", phase3)),
        "Phase 3 includes numeric import counts",
    )
    assert_true(
        "seed_demo_tenant" in phase3.lower()
        or "not** seed" in phase3.lower()
        or "not seed" in phase3.lower()
        or "Path is **not**" in phase3,
        "Phase 3 affirms path is not seed",
    )
    assert_true(
        "latest_bootstrap" in phase3 or "/api/v1/connectors/" in phase3,
        "Phase 3 documents API evidence path",
    )

    print("\n  Employer §11 checklist template (Phase 6 prep)", flush=True)
    for item in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"):
        assert_true(f"**{item}**" in prd, f"PRD §11 item {item} present")
    assert_true(
        "verify_m3_demo01_backend.py" in prd and "**A5**" in prd,
        "§11 A5 tied to verify script",
    )
    phase6 = read("docs/sahil/M3_DEMO_01_PHASE_6.md")
    assert_true(bool(phase6), "M3_DEMO_01_PHASE_6.md exists")
    assert_true(
        "employer acceptance" in phase6.lower() or "§11" in phase6,
        "Phase 6 has §11 paste block",
    )
    for item in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"):
        assert_true(f"**{item}**" in phase6, f"Phase 6 §11 item {item} present")
    assert_true(
        "PR draft" in phase6 or "PR title" in phase6.lower(),
        "Phase 6 includes PR draft",
    )
    assert_true(
        "do **not** agent-commit" in phase6.lower()
        or "Manual commit" in phase6
        or "user commits manually" in phase6.lower(),
        "Phase 6 notes manual commit (no agent commit)",
    )

    print(flush=True)
    if failed:
        print(f"FAILED ({failed} static check(s))", flush=True)
        if args.run_tests:
            print("Skipping --run-tests because static checks failed.", flush=True)
        return 1

    print("M3-DEMO-01 static checks: PASS", flush=True)
    print(
        "NOTE: Sahil ship complete (local-only A3). Staging A2/A10 = residual ops "
        "(see docs/sahil/M3_DEMO_01_PHASE_6.md).",
        flush=True,
    )

    if args.run_tests:
        print("\n  Django tests (--run-tests)\n", flush=True)
        cmd = [
            sys.executable,
            "manage.py",
            "test",
            *DEMO01_TEST_MODULES,
            "--keepdb",
            "-v1",
        ]
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode != 0:
            print("\nDjango tests: FAIL", flush=True)
            return result.returncode
        print("\nDjango tests: PASS", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
