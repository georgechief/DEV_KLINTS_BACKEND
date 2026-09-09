"""PRD-WB-07 backend smoke — atomic claim + response hygiene static checks + tests."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _read(rel_path: str) -> str:
    path = os.path.join(ROOT, rel_path)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def main() -> int:
    print("=== WB-07 BACKEND VERIFICATION ===\n")

    pipeline = _read("dataruns/writebacks/pipeline.py")
    _assert(
        'status="executing"' in pipeline or "status='executing'" in pipeline,
        "pipeline must create WritebackJob with status=executing before adapter I/O",
    )
    _assert(
        "acquire_company_execute_lock" in pipeline,
        "pipeline must lock before claim (Option A)",
    )
    _assert(
        "consume_approval_token" in pipeline,
        "pipeline must consume approval at claim",
    )
    # Claim block must appear before _execute_intents call site.
    claim_idx = pipeline.find('status="executing"')
    if claim_idx < 0:
        claim_idx = pipeline.find("status='executing'")
    exec_idx = pipeline.find("_execute_intents(")
    _assert(claim_idx >= 0 and exec_idx > claim_idx, "claim must precede _execute_intents")
    print("pipeline: claim-before-write + lock — OK")

    run_gate = _read("dataruns/writebacks/run_gate.py")
    _assert("reclaim_stale_executing_jobs" in run_gate, "stale executing reclaim missing")
    _assert("is_in_flight_execute_job" in run_gate, "in-flight execute helper missing")
    _assert("acquire_company_execute_lock" in run_gate, "company execute lock missing")
    _assert('rollback_policy": "manual_admin_only"' in run_gate, "W6-03 rollback_policy missing")
    _assert("rollback_auto_on_error" in run_gate, "W6-03 rollback_auto_on_error missing")
    _assert("stale_executing_reclaim_minutes" in run_gate, "W6-03 stale reclaim minutes missing")
    granted_fn = run_gate.split("def _latest_granted_approval", 1)[1][:1200]
    _assert(
        "expires_at__gt=timezone.now()" in granted_fn,
        "C3: _latest_granted_approval must TTL-bound with expires_at__gt",
    )
    _assert(
        "return qs.filter(writeback_job_id=preview_job.id)" in granted_fn
        or "writeback_job_id=preview_job.id).order_by" in granted_fn,
        "C4: granted approval must not fall back to older preview jobs",
    )
    approvals = _read("dataruns/writebacks/approvals/service.py")
    expire_fn = approvals.split("def _expire_if_needed", 1)[1][:500]
    _assert(
        "Status.APPROVED" in expire_fn,
        "C3: _expire_if_needed must expire APPROVED past TTL",
    )
    print("run_gate: executing block + stale reclaim + W6-03 policy — OK")

    exceptions = _read("dataruns/writebacks/exceptions.py")
    _assert("dcs_run_required" in exceptions, "WritebackDcsRunRequiredError code missing")
    print("exceptions: dcs_run_required — OK")

    serializers = _read("dataruns/writebacks/serializers.py")
    _assert("mask_entity_key" in serializers, "serialize_intent must mask entity_key")
    _assert(
        "sanitize_execute_result_for_client" in serializers,
        "serialize_intent must sanitize execute_result",
    )
    print("serializers: PII mask + execute_result sanitize — OK")

    views = _read("dataruns/writebacks/views.py")
    _assert("diff_hash_mismatch" in views, "diff_hash_mismatch response missing")
    _assert(
        "revoke_approval_on_diff_hash_mismatch" in views,
        "C2: execute mismatch revokes stale APPROVED grant",
    )
    approvals = _read("dataruns/writebacks/approvals/service.py")
    _assert(
        "def revoke_approval_on_diff_hash_mismatch" in approvals,
        "C2: revoke_approval_on_diff_hash_mismatch helper",
    )
    _assert(
        "Status.REVOKED" in approvals
        and "diff_hash_mismatch" in approvals.split("def revoke_approval_on_diff_hash_mismatch", 1)[1][:1200],
        "C2: mismatch revoke sets REVOKED with diff_hash_mismatch reason",
    )
    _assert(
        "def revoke_superseded_grants_for_new_preview" in approvals,
        "C4: revoke_superseded_grants_for_new_preview helper",
    )
    _assert(
        "superseded_by_new_preview"
        in approvals.split("def revoke_superseded_grants_for_new_preview", 1)[1][:1600],
        "C4: new dry-run revokes older APPROVED with superseded_by_new_preview",
    )
    pipeline = _read("dataruns/writebacks/pipeline.py")
    _assert(
        "revoke_superseded_grants_for_new_preview" in pipeline,
        "C4: dry-run path must revoke superseded APPROVED grants",
    )
    _assert(
        '"expected"' not in views.split("diff_hash_mismatch")[1][:400]
        or "exc.expected" in views,
        "client DiffHash 409 must not expose expected/actual fields",
    )
    # Stronger: Response payload after DiffHash must omit expected/actual keys.
    _assert(
        '"expected":' not in views and '"actual":' not in views,
        "views must not return expected/actual hash fields to clients",
    )
    _assert("WritebackDcsRunRequiredError" in views, "views must map dcs_run_required")
    print("views: DiffHash hygiene + dcs_run_required — OK")

    manago = _read("dataruns/writebacks/adapters/manago.py")
    shopify = _read("dataruns/writebacks/adapters/shopify.py")
    _assert('error_reason = "upstream_error"' in manago, "manago must use stable error_reason")
    _assert(
        'error_reason = "upstream_error"' in shopify,
        "shopify must use stable error_reason",
    )
    print("adapters: stable upstream_error — OK")

    from django.conf import settings

    stale = int(getattr(settings, "WRITEBACK_EXECUTING_STALE_MINUTES", 0) or 0)
    _assert(stale >= 1, "WRITEBACK_EXECUTING_STALE_MINUTES must be set (≥1)")
    print(f"WRITEBACK_EXECUTING_STALE_MINUTES={stale} — OK")

    from dataruns.writebacks.pii import mask_entity_key

    _assert(
        mask_entity_key("buyer@example.com") == "b***@example.com",
        "mask_entity_key email shape mismatch",
    )
    print("pii.mask_entity_key — OK")

    print("\nRunning test_writeback_wb07 …")
    proc = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "test",
            "dataruns.tests.test_writeback_wb07",
            "--verbosity=1",
            "--keepdb",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        print("\nWB-07 backend verification: FAIL (tests)")
        return proc.returncode

    print("\nWB-07 backend verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
