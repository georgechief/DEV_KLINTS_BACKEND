"""Writeback pipeline orchestration (PRD-WB-01 §4)."""

from __future__ import annotations

from django.conf import settings

from dataruns.audit import append_audit_event
from dataruns.dcs.fix_ownership import is_klints_automated_fix
from dataruns.models import CheckMaster, WritebackJob
from dataruns.writebacks.adapters import get_adapter
from dataruns.writebacks.approvals.service import consume_approval_token
from dataruns.writebacks.capabilities import capability_batch_max
from dataruns.writebacks.exceptions import DiffHashMismatchError
from dataruns.writebacks.gates import execute_allowed, is_sandbox_company
from dataruns.writebacks.hashing import compute_diff_hash
from dataruns.writebacks.preflight import run_preflight
from dataruns.writebacks.registry import MappingDisabled, MappingNotFound, get_check_mapping
from dataruns.writebacks.transform import build_intents_from_mapping, collect_evidence_rows
from dataruns.writebacks.types import (
    ExecuteEligibility,
    WritebackResult,
    WritebackSummary,
    WriteIntent,
    WriteMode,
)
from tenants.models import Company, User


def run_writeback_pipeline(
    *,
    company: Company,
    check_id: str,
    mode: WriteMode = "dry_run",
    batch_size: int | None = None,
    max_rows: int | None = None,
    approval_id: str | None = None,
    actor: User | None = None,
    intents: list[WriteIntent] | None = None,
    expected_diff_hash: str | None = None,
) -> WritebackResult:
    normalized_check = (check_id or "").strip().upper()
    if not normalized_check:
        raise ValueError("check_id is required")

    try:
        mapping = get_check_mapping(normalized_check)
    except MappingNotFound as exc:
        raise ValueError(str(exc)) from exc
    except MappingDisabled as exc:
        raise ValueError(str(exc)) from exc

    effective_batch = batch_size or settings.WRITEBACK_DEFAULT_BATCH_SIZE
    effective_max = max_rows
    if mode in ("execute", "sandbox_execute") and effective_max is None:
        effective_max = settings.WRITEBACK_SANDBOX_MAX_ROWS

    blocked_reason = run_preflight(company=company, mapping=mapping)
    if blocked_reason:
        return _blocked_result(
            check_id=normalized_check,
            mode=mode,
            mapping=mapping,
            blocked_reason=blocked_reason,
        )

    if intents is None:
        evidence_rows = collect_evidence_rows(
            company=company,
            check_id=normalized_check,
            max_rows=effective_max,
        )
        intents = build_intents_from_mapping(
            company=company,
            mapping=mapping,
            evidence_rows=evidence_rows,
        )

    intents = _dry_run_intents(company=company, intents=intents)

    diff_hash = compute_diff_hash(intents)
    if expected_diff_hash and expected_diff_hash != diff_hash:
        raise DiffHashMismatchError(expected=expected_diff_hash, actual=diff_hash)

    summary = _summarize(intents)
    execute_eligible = ExecuteEligibility(
        sandbox=is_sandbox_company(company),
        production=bool(settings.WRITEBACKS_ENABLED),
    )

    master = CheckMaster.objects.filter(check_id=normalized_check).first()
    preview_only_owner = master is not None and not is_klints_automated_fix(master.fix_owner)

    if mode in ("execute", "sandbox_execute"):
        if mapping.get("approval_tier") == "individual" and summary.ready > 1:
            return WritebackResult(
                check_id=normalized_check,
                mode=mode,
                diff_hash=diff_hash,
                intents=intents,
                summary=summary,
                execute_eligible=execute_eligible,
                blocked_reason="individual_tier_single_intent_required",
                approval_tier=mapping.get("approval_tier"),
                irreversible=bool(mapping.get("irreversible")),
                operator_disclosure=mapping.get("operator_disclosure"),
            )

        allowed, deny_reason = execute_allowed(
            company=company,
            check_id=normalized_check,
            approval_id=approval_id,
            diff_hash=diff_hash,
        )
        if not allowed or preview_only_owner:
            reason = deny_reason or "fix_owner_not_klints_automated"
            _audit(
                company=company,
                actor=actor,
                action="writeback.execute_denied",
                summary=f"Writeback execute denied for {normalized_check}",
                metadata={"check_id": normalized_check, "reason": reason},
            )
            return WritebackResult(
                check_id=normalized_check,
                mode=mode,
                diff_hash=diff_hash,
                intents=intents,
                summary=summary,
                execute_eligible=execute_eligible,
                blocked_reason=reason,
                approval_tier=mapping.get("approval_tier"),
                irreversible=bool(mapping.get("irreversible")),
                operator_disclosure=mapping.get("operator_disclosure"),
            )

        intents, job_status = _execute_intents(
            company=company,
            check_id=normalized_check,
            intents=intents,
            batch_size=effective_batch,
            diff_hash=diff_hash,
            approval_id=approval_id,
        )
        summary = _summarize(intents)
        sandbox = is_sandbox_company(company)
        job_mode = "sandbox_execute" if sandbox else "execute"

        job = WritebackJob.objects.create(
            company=company,
            check_id=normalized_check,
            mode=job_mode,
            status=job_status,
            diff_hash=diff_hash,
            approval_tier=str(mapping.get("approval_tier") or ""),
            approval_id=_parse_uuid(approval_id),
            token_binds={
                "tenant_id": str(company.tenant_id),
                "object_id": normalized_check,
                "object_version": str(mapping.get("schema_version") or "1.0.0"),
                "diff_hash": diff_hash,
            },
            intents=_serialize_intents(intents),
            summary={
                "ready": summary.ready,
                "skipped": summary.skipped,
                "errors": summary.errors,
                "executed": summary.executed,
            },
            sandbox=sandbox,
            actor_user=actor,
            metadata={
                "batch_size": effective_batch,
                "rollback_window_minutes": settings.WRITEBACK_PARTIAL_ROLLBACK_MINUTES,
            },
        )

        _audit(
            company=company,
            actor=actor,
            action="writeback.executed",
            summary=f"Writeback executed for {normalized_check}",
            metadata={
                "check_id": normalized_check,
                "job_id": str(job.id),
                "diff_hash": diff_hash,
                "status": job_status,
                "executed": summary.executed,
                "errors": summary.errors,
                "sandbox": sandbox,
            },
        )

        if (
            approval_id
            and not sandbox
            and job_status in ("executed", "partial")
            and summary.executed > 0
        ):
            consume_approval_token(company=company, approval_id=approval_id)

        return WritebackResult(
            check_id=normalized_check,
            mode=job_mode,
            diff_hash=diff_hash,
            intents=intents,
            summary=summary,
            execute_eligible=execute_eligible,
            blocked_reason=None,
            job_id=str(job.id),
            approval_tier=mapping.get("approval_tier"),
            irreversible=bool(mapping.get("irreversible")),
            operator_disclosure=mapping.get("operator_disclosure"),
        )

    job = WritebackJob.objects.create(
        company=company,
        check_id=normalized_check,
        mode="dry_run",
        status="previewed",
        diff_hash=diff_hash,
        approval_tier=str(mapping.get("approval_tier") or ""),
        token_binds={
            "tenant_id": str(company.tenant_id),
            "object_id": normalized_check,
            "object_version": str(mapping.get("schema_version") or "1.0.0"),
            "diff_hash": diff_hash,
        },
        intents=_serialize_intents(intents),
        summary={
            "ready": summary.ready,
            "skipped": summary.skipped,
            "errors": summary.errors,
            "executed": summary.executed,
        },
        sandbox=is_sandbox_company(company),
        actor_user=actor,
        metadata={"batch_size": effective_batch},
    )

    _audit(
        company=company,
        actor=actor,
        action="writeback.previewed",
        summary=f"Writeback preview for {normalized_check}",
        metadata={
            "check_id": normalized_check,
            "job_id": str(job.id),
            "diff_hash": diff_hash,
            "ready": summary.ready,
            "errors": summary.errors,
            "sandbox": is_sandbox_company(company),
        },
    )

    return WritebackResult(
        check_id=normalized_check,
        mode=mode,
        diff_hash=diff_hash,
        intents=intents,
        summary=summary,
        execute_eligible=execute_eligible,
        blocked_reason=None,
        job_id=str(job.id),
        approval_tier=mapping.get("approval_tier"),
        irreversible=bool(mapping.get("irreversible")),
        operator_disclosure=mapping.get("operator_disclosure"),
    )


def _execute_intents(
    *,
    company: Company,
    check_id: str,
    intents: list[WriteIntent],
    batch_size: int,
    diff_hash: str,
    approval_id: str | None,
) -> tuple[list[WriteIntent], str]:
    ready = [intent for intent in intents if intent.status == "ready"]
    if not ready:
        return intents, "failed"

    batch_cap = min(batch_size, settings.WRITEBACK_MANAGO_BATCH_MAX)
    capability_cap = capability_batch_max(ready[0].capability_id)
    if capability_cap:
        batch_cap = min(batch_cap, capability_cap)

    executed_all: list[WriteIntent] = []
    partial = False

    for chunk_index, start in enumerate(range(0, len(ready), batch_cap)):
        chunk = ready[start : start + batch_cap]
        by_target: dict[str, list[WriteIntent]] = {}
        for intent in chunk:
            by_target.setdefault(intent.target_system, []).append(intent)

        chunk_failed = False
        for target, group in by_target.items():
            adapter = get_adapter(target)
            if adapter is None:
                for intent in group:
                    intent.status = "error"
                    intent.error_reason = "adapter_not_implemented"
                chunk_failed = True
                executed_all.extend(group)
                continue

            idempotency_key = f"{company.id}:{check_id}:{diff_hash}:{chunk_index}"
            results = adapter.execute(
                company,
                group,
                approval_id=approval_id,
                idempotency_key=idempotency_key,
            )
            executed_all.extend(results)
            if any(row.status == "error" for row in results):
                chunk_failed = True

        if chunk_failed:
            partial = True
            break

    # Merge executed intents back into full list preserving errors/skipped.
    executed_by_key = {
        (row.operation, row.entity_key, row.op_kind): row for row in executed_all
    }
    merged: list[WriteIntent] = []
    for intent in intents:
        key = (intent.operation, intent.entity_key, intent.op_kind)
        merged.append(executed_by_key.get(key, intent))

    if partial:
        return merged, "partial"
    if any(intent.status == "error" for intent in merged):
        return merged, "partial"
    return merged, "executed"


def deserialize_intents(rows: list[dict]) -> list[WriteIntent]:
    intents: list[WriteIntent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        intents.append(
            WriteIntent(
                check_id=str(row.get("check_id") or ""),
                op_kind=str(row.get("op_kind") or ""),
                operation=str(row.get("operation") or ""),
                target_system=str(row.get("target_system") or ""),
                entity_type=str(row.get("entity_type") or ""),
                entity_key=str(row.get("entity_key") or ""),
                namespace=str(row.get("namespace") or ""),
                template_id=row.get("template_id"),
                payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
                before=row.get("before") if isinstance(row.get("before"), dict) else {},
                after=row.get("after") if isinstance(row.get("after"), dict) else {},
                rollback_snapshot=(
                    row.get("rollback_snapshot")
                    if isinstance(row.get("rollback_snapshot"), dict)
                    else {}
                ),
                source_evidence_ref=str(row.get("source_evidence_ref") or ""),
                status=row.get("status") or "ready",
                error_reason=row.get("error_reason"),
                capability_id=row.get("capability_id"),
                rollback_strategy=row.get("rollback_strategy"),
                execute_result=(
                    row.get("execute_result")
                    if isinstance(row.get("execute_result"), dict)
                    else None
                ),
            )
        )
    return intents


def _dry_run_intents(*, company: Company, intents: list[WriteIntent]) -> list[WriteIntent]:
    updated: list[WriteIntent] = []
    for intent in intents:
        if intent.status == "error":
            updated.append(intent)
            continue
        adapter = get_adapter(intent.target_system)
        if adapter is None:
            intent.status = "error"
            intent.error_reason = "adapter_not_implemented"
            updated.append(intent)
            continue
        updated.extend(adapter.dry_run(company, [intent]))
    return updated


def _summarize(intents: list[WriteIntent]) -> WritebackSummary:
    summary = WritebackSummary()
    for intent in intents:
        if intent.status == "executed":
            summary.executed += 1
        elif intent.status == "ready":
            summary.ready += 1
        elif intent.status == "error":
            summary.errors += 1
        else:
            summary.skipped += 1
    return summary


def _blocked_result(
    *,
    check_id: str,
    mode: WriteMode,
    mapping: dict,
    blocked_reason: str,
) -> WritebackResult:
    return WritebackResult(
        check_id=check_id,
        mode=mode,
        diff_hash=compute_diff_hash([]),
        intents=[],
        summary=WritebackSummary(),
        execute_eligible=ExecuteEligibility(),
        blocked_reason=blocked_reason,
        approval_tier=mapping.get("approval_tier"),
        irreversible=bool(mapping.get("irreversible")),
        operator_disclosure=mapping.get("operator_disclosure"),
    )


def _serialize_intents(intents: list[WriteIntent]) -> list[dict]:
    rows: list[dict] = []
    for intent in intents:
        rows.append(
            {
                "check_id": intent.check_id,
                "op_kind": intent.op_kind,
                "operation": intent.operation,
                "target_system": intent.target_system,
                "entity_type": intent.entity_type,
                "entity_key": intent.entity_key,
                "namespace": intent.namespace,
                "payload": intent.payload,
                "before": intent.before,
                "after": intent.after,
                "rollback_snapshot": intent.rollback_snapshot,
                "status": intent.status,
                "error_reason": intent.error_reason,
                "capability_id": intent.capability_id,
                "rollback_strategy": intent.rollback_strategy,
                "execute_result": intent.execute_result,
            }
        )
    return rows


def _audit(
    *,
    company: Company,
    actor: User | None,
    action: str,
    summary: str,
    metadata: dict,
) -> None:
    append_audit_event(
        company=company,
        action=action,
        summary=summary,
        performed_by=actor.email if actor else "system",
        actor_user_id=str(actor.id) if actor else None,
        metadata=metadata,
    )


def _parse_uuid(value: str | None):
    if not value:
        return None
    import uuid

    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
