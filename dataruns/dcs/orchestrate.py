"""DCS score orchestration pipeline (PRD-DCS-01)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone as dj_timezone

from dataruns.connectors.base import resolve_company_from_data_run
from dataruns.dcs.assemble import assemble_dcs_score
from dataruns.dcs.constants import (
    DCS_SCORE_KIND,
    DCS_SCORING_MODEL_NAME,
    DCS_SCORING_MODEL_VERSION,
)
from dataruns.dcs.db_context import build_foundation_context_for_company
from dataruns.dcs.executors.foundation import evaluate_foundation_gates
from dataruns.dcs.executors.registry import get_executor
from dataruns.dcs.fresh_import import (
    DcsFreshImportError,
    refresh_connected_platforms_for_dcs,
)
from dataruns.dcs.issues import persist_dcs_issues
from dataruns.dcs.master import CheckDefinition, load_check_master
from dataruns.dcs.revenue_impact import rollup_revenue_impact
from dataruns.dcs.run_progress import (
    STAGE_DIMENSION_ORDER,
    finalize_stage_progress_on_failure,
    group_checks_by_dimension,
    persist_import_stage_running,
    persist_stage_progress,
)
from dataruns.dcs.snapshot import build_dcs_run_snapshot
from dataruns.dcs.types import CheckResult, DcsRun
from dataruns.models import DataRun, QaCheck, Run, RunScore, ScoringModel


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _fail_checks_for_email(
    check_results: list[CheckResult], *, limit: int = 5
) -> list[dict[str, Any]]:
    """Top FAIL rows with merchant-facing titles / fixes for email."""
    from dataruns.dcs.catalogue import (
        foundation_gate_meta,
        user_facing_check_name,
        user_facing_suggested_fix,
    )
    from dataruns.dcs.fix_ownership import is_klints_automated_fix

    rows: list[dict[str, Any]] = []
    for result in check_results:
        if result.status != "FAIL":
            continue
        meta = foundation_gate_meta(result.check_id)
        fix_owner = (result.fix_owner or meta.get("fix_owner") or "").strip()
        suggested = user_facing_suggested_fix(
            result.check_id,
            fallback=result.suggested_fix or meta.get("suggested_fix"),
        )
        rows.append(
            {
                "check_id": result.check_id,
                "check_name": user_facing_check_name(result.check_id)
                or meta.get("check_name")
                or result.check_id,
                "message": result.message,
                "suggested_fix": suggested,
                "fix_owner": fix_owner,
                "fix_in_klints": (
                    result.fix_in_klints
                    if result.fix_in_klints is not None
                    else is_klints_automated_fix(fix_owner)
                ),
                "reason_code": result.reason_code,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _notify_dcs_completed(
    *,
    company,
    data_run: DataRun,
    dcs: DcsRun,
    check_results: list[CheckResult],
) -> None:
    from tenants.emails import MailerAPIError, send_dcs_completed_email

    meta = data_run.metadata or {}
    actor_user_id = meta.get("actor_user_id")
    try:
        send_dcs_completed_email(
            company=company,
            run_state=dcs.run_state,
            headline_score=dcs.headline_score,
            data_run_id=data_run.id,
            fail_checks=_fail_checks_for_email(check_results),
            blocking_gates_failed=dcs.blocking_gates_failed,
            actor_user_id=str(actor_user_id) if actor_user_id else None,
        )
    except MailerAPIError:
        return


def _notify_dcs_failed(
    *,
    company,
    data_run: DataRun,
    error_message: str,
) -> None:
    from tenants.emails import MailerAPIError, send_dcs_failed_email

    meta = data_run.metadata or {}
    actor_user_id = meta.get("actor_user_id")
    try:
        send_dcs_failed_email(
            company=company,
            error_message=error_message,
            data_run_id=data_run.id,
            actor_user_id=str(actor_user_id) if actor_user_id else None,
        )
    except MailerAPIError:
        return


def _audit_dcs_completed(
    *,
    company,
    domain_run: Run,
    data_run: DataRun,
    dcs: DcsRun,
    run_diff: dict[str, Any] | None = None,
) -> None:
    from dataruns.audit import append_audit_event, resolve_performed_by_email
    from dataruns.dcs.run_diff import format_audit_score_summary
    from dataruns.models import AuditLog

    meta = data_run.metadata or {}
    actor_user_id = meta.get("actor_user_id")
    performed_by = resolve_performed_by_email(
        str(actor_user_id) if actor_user_id else None
    )
    tone = (
        AuditLog.Tone.RISK
        if dcs.run_state == "BLOCKED"
        else AuditLog.Tone.INFO
    )
    headline = dcs.headline_score
    stored_diff = run_diff
    if stored_diff is None and isinstance(meta.get("run_diff"), dict):
        stored_diff = meta["run_diff"]
    summary = format_audit_score_summary(
        headline_score=headline,
        run_state=dcs.run_state,
        run_diff=stored_diff,
    )
    audit_metadata: dict[str, Any] = {
        "data_run_id": data_run.id,
        "run_id": str(domain_run.id),
        "run_state": dcs.run_state,
        "headline_score": str(headline) if headline is not None else None,
    }
    if stored_diff is not None:
        audit_metadata["run_diff"] = stored_diff
    append_audit_event(
        company=company,
        action="dcs.score_completed",
        summary=summary,
        performed_by=performed_by,
        tone=tone,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        run=domain_run,
        metadata=audit_metadata,
    )


def _audit_dcs_failed(
    *,
    company,
    data_run: DataRun,
    domain_run: Run,
    error_message: str,
) -> None:
    from dataruns.audit import append_audit_event, resolve_performed_by_email
    from dataruns.models import AuditLog

    meta = data_run.metadata or {}
    actor_user_id = meta.get("actor_user_id")
    performed_by = resolve_performed_by_email(
        str(actor_user_id) if actor_user_id else None
    )
    append_audit_event(
        company=company,
        action="dcs.score_failed",
        summary=f"DCS score failed · {error_message}",
        performed_by=performed_by,
        tone=AuditLog.Tone.LOSS,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        run=domain_run,
        metadata={
            "data_run_id": data_run.id,
            "run_id": str(domain_run.id),
            "error": error_message,
        },
    )


def _evaluate_check_definition(
    definition: CheckDefinition,
    *,
    ctx,
    gate_results: dict[str, CheckResult],
    tenant_id: str,
    run_id: str,
    observed: str,
    erp_in_scope: bool,
) -> CheckResult:
    check_id = definition.check_id
    if check_id in gate_results:
        return gate_results[check_id]

    executor = get_executor(check_id)
    if executor is not None:
        result = executor(ctx)
        if result.numeric_weight is None:
            result.numeric_weight = definition.numeric_weight
        if not result.tenant_id:
            result.tenant_id = tenant_id
        if not result.run_id:
            result.run_id = run_id
        if not result.evaluated_at:
            result.evaluated_at = observed
        return result

    if (
        check_id.startswith("BR-") or check_id == "FD-03"
    ) and not erp_in_scope:
        return CheckResult(
            check_id=check_id,
            status="NOT_CONNECTED",
            confidence="HIGH",
            reason_code="ERP_OUT_OF_SCOPE",
            numeric_weight=definition.numeric_weight,
            tenant_id=tenant_id,
            run_id=run_id,
            evaluated_at=observed,
        )

    return CheckResult(
        check_id=check_id,
        status="UNKNOWN",
        confidence="LOW",
        reason_code="EXECUTOR_NOT_IMPLEMENTED",
        numeric_weight=definition.numeric_weight,
        tenant_id=tenant_id,
        run_id=run_id,
        evaluated_at=observed,
    )


def evaluate_check_results(
    *,
    ctx,
    tenant_id: str,
    run_id: str,
    evaluated_at: str | None = None,
) -> list[CheckResult]:
    """
    Evaluate all 42 MVP1 checks.

    Foundation gates + RULE checks + all 14 DRIFT checks (PRD-DCS-05).
    """
    master = load_check_master()
    observed = evaluated_at or _utcnow_iso()
    if evaluated_at and not ctx.evaluated_at:
        ctx.evaluated_at = evaluated_at
    gate_results = {
        result.check_id: result for result in evaluate_foundation_gates(ctx)
    }
    erp_in_scope = bool(getattr(ctx, "erp_in_scope", False))

    return [
        _evaluate_check_definition(
            definition,
            ctx=ctx,
            gate_results=gate_results,
            tenant_id=tenant_id,
            run_id=run_id,
            observed=observed,
            erp_in_scope=erp_in_scope,
        )
        for definition in master.checks
    ]


def evaluate_check_results_with_progress(
    *,
    data_run: DataRun,
    ctx,
    tenant_id: str,
    run_id: str,
    evaluated_at: str | None = None,
) -> list[CheckResult]:
    """Evaluate checks dimension-by-dimension, persisting stage_progress (PRD-FE-04)."""
    master = load_check_master()
    observed = evaluated_at or _utcnow_iso()
    if evaluated_at and not ctx.evaluated_at:
        ctx.evaluated_at = evaluated_at
    erp_in_scope = bool(getattr(ctx, "erp_in_scope", False))
    grouped = group_checks_by_dimension(master)
    gate_results = {
        result.check_id: result for result in evaluate_foundation_gates(ctx)
    }

    results: list[CheckResult] = []
    ordered_dimensions = [
        dimension_id
        for dimension_id in STAGE_DIMENSION_ORDER
        if grouped.get(dimension_id)
    ]

    for index, dimension_id in enumerate(ordered_dimensions):
        persist_stage_progress(
            data_run,
            check_results=results,
            current_dimension_id=dimension_id,
            run_status=DataRun.Status.RUNNING,
        )

        for definition in grouped.get(dimension_id, []):
            results.append(
                _evaluate_check_definition(
                    definition,
                    ctx=ctx,
                    gate_results=gate_results,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    observed=observed,
                    erp_in_scope=erp_in_scope,
                )
            )

        next_dimension_id = (
            ordered_dimensions[index + 1] if index + 1 < len(ordered_dimensions) else None
        )
        persist_stage_progress(
            data_run,
            check_results=results,
            current_dimension_id=next_dimension_id,
            run_status=DataRun.Status.RUNNING,
        )

    return results


def _ensure_scoring_model() -> ScoringModel:
    model, _ = ScoringModel.objects.get_or_create(
        name=DCS_SCORING_MODEL_NAME,
        version=DCS_SCORING_MODEL_VERSION,
        defaults={"config": {"source": "PRD-DCS-01"}},
    )
    return model


def _resolve_domain_run(*, data_run: DataRun, company) -> Run:
    meta = data_run.metadata or {}
    run_id = meta.get("run_id")
    if run_id:
        try:
            return Run.objects.get(pk=run_id)
        except (Run.DoesNotExist, ValueError, TypeError):
            pass

    run = Run.objects.create(
        company=company,
        run_type=Run.RunType.FULL,
        status=Run.Status.RUNNING,
        started_at=dj_timezone.now(),
    )
    data_run.metadata = {**meta, "run_id": str(run.id)}
    data_run.save(update_fields=["metadata", "updated_at"])
    return run


def persist_dcs_results(
    *,
    company,
    domain_run: Run,
    dcs: DcsRun,
    check_results: list[CheckResult],
    business_impact: dict[str, Any] | None = None,
) -> RunScore:
    """Persist assemble output + QaCheck + RunIssue/Impact (PRD-DCS-01 §5)."""
    from dataruns.dcs.fix_ownership import enrich_check_results_from_master

    enrich_check_results_from_master(check_results)

    scoring_model = _ensure_scoring_model()
    headline = dcs.headline_score
    score_value = (
        Decimal(str(headline)) if headline is not None else Decimal("0")
    )

    breakdown = {
        "schema_version": dcs.schema_version,
        "dcs_run": dcs.to_dict(),
        "check_results": [result.to_dict() for result in check_results],
        "scoring_model_version": dcs.scoring_model_version,
        "run_state": dcs.run_state,
        "blocking_gates_failed": dcs.blocking_gates_failed,
    }
    if business_impact is not None:
        breakdown["business_impact"] = business_impact

    run_score = RunScore.objects.create(
        run=domain_run,
        scoring_model=scoring_model,
        entity_type="company",
        entity_id=str(company.id),
        score=score_value,
        breakdown=breakdown,
    )

    QaCheck.objects.bulk_create(
        [
            QaCheck(
                run=domain_run,
                check_type=result.check_id,
                result=result.status,
                details=result.to_dict(),
            )
            for result in check_results
        ]
    )
    persist_dcs_issues(
        company=company,
        domain_run=domain_run,
        check_results=check_results,
    )
    return run_score


def run_dcs_pipeline(data_run: DataRun) -> dict[str, Any]:
    """
    Full worker pipeline for one DCS DataRun (PRD-DCS-01 §3 worker steps).

    Idempotent: if DataRun already succeeded, return stored summary.
    Always re-imports connected platforms, freezes run_snapshot, then scores.
    """
    meta = data_run.metadata or {}
    if meta.get("kind") != DCS_SCORE_KIND:
        return {"ok": False, "error": "Not a DCS score DataRun."}

    if data_run.status == DataRun.Status.SUCCEEDED:
        return {
            "ok": True,
            "data_run_id": data_run.id,
            "status": data_run.status,
            "idempotent": True,
            "run_state": (meta.get("dcs_run") or {}).get("run_state"),
            "headline_score": (meta.get("dcs_run") or {}).get("headline_score"),
        }

    company = resolve_company_from_data_run(data_run)
    erp_in_scope = bool(meta.get("erp_in_scope", False))
    live_revalidate = bool(meta.get("live_revalidate", False))

    from tenants.manago_topology_service import ensure_manago_primary_owner

    actor_user_id = meta.get("actor_user_id")
    ensure_manago_primary_owner(
        company,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        allow_multi_owner_inference=True,
    )

    data_run.status = DataRun.Status.RUNNING
    data_run.started_at = data_run.started_at or dj_timezone.now()
    data_run.save(update_fields=["status", "started_at", "updated_at"])

    domain_run = _resolve_domain_run(data_run=data_run, company=company)
    tenant_id = str(company.tenant_id)
    run_id = str(domain_run.id)
    started_iso = _utcnow_iso()
    check_results: list[CheckResult] = []

    try:
        persist_import_stage_running(data_run)
        refresh = refresh_connected_platforms_for_dcs(
            company=company,
            dcs_data_run=data_run,
        )
        source_runs = refresh["source_runs"]
        fresh_imports = refresh["fresh_imports"]
        window_days = refresh["window_days"]

        snapshot = build_dcs_run_snapshot(
            company=company,
            source_runs=source_runs,
            fresh_imports=fresh_imports,
            window_days=window_days,
        )
        data_run.run_snapshot = snapshot
        data_run.metadata = {
            **(data_run.metadata or {}),
            "source_runs": {
                "manago_ai": (
                    str(source_runs["manago_ai"])
                    if source_runs.get("manago_ai") is not None
                    else None
                ),
                "shopify": (
                    str(source_runs["shopify"])
                    if source_runs.get("shopify") is not None
                    else None
                ),
            },
            "fresh_imports": fresh_imports,
            "run_snapshot_as_of": snapshot.get("as_of"),
        }
        data_run.save(
            update_fields=["run_snapshot", "metadata", "updated_at"]
        )

        ctx, resolved_sources = build_foundation_context_for_company(
            company=company,
            tenant_id=tenant_id,
            run_id=run_id,
            erp_in_scope=erp_in_scope,
            source_run_ids=source_runs,
            live_revalidate=live_revalidate,
        )
        # Excel Phase 0 artifact: account map on the frozen DCS snapshot.
        topology = ctx.extra.get("manago_topology")
        history_depth = ctx.extra.get("history_depth")
        snapshot_dirty = False
        if isinstance(topology, dict):
            gate_inputs = data_run.run_snapshot.setdefault("gate_inputs", {})
            if isinstance(gate_inputs, dict):
                gate_inputs["topology"] = topology
            data_run.run_snapshot["account_map"] = topology
            snapshot_dirty = True
        if isinstance(history_depth, dict):
            gate_inputs = data_run.run_snapshot.setdefault("gate_inputs", {})
            if isinstance(gate_inputs, dict):
                gate_inputs["history_depth"] = history_depth
                # Attach measured rate budgets from gate context when present.
                rate_budgets = {}
                if ctx.manago and ctx.manago.rate_budget:
                    rate_budgets["manago_ai"] = ctx.manago.rate_budget
                if ctx.shopify and ctx.shopify.rate_budget:
                    rate_budgets["shopify"] = ctx.shopify.rate_budget
                if rate_budgets:
                    gate_inputs["rate_budgets"] = rate_budgets
            data_run.run_snapshot["history_depth"] = history_depth
            snapshot_dirty = True
        if snapshot_dirty:
            data_run.save(update_fields=["run_snapshot", "updated_at"])

        # CI-* executors read the frozen snapshot only (PRD-DCS-03 / DCS-04).
        ctx.extra["scoring_snapshot"] = data_run.run_snapshot

        check_results = evaluate_check_results_with_progress(
            data_run=data_run,
            ctx=ctx,
            tenant_id=tenant_id,
            run_id=run_id,
            evaluated_at=started_iso,
        )
        # Foundation + RULE + all 14 DRIFT registered (PRD-DCS-05 complete).
        master = load_check_master()
        dcs = assemble_dcs_score(
            check_results,
            master=master,
            erp_in_scope=erp_in_scope,
            sweep_complete=True,
            tenant_id=tenant_id,
            run_id=run_id,
            started_at=started_iso,
            completed_at=_utcnow_iso(),
            scoring_model_version=DCS_SCORING_MODEL_VERSION,
        )
        business_impact = rollup_revenue_impact(check_results)

        with transaction.atomic():
            run_score = persist_dcs_results(
                company=company,
                domain_run=domain_run,
                dcs=dcs,
                check_results=check_results,
                business_impact=business_impact,
            )
            domain_run.status = Run.Status.COMPLETED
            domain_run.completed_at = dj_timezone.now()
            domain_run.save(
                update_fields=["status", "completed_at"]
            )

            # Keep run_snapshot + metadata business_impact in the same txn so a
            # rollback cannot leave snapshot money without succeeded metadata.
            if isinstance(data_run.run_snapshot, dict):
                data_run.run_snapshot = {
                    **data_run.run_snapshot,
                    "business_impact": business_impact,
                }
            data_run.status = DataRun.Status.SUCCEEDED
            data_run.finished_at = dj_timezone.now()
            data_run.metadata = {
                **(data_run.metadata or {}),
                "source_runs": {
                    "manago_ai": (
                        str(resolved_sources["manago_ai"])
                        if resolved_sources.get("manago_ai") is not None
                        else None
                    ),
                    "shopify": (
                        str(resolved_sources["shopify"])
                        if resolved_sources.get("shopify") is not None
                        else None
                    ),
                },
                "run_score_id": str(run_score.id),
                "dcs_run": dcs.to_dict(),
                "check_results": [result.to_dict() for result in check_results],
                "check_count": len(check_results),
                "business_impact": business_impact,
                "run_snapshot_as_of": (data_run.run_snapshot or {}).get("as_of"),
            }
            data_run.save(
                update_fields=[
                    "status",
                    "finished_at",
                    "metadata",
                    "run_snapshot",
                    "updated_at",
                ]
            )

        persist_stage_progress(
            data_run,
            check_results=check_results,
            current_dimension_id=None,
            run_status=DataRun.Status.SUCCEEDED,
        )

        from dataruns.dcs.run_diff import persist_consecutive_run_diff

        data_run.refresh_from_db()
        run_diff = persist_consecutive_run_diff(company=company, data_run=data_run)

        _notify_dcs_completed(
            company=company,
            data_run=data_run,
            dcs=dcs,
            check_results=check_results,
        )
        _audit_dcs_completed(
            company=company,
            domain_run=domain_run,
            data_run=data_run,
            dcs=dcs,
            run_diff=run_diff,
        )

        # PRD-AF-01: Architecture Assessment follows every DCS SUCCEEDED
        # asynchronously — never blocks the DCS response path.
        from dataruns.architecture.enqueue import maybe_enqueue_architecture_after_dcs

        maybe_enqueue_architecture_after_dcs(
            company=company,
            source_dcs_data_run=data_run,
        )

        return {
            "ok": True,
            "data_run_id": data_run.id,
            "run_id": str(domain_run.id),
            "run_score_id": str(run_score.id),
            "run_state": dcs.run_state,
            "headline_score": dcs.headline_score,
            "blocking_gates_failed": dcs.blocking_gates_failed,
            "check_count": len(check_results),
            "run_snapshot_as_of": (data_run.run_snapshot or {}).get("as_of"),
        }
    except Exception as exc:  # noqa: BLE001 — mark failed for worker visibility
        finalize_stage_progress_on_failure(
            data_run,
            check_results=check_results,
        )
        data_run.status = DataRun.Status.FAILED
        data_run.finished_at = dj_timezone.now()
        error_meta: dict[str, Any] = {
            **(data_run.metadata or {}),
            "error": str(exc),
        }
        if isinstance(exc, DcsFreshImportError):
            error_meta["fresh_import_failed_platform"] = exc.platform
        data_run.metadata = error_meta
        data_run.save(
            update_fields=["status", "finished_at", "metadata", "updated_at"]
        )
        if domain_run.status != Run.Status.COMPLETED:
            domain_run.status = Run.Status.COMPLETED
            domain_run.completed_at = dj_timezone.now()
            domain_run.save(update_fields=["status", "completed_at"])
        _notify_dcs_failed(
            company=company,
            data_run=data_run,
            error_message=str(exc),
        )
        _audit_dcs_failed(
            company=company,
            data_run=data_run,
            domain_run=domain_run,
            error_message=str(exc),
        )
        failure_response: dict[str, Any] = {
            "ok": False,
            "data_run_id": data_run.id,
            "error": str(exc),
        }
        if isinstance(exc, DcsFreshImportError):
            failure_response["fresh_import_failed_platform"] = exc.platform
        return failure_response
