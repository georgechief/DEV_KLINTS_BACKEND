"""
GAP-01 Slice F — demo seed acceptance verify (Phases 1–4 / F0.10).

Static asserts: command · offline corpus/DCS · demo path doc · honesty locks.
Optional: Django Phase 1–2 tests (small-N seed + REMEDIATE band).

Run from klints_backend:
  python scripts/verify_gap01f_backend.py
  python scripts/verify_gap01f_backend.py --run-tests
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

GAP01F_TEST_MODULES = [
    "dataruns.tests.test_seed_demo_tenant_phase1",
    "dataruns.tests.test_seed_demo_tenant_phase2",
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


def _first_call_index(src: str, name: str) -> int:
    """Index of first non-import usage of ``name(`` (skips ``from … import`` lines)."""
    needle = f"{name}("
    start = 0
    while True:
        idx = src.find(needle, start)
        if idx < 0:
            return -1
        line_start = src.rfind("\n", 0, idx) + 1
        line = src[line_start : src.find("\n", idx)]
        if line.lstrip().startswith("from ") or line.lstrip().startswith("import "):
            start = idx + len(needle)
            continue
        return idx


def main() -> int:
    global failed
    failed = 0

    parser = argparse.ArgumentParser(
        description="GAP-01F demo seed backend verify (F0.10).",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run Django Phase 1–2 seed_demo_tenant tests (skipped if static fails).",
    )
    args = parser.parse_args()

    print("\nGAP-01F — Demo seed acceptance (Phases 1–4 / F0.10)\n", flush=True)

    print("  Docs + F0 locks", flush=True)
    gaps = read("docs/sahil/GAP_01_WORKING_GAPS.md")
    prd = read("docs/sahil/PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md")
    demo_path = read("docs/sahil/GAP_01F_DEMO_PATH.md")
    readme = read("docs/sahil/README.md")
    assert_true(bool(gaps), "GAP_01_WORKING_GAPS exists")
    assert_true(bool(prd), "PRD_GAP_01 exists")
    assert_true(bool(demo_path), "GAP_01F_DEMO_PATH.md exists (W9-04)")
    assert_true("GAP_01F_DEMO_PATH.md" in readme, "demo path linked from sahil README")
    assert_true(
        "verify_gap01f_backend.py" in prd,
        "verify script referenced in PRD Slice F",
    )
    assert_true("feature/gap01-slice-f-demo-seed" in gaps, "F0.1 branch documented")
    assert_true("verify_gap01f_backend.py" in gaps, "F0.10 verify script documented")
    assert_true(
        "Offline-first seed" in gaps or "offline-first" in gaps.lower(),
        "F0.2 offline-first",
    )
    assert_true(
        "Company.vertical" in gaps and "migration" in gaps,
        "F0.3 Company.vertical migration called out",
    )
    assert_true("5,000" in gaps or "5000" in gaps, "F0.4 ~5k contacts")
    assert_true("REMEDIATE" in gaps and "50" in gaps and "69" in gaps, "F0.5 REMEDIATE 50–69")
    assert_true("--reset" in gaps, "F0.6 reset idempotency")
    assert_true(
        "seed_dcs_master" in gaps and "load_use_case_pilots" in gaps,
        "F0.7 masters",
    )
    assert_true(
        "not** an in-app tour" in gaps or "not an in-app tour" in gaps.lower(),
        "F0.8 markdown tour",
    )
    assert_true(
        ("CONFIRMED_LIVE" in gaps)
        and ("no Matrix flip" in gaps or "no matrix flip" in gaps.lower()),
        "F0.9 Matrix honesty",
    )
    assert_true(
        "manago_mcp" in gaps and ("do not expand" in gaps.lower() or "not expand" in gaps.lower()),
        "F0.9 no manago_mcp expansion",
    )

    print("\n  W9-04 demo path honesty", flush=True)
    for route, label in (
        ("/integrations", "connect"),
        ("/data-consistency", "score"),
        ("/fix", "fix"),
        ("/workflow", "studio"),
        ("/qa", "qa"),
        ("/handoff", "handoff"),
        ("/signin", "signin"),
        ("/dashboard", "overview"),
    ):
        assert_true(route in demo_path, f"{label} route {route}")
    assert_true("--reset" in demo_path, "reset documented")
    assert_true("demo@example.com" in demo_path, "demo login documented")
    assert_true(
        "*.local" in demo_path or "type=\"email\"" in demo_path,
        "HTML5 email /.local caveat documented",
    )
    assert_true(
        "blocked_dcs_score" in demo_path and "Needs higher score" in demo_path,
        "blocked_dcs_score + Needs higher score honesty",
    )
    assert_true(
        "min_dcs: 70" in demo_path or "min_dcs`: 70" in demo_path or "`min_dcs: 70`" in demo_path,
        "exact min_dcs: 70 called out",
    )
    assert_true(
        "Below 70 threshold" in demo_path,
        "UI Below 70 threshold badge documented",
    )
    assert_true(
        "does **not** create a build package" in demo_path
        or "No package is pre-built by seed" in demo_path,
        "no pre-built package honesty",
    )
    assert_true(
        "not** live MCP publish" in demo_path or "not live MCP publish" in demo_path,
        "handoff not live MCP publish",
    )
    assert_true("human activation" in demo_path.lower(), "human activation path")
    assert_true("gap01f_demo_seed" in demo_path, "stub marker documented")
    assert_true(
        "shared" in demo_path.lower() and ("catalogue" in demo_path.lower() or "masters" in demo_path.lower()),
        "shared masters upsert honesty",
    )
    assert_true(
        "hard-delete" in demo_path.lower() or "does **not** hard-delete" in demo_path,
        "reset hard-delete honesty in demo path",
    )
    assert_true(
        "admin/shell (CASCADE)" not in demo_path
        and "delete tenant slug" not in demo_path.lower(),
        "demo path does not recommend CASCADE hard-delete teardown",
    )

    print("\n  Command + package surface", flush=True)
    cmd = read("dataruns/management/commands/seed_demo_tenant.py")
    assert_true("class Command" in cmd, "seed_demo_tenant Command class")
    assert_true("GAP-01" in cmd or "gap01" in cmd.lower(), "GAP-01F command identity")
    for flag in (
        "--vertical",
        "--contacts",
        "--reset",
        "--skip-masters",
        "--skip-dcs",
        "--require-remediate",
    ):
        assert_true(flag in cmd, f"flag {flag}")
    assert_true(
        "require-remediate cannot be combined with --skip-dcs" in cmd
        or (
            "require_remediate and skip_dcs" in cmd
            and "CommandError" in cmd
        ),
        "refuse --require-remediate with --skip-dcs",
    )
    email_idx = _first_call_index(cmd, "assert_email_available_for_slug")
    reset_idx = _first_call_index(cmd, "reset_demo_tenant")
    assert_true(email_idx >= 0, "assert_email_available_for_slug called")
    assert_true(reset_idx >= 0, "reset_demo_tenant called")
    assert_true(
        email_idx < reset_idx,
        "email availability checked before --reset delete",
        detail=f"email@{email_idx} reset@{reset_idx}",
    )
    assert_true("run_offline_demo_dcs" in cmd, "offline DCS wired")
    assert_true("Company.vertical" not in cmd, "no Company.vertical on command")
    assert_true(
        'password:     {password}' not in cmd and "not printed" in cmd,
        "seed does not print plaintext password",
    )

    constants = read("dataruns/demo_seed/constants.py")
    assert_true("DEFAULT_CONTACTS = 5000" in constants, "DEFAULT_CONTACTS = 5000")
    assert_true('DEFAULT_VERTICAL = "skincare"' in constants, "default vertical skincare")
    assert_true(
        'DEMO_SEED_CONFIG_MARKER = "gap01f_demo_seed"' in constants,
        "DEMO_SEED_CONFIG_MARKER value locked",
    )

    identity = read("dataruns/demo_seed/identity.py")
    assert_true("assert_email_available_for_slug" in identity, "email available helper")
    assert_true(
        "Must run **before**" in identity
        or "before ``--reset``" in identity
        or "before any destructive reset" in identity,
        "email-before-reset contract in docstring",
    )
    assert_true(
        "retired" in identity.lower() and "audit_logs" in identity,
        "reset retires tenant (audit_logs append-only)",
    )
    assert_true("existing.delete()" not in identity, "reset does not hard-delete tenant")
    assert_true(
        'update_fields=["domain"]' in identity,
        "Company.save omits updated_at (Company has no updated_at)",
    )
    assert_true("ensure_stub_connectors" in identity, "stub connectors")
    assert_true("DEMO_SEED_CONFIG_MARKER" in identity, "stub uses demo marker")
    assert_true("resolve_connector_type" in identity, "connector types via resolver")
    assert_true("demo-stub-not-a-live-token" in identity, "honest stub token string")
    assert_true("CONFIRMED_LIVE" not in identity, "no Matrix CONFIRMED_LIVE in identity")
    assert_true("manago_mcp" not in identity, "no manago_mcp expansion in identity")

    corpus = read("dataruns/demo_seed/corpus.py")
    assert_true("build_skincare_corpus" in corpus, "skincare corpus builder")
    assert_true("manago_dup" in corpus, "Manago dup mix for CI-03")
    assert_true("shopify_only" in corpus and "matched" in corpus, "corpus mix buckets")

    offline = read("dataruns/demo_seed/offline_dcs.py")
    assert_true("run_offline_demo_dcs" in offline, "run_offline_demo_dcs")
    assert_true("REMEDIATE_MIN = 50.0" in offline, "REMEDIATE_MIN = 50.0")
    assert_true("REMEDIATE_MAX = 69.999" in offline, "REMEDIATE_MAX = 69.999")
    assert_true(
        "REMEDIATE_MIN <= headline_f <= REMEDIATE_MAX" in offline,
        "in_remediate_band uses MIN/MAX",
    )
    assert_true(
        'kwargs["skip_website_scrape"] = True' in offline
        or "kwargs['skip_website_scrape'] = True" in offline,
        "skip_website_scrape forced True",
    )
    assert_true(
        '"dataruns.dcs.db_context.build_foundation_gate_context"' in offline,
        "foundation context patched for scrape skip",
    )
    assert_true("_demo_apply_tracking" in offline, "tracking stub")
    assert_true("_demo_apply_topology" in offline, "topology stub")
    assert_true("_demo_apply_rate_budget" in offline, "rate budget stub")
    assert_true(
        '"dataruns.dcs.fresh_import.run_import"' in offline,
        "run_import patched (no live connector HTTP)",
    )
    # Call site (not the import) must sit inside the atomic block after complete_import_run.
    complete_idx = offline.find("complete_import_run(run=run)")
    mark_idx = offline.find("mark_data_run_succeeded(", complete_idx)
    atomic_idx = offline.rfind("with transaction.atomic():", 0, mark_idx)
    assert_true(
        complete_idx >= 0 and mark_idx > complete_idx and atomic_idx >= 0,
        "mark_data_run_succeeded inside transaction.atomic (import+succeed atomic)",
        detail=f"atomic@{atomic_idx} complete@{complete_idx} mark@{mark_idx}",
    )
    assert_true("CONFIRMED_LIVE" not in offline, "no Matrix flip in offline_dcs")
    assert_true("manago_mcp" not in offline, "no manago_mcp in offline_dcs")

    print("\n  Django tests present", flush=True)
    p1 = read("dataruns/tests/test_seed_demo_tenant_phase1.py")
    p2 = read("dataruns/tests/test_seed_demo_tenant_phase2.py")
    assert_true(
        "test_assert_email_blocks_foreign_tenant_before_reset" in p1,
        "phase1 email-before-reset test",
    )
    assert_true(
        "test_seed_creates_identity_stubs_and_refuses_without_reset" in p1,
        "phase1 seed/reset test",
    )
    assert_true(
        "Tenant.objects.filter(slug=\"gap01f-test-demo\").exists()" in p1
        or "gap01f-test-demo" in p1,
        "phase1 proves demo slug survives foreign-email --reset",
    )
    assert_true("test_offline_dcs_lands_in_remediate_band" in p2, "phase2 REMEDIATE band test")
    assert_true(
        "test_offline_dcs_skips_website_http_scrape" in p2,
        "phase2 no website scrape test",
    )
    assert_true(
        "scrape.assert_not_called" in p2,
        "phase2 scrape mock assert_not_called",
    )
    assert_true(
        "test_command_require_remediate_rejects_skip_dcs" in p2,
        "phase2 contradict flags test",
    )
    assert_true(
        "test_command_seeds_corpus_and_remediate_band" in p2,
        "phase2 command small-N seed test",
    )
    assert_true("--require-remediate" in p2, "phase2 command uses --require-remediate")
    assert_true(
        "test_corpus_default_scale_ratios_hold" in p2,
        "phase2 5k mix ratio test",
    )
    assert_true("contacts=5000" in p2, "phase2 locks contacts=5000 mix")

    if failed:
        print(f"\nSTATIC FAILED — {failed} check(s). Skipping Django tests.\n", flush=True)
        return 1

    if args.run_tests:
        print("\n  Django tests (--run-tests)\n", flush=True)
        cmd_line = [
            sys.executable,
            "manage.py",
            "test",
            *GAP01F_TEST_MODULES,
            "--verbosity=1",
        ]
        print(f"  $ {' '.join(cmd_line)}", flush=True)
        proc = subprocess.run(cmd_line, cwd=str(ROOT))
        if proc.returncode != 0:
            fail("Django GAP-01F Phase 1–2 tests", f"exit {proc.returncode}")
            print(f"\nFAILED — {failed} check(s)\n", flush=True)
            return 1
        pass_("Django GAP-01F Phase 1–2 tests")
    else:
        print("\n  (skip Django tests — pass --run-tests to run)", flush=True)

    print("\nALL CHECKS PASSED\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
