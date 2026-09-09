"""M2-OPS-01 local Fix smoke — Klints Dev Co (no staging SSH).

Runs: LE-04 blocked · preview allowlisted FAIL · execute · re-execute 409.
Does not print emails/PII. Optional rollback via --rollback.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

import django

django.setup()

from tenants.models import Company, Connector, User
from dataruns.models import DataRun, WritebackAllowedCheck
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.writebacks.exceptions import (
    WritebackAlreadyExecutedForRunError,
    WritebackDcsRunRequiredError,
)
from dataruns.writebacks.registry import MappingDisabled, get_check_mapping
from dataruns.writebacks.run_gate import find_blocking_execute_job, resolve_writeback_gate
from dataruns.writebacks.service import writeback_run, writeback_rollback_job
from dataruns.tests.writeback_helpers import issue_approved_writeback_token


def _ok(label: str) -> None:
    print(f"  [ok] {label}")


def _fail(label: str, detail: str = "") -> None:
    print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)


def _pick_check(company: Company) -> str:
    dcs = (
        DataRun.objects.filter(
            tenant=company.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
        )
        .order_by("-created_at")
        .first()
    )
    if dcs is None:
        _fail("terminal DCS", "no succeeded score run")
    meta = dcs.metadata if isinstance(dcs.metadata, dict) else {}
    checks = meta.get("check_results") or []
    prefer = ["CC-03", "CI-01", "WB-SHOP-01"]
    fails = {
        str(row.get("check_id") or "").upper()
        for row in checks
        if isinstance(row, dict) and str(row.get("status") or "").upper() == "FAIL"
    }
    open_checks: list[str] = []
    locked_checks: list[str] = []
    for check_id in prefer:
        if check_id not in fails:
            continue
        gate = resolve_writeback_gate(company=company, check_id=check_id)
        if gate == "locked":
            locked_checks.append(check_id)
        else:
            open_checks.append(check_id)
    if open_checks:
        check_id = open_checks[0]
        print(f"  using check {check_id} (FAIL on DCS id={dcs.id}, gate open)")
        return check_id
    if locked_checks:
        # Prefer rolling back first locked allowlisted FAIL so smoke can run.
        check_id = locked_checks[0]
        print(
            f"  check {check_id} already locked on DCS id={dcs.id} — "
            "will rollback then re-execute for smoke"
        )
        return check_id
    _fail("allowlisted FAIL", f"none of {prefer} FAIL on latest DCS")


def _ensure_gate_open(*, company: Company, check_id: str, actor: User) -> None:
    gate = resolve_writeback_gate(company=company, check_id=check_id)
    if gate != "locked":
        return
    from dataruns.writebacks.run_gate import writeback_status_payload

    status = writeback_status_payload(company=company, check_id=check_id)
    latest = status.get("latest_execute") or {}
    job_id = latest.get("job_id")
    if not job_id:
        _fail("unlock gate", "locked but no latest_execute.job_id")
    writeback_rollback_job(company=company, job_id=str(job_id), actor=actor)
    gate2 = resolve_writeback_gate(company=company, check_id=check_id)
    if gate2 == "locked":
        _fail("unlock gate", f"still locked after rollback ({gate2})")
    _ok(f"rolled back prior job to open gate ({gate2})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="After 409, rollback the execute job and confirm gate opens",
    )
    args = parser.parse_args()

    print("=== M2-OPS-01 local Fix smoke ===\n")

    company = Company.objects.filter(name="Klints Dev Co").first()
    if company is None:
        _fail("company", "Klints Dev Co not found")
    _ok(f"company={company.name}")

    if not company.writeback_execute_enabled:
        _fail("Allow writebacks", "writeback_execute_enabled is False")
    _ok("Allow writebacks ON")

    conns = {
        name: status
        for name, status in Connector.objects.filter(company=company).values_list(
            "name", "status"
        )
    }
    for need in ("manago_ai", "shopify"):
        if conns.get(need) not in {"connected", "degraded"}:
            _fail("connectors", f"{need} status={conns.get(need)!r}")
    _ok(f"connectors {conns}")

    allowed = set(
        WritebackAllowedCheck.objects.filter(enabled=True).values_list(
            "check_id", flat=True
        )
    )
    for need in ("CI-01", "CC-03", "WB-SHOP-01"):
        if need not in allowed:
            _fail("allowlist", f"{need} missing/disabled")
    _ok("allowlist CI-01 · CC-03 · WB-SHOP-01")

    # LE-04 blocked
    try:
        get_check_mapping("LE-04")
        _fail("LE-04 mapping", "expected MappingDisabled")
    except MappingDisabled:
        _ok("LE-04 mapping disabled")
    if "LE-04" in allowed:
        _fail("LE-04 allowlist", "should not be allowlisted")
    _ok("LE-04 not on allowlist")

    admin = (
        User.objects.filter(
            tenant=company.tenant, role=User.Role.ADMIN, is_active=True
        )
        .order_by("created_at")
        .first()
    )
    if admin is None:
        _fail("admin user", "none active")
    _ok("admin actor present")

    check_id = _pick_check(company)
    _ensure_gate_open(company=company, check_id=check_id, actor=admin)

    preview = writeback_run(
        company=company,
        check_id=check_id,
        mode="dry_run",
        actor=admin,
    )
    ready = int(preview.summary.ready or 0)
    if ready < 1:
        _fail("preview ready", f"ready={ready} blocked={preview.blocked_reason!r}")
    if not preview.job_id or not preview.diff_hash:
        _fail("preview job/diff_hash", "missing")
    entity = (preview.intents[0].entity_key if preview.intents else "") or ""
    # Entity may still be full in DB intent; API serialize masks — smoke uses service.
    _ok(f"preview ready={ready} job_id set")

    token = issue_approved_writeback_token(
        company=company,
        job_id=str(preview.job_id),
        requester=admin,
        approver=admin,
    )

    try:
        result = writeback_run(
            company=company,
            check_id=check_id,
            mode="execute",
            expected_diff_hash=preview.diff_hash,
            approval_id=str(token.id),
            actor=admin,
        )
    except WritebackDcsRunRequiredError:
        _fail("execute", "dcs_run_required")
    except Exception as exc:  # noqa: BLE001
        _fail("execute", f"{type(exc).__name__}: {exc}")

    executed = int(result.summary.executed or 0)
    if executed < 1 and result.blocked_reason:
        _fail("execute written", f"blocked={result.blocked_reason}")
    if executed < 1:
        _fail("execute written", f"executed={executed} status errors possible")
    _ok(f"execute Written executed={executed} job={result.job_id}")

    gate = resolve_writeback_gate(company=company, check_id=check_id)
    if gate != "locked":
        _fail("status gate", f"expected locked got {gate}")
    _ok("gate=locked after execute")

    # Fresh preview+token for second Approve attempt (simulates re-Approve race/gate)
    preview2 = writeback_run(
        company=company,
        check_id=check_id,
        mode="dry_run",
        actor=admin,
    )
    token2 = issue_approved_writeback_token(
        company=company,
        job_id=str(preview2.job_id),
        requester=admin,
        approver=admin,
    )
    try:
        writeback_run(
            company=company,
            check_id=check_id,
            mode="execute",
            expected_diff_hash=preview2.diff_hash,
            approval_id=str(token2.id),
            actor=admin,
        )
        _fail("re-execute 409", "second execute succeeded (should block)")
    except WritebackAlreadyExecutedForRunError:
        _ok("re-execute -> WritebackAlreadyExecutedForRunError (409 path)")
    except Exception as exc:  # noqa: BLE001
        _fail("re-execute 409", f"{type(exc).__name__}: {exc}")

    if args.rollback:
        job_id = result.job_id
        if not job_id:
            _fail("rollback", "missing execute job_id")
        writeback_rollback_job(company=company, job_id=str(job_id), actor=admin)
        gate2 = resolve_writeback_gate(company=company, check_id=check_id)
        if gate2 not in {"open", "rolled_back"}:
            _fail("rollback gate", f"got {gate2}")
        blocking = find_blocking_execute_job(
            company=company,
            check_id=check_id,
            dcs_data_run_id=result.data_run_id,
        )
        if blocking is not None:
            _fail("rollback blocking", "still blocked")
        _ok(f"rollback done gate={gate2}")

    print("\nM2-OPS-01 local Fix smoke: PASS")
    print(f"check_used={check_id} rollback={'Y' if args.rollback else 'N'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
