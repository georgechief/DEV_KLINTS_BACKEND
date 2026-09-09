"""DCS app-gate status resolver (PRD-FE-03 §4–§5)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from dataruns.dcs.enqueue import (
    DCS_SCORE_DATA_RUN_NAME,
    DCS_SCORE_KIND,
    ELIGIBLE_CONNECTOR_NAMES,
    fail_stale_active_dcs_runs,
)
from dataruns.dcs.gates import (
    is_effectively_blocked,
    load_optional_check_ids,
    partition_gate_failures,
)
from dataruns.dcs.run_progress import build_run_progress
from dataruns.dcs.worklist import (
    STATUS_ISSUES_CAP,
    build_enriched_issues,
    build_status_enrichment,
)
from dataruns.models import DataRun
from tenants.auth.services import get_user_company
from tenants.models import Company, User

LOCKED_ALLOWED_ROUTES = [
    "/dashboard",
    "/integrations",
    "/settings",
    "/activity",
]
UNLOCKED_ALLOWED_ROUTES = ["*"]

ACTIVE_STATUSES = (DataRun.Status.PENDING, DataRun.Status.RUNNING)
TERMINAL_STATUSES = (DataRun.Status.SUCCEEDED, DataRun.Status.FAILED)

# Scrub credential-like values before returning error text to the client.
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b("
    r"access_token|refresh_token|api_key|api_secret|password|authorization"
    r")\s*[:=]\s*([^\s,;]+)"
)
_SHOPIFY_TOKEN_RE = re.compile(r"\b(shpat_|shprt_|shpss_)[A-Za-z0-9]+")


def _redact_secrets(text: str) -> str:
    scrubbed = _SECRET_VALUE_RE.sub(r"\1=****", text)
    return _SHOPIFY_TOKEN_RE.sub(r"\1****", scrubbed)

# PRD-FE-03 §5.6 default lock messages (single source of truth for API `message`).
LOCK_MESSAGES = {
    "no_run": (
        "Data Consistency Score is not calculated yet. Wait for the daily job or "
        "trigger a score run after connectors are healthy."
    ),
    "failed": (
        "The latest DCS run failed. Review the issue below, fix connectors, then "
        "retry scoring."
    ),
    "blocked": (
        "Score is not calculated — required foundation gates failed. Fix the issues "
        "under Connected stack. (Optional checks like ERP/FD-03 are not enough to "
        "show this.)"
    ),
    "incomplete_no_score": (
        "Score is not calculated yet (run incomplete / missing scored checks). "
        "Review any open issues below."
    ),
    "running_no_score": (
        "Scoring in progress. Score will appear here when ready."
    ),
}


def _company_dcs_runs(*, company: Company):
    return DataRun.objects.filter(
        tenant=company.tenant,
        name=DCS_SCORE_DATA_RUN_NAME,
        metadata__kind=DCS_SCORE_KIND,
        metadata__company_id=str(company.id),
    ).order_by("-created_at")


def _company_dcs_runs_in_window(
    *,
    company: Company,
    since,
    until,
):
    """
    Succeeded DCS score runs for a company within ``[since, until]``.

    Uses ``finished_at`` when set, otherwise ``created_at``. Results are ordered
    chronologically (oldest first) for history charts.
    """
    from django.db.models import DateTimeField
    from django.db.models.functions import Coalesce

    at = Coalesce("finished_at", "created_at", output_field=DateTimeField())
    return (
        _company_dcs_runs(company=company)
        .filter(status=DataRun.Status.SUCCEEDED)
        .annotate(at=at)
        .exclude(at__isnull=True)
        .filter(at__gte=since, at__lte=until)
        .order_by("at")
        .only("id", "metadata", "finished_at", "created_at", "status")
    )


def _extract_dcs_payload(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    dcs_run = metadata.get("dcs_run")
    if not isinstance(dcs_run, dict):
        dcs_run = {}
    check_results = metadata.get("check_results")
    if not isinstance(check_results, list):
        check_results = dcs_run.get("check_results")
    if not isinstance(check_results, list):
        check_results = []

    run_state = dcs_run.get("run_state") or dcs_run.get("score_state")
    headline_score = dcs_run.get("headline_score")
    if headline_score is None:
        headline_score = metadata.get("headline_score")

    domain_run_id = dcs_run.get("run_id") or metadata.get("run_id")
    blocking_gates_failed = dcs_run.get("blocking_gates_failed")
    if blocking_gates_failed is None:
        blocking_gates_failed = metadata.get("blocking_gates_failed", 0)

    return {
        "dcs_run": dcs_run,
        "check_results": check_results,
        "run_state": run_state,
        "headline_score": headline_score,
        "domain_run_id": domain_run_id,
        "blocking_gates_failed": blocking_gates_failed,
    }


def _coerce_headline_score(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _coerce_fresh_import_data_run_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _serialize_fresh_imports_for_status(
    metadata: dict[str, Any] | None,
) -> dict[str, dict[str, Any]] | None:
    """
    PRD-DCS-10 Slice B — platform summary for GET /dcs/status/ run payloads.

    Exposes ``data_run_id`` and ``window_end`` per platform; omits counts and
    other internal import fields.
    """
    metadata = metadata or {}
    raw = metadata.get("fresh_imports")
    if not isinstance(raw, dict):
        return None

    summary: dict[str, dict[str, Any]] = {}
    for platform in ELIGIBLE_CONNECTOR_NAMES:
        block = raw.get(platform)
        if not isinstance(block, dict):
            continue
        entry: dict[str, Any] = {}
        data_run_id = _coerce_fresh_import_data_run_id(block.get("data_run_id"))
        if data_run_id is not None:
            entry["data_run_id"] = data_run_id
        window_end = block.get("window_end")
        if isinstance(window_end, str) and window_end.strip():
            entry["window_end"] = window_end.strip()
        if entry:
            summary[platform] = entry
    return summary or None


def _serialize_run_summary(
    data_run: DataRun | None,
    *,
    optional_check_ids: frozenset[str],
) -> dict[str, Any] | None:
    if data_run is None:
        return None

    metadata = data_run.metadata or {}
    payload = _extract_dcs_payload(metadata)
    check_results = payload["check_results"]
    required_fail_count = len(
        partition_gate_failures(
            check_results,
            optional_check_ids=optional_check_ids,
        )[0]
    )

    result = {
        "data_run_id": data_run.id,
        "domain_run_id": payload["domain_run_id"],
        "status": data_run.status,
        "run_state": payload["run_state"],
        "headline_score": _coerce_headline_score(payload["headline_score"]),
        "blocking_gates_failed": required_fail_count,
        "error": (
            _redact_secrets(str(metadata.get("error")))
            if metadata.get("error") is not None
            else None
        ),
        "triggered_by": metadata.get("triggered_by"),
        "started_at": data_run.started_at,
        "created_at": data_run.created_at,
        "finished_at": data_run.finished_at,
    }
    run_diff = metadata.get("run_diff")
    if isinstance(run_diff, dict):
        result["run_diff"] = run_diff
    fresh_imports = _serialize_fresh_imports_for_status(metadata)
    if fresh_imports is not None:
        result["fresh_imports"] = fresh_imports
    failed_platform = metadata.get("fresh_import_failed_platform")
    if isinstance(failed_platform, str):
        failed_platform = failed_platform.strip()
        if failed_platform in ELIGIBLE_CONNECTOR_NAMES:
            result["fresh_import_failed_platform"] = failed_platform
    return result


def _build_issues(
    *,
    latest_run: DataRun | None,
    lock_reason: str | None,
    optional_check_ids: frozenset[str],
) -> list[dict[str, Any]]:
    """PRD-FE-06: FAIL+WARN enriched issues via worklist builder (cap 30)."""
    del lock_reason  # retained for call-site compatibility
    return build_enriched_issues(
        data_run=latest_run,
        optional_check_ids=optional_check_ids,
        cap=STATUS_ISSUES_CAP,
    )


def _best_headline_score(runs) -> float | None:
    best: float | None = None
    for data_run in runs:
        if data_run.status != DataRun.Status.SUCCEEDED:
            continue
        payload = _extract_dcs_payload(data_run.metadata)
        headline = _coerce_headline_score(payload["headline_score"])
        if headline is None:
            continue
        if best is None or headline > best:
            best = headline
    return best


def _latest_succeeded_headline_score(runs) -> float | None:
    """Most recent succeeded run's headline (not the historical max)."""
    for data_run in runs:
        if data_run.status != DataRun.Status.SUCCEEDED:
            continue
        payload = _extract_dcs_payload(data_run.metadata)
        headline = _coerce_headline_score(payload["headline_score"])
        if headline is not None:
            return headline
    return None


def _has_ever_scored(runs) -> bool:
    return _latest_succeeded_headline_score(runs) is not None


def resolve_dcs_app_status(*, company: Company) -> dict[str, Any]:
    """Compute DCS app-gate payload for the shell (PRD-FE-03 §5.2 / FE-06 §4.4)."""
    # Unlock soft-lock loops when workers never picked up a queued run.
    fail_stale_active_dcs_runs(company=company)

    optional_check_ids = load_optional_check_ids()

    runs = list(_company_dcs_runs(company=company))
    active_run = next(
        (run for run in runs if run.status in ACTIVE_STATUSES),
        None,
    )
    latest_any = runs[0] if runs else None
    latest_terminal = next(
        (run for run in runs if run.status in TERMINAL_STATUSES),
        None,
    )
    scheduled = active_run is not None
    has_ever_scored = _has_ever_scored(runs)
    best_headline_score = _best_headline_score(runs)
    last_succeeded_headline = _latest_succeeded_headline_score(runs)

    state_run = latest_any
    if state_run is not None and state_run.status in ACTIVE_STATUSES:
        state_run = latest_terminal

    latest_headline = None
    latest_payload: dict[str, Any] = {}
    if state_run is not None and state_run.status == DataRun.Status.SUCCEEDED:
        latest_payload = _extract_dcs_payload(state_run.metadata)
        latest_headline = _coerce_headline_score(latest_payload["headline_score"])

    usable_score = has_ever_scored or latest_headline is not None

    app_access = "hard_locked"
    lock_reason: str | None = "no_run"
    message = LOCK_MESSAGES["no_run"]

    if usable_score:
        app_access = "unlocked"
        lock_reason = None
        message = None
    elif scheduled:
        app_access = "soft_locked_running"
        lock_reason = "running_no_score"
        message = LOCK_MESSAGES["running_no_score"]
    elif state_run is None:
        app_access = "hard_locked"
        lock_reason = "no_run"
        message = LOCK_MESSAGES["no_run"]
    elif state_run.status == DataRun.Status.FAILED:
        app_access = "hard_locked"
        lock_reason = "failed"
        error_text = (state_run.metadata or {}).get("error")
        message = LOCK_MESSAGES["failed"]
        if isinstance(error_text, str) and error_text.strip():
            snippet = _redact_secrets(error_text.strip())
            if len(snippet) > 240:
                snippet = f"{snippet[:237]}..."
            message = f"{message} {snippet}"
    else:
        check_results = latest_payload.get("check_results", [])
        if not check_results and state_run is not None:
            latest_payload = _extract_dcs_payload(state_run.metadata)
            check_results = latest_payload.get("check_results", [])

        effectively_blocked = is_effectively_blocked(
            run_state=latest_payload.get("run_state"),
            headline_score=latest_headline,
            check_results=check_results,
            optional_check_ids=optional_check_ids,
        )
        if effectively_blocked:
            app_access = "hard_locked"
            lock_reason = "blocked"
            message = LOCK_MESSAGES["blocked"]
        elif (
            state_run.status == DataRun.Status.SUCCEEDED
            and latest_payload.get("run_state") == "INCOMPLETE"
            and latest_headline is None
        ):
            app_access = "hard_locked"
            lock_reason = "incomplete_no_score"
            message = LOCK_MESSAGES["incomplete_no_score"]
        elif state_run.status == DataRun.Status.SUCCEEDED and latest_headline is None:
            app_access = "hard_locked"
            lock_reason = "incomplete_no_score"
            message = LOCK_MESSAGES["incomplete_no_score"]
        else:
            app_access = "hard_locked"
            lock_reason = "incomplete_no_score"
            message = LOCK_MESSAGES["incomplete_no_score"]

    if app_access == "unlocked":
        # Hide ready score only when the latest terminal run failed and nothing
        # is currently recalculating. While scheduled, keep showing the last
        # successful score (PRD: usable_score + scheduled → unlocked product).
        latest_failed = (
            not scheduled
            and latest_terminal is not None
            and latest_terminal.status == DataRun.Status.FAILED
            and latest_headline is None
        )
        if latest_failed:
            # Keep product unlocked (prior score existed) but do NOT show a
            # ready headline — that looked like a live/dummy score after failure.
            score_display = {
                "state": "not_calculated",
                "headline_score": None,
                "label": "Not calculated",
            }
            if message is None:
                message = LOCK_MESSAGES["failed"]
                error_text = (latest_terminal.metadata or {}).get("error")
                if isinstance(error_text, str) and error_text.strip():
                    snippet = _redact_secrets(error_text.strip())
                    if len(snippet) > 240:
                        snippet = f"{snippet[:237]}..."
                    message = f"{message} {snippet}"
                if last_succeeded_headline is not None:
                    message = (
                        f"{message} Last successful score was "
                        f"{round(last_succeeded_headline)}."
                    )
        else:
            # Prefer the current succeeded run; else most recent succeeded score
            # (never the historical max — that looks like a dummy/wrong score).
            display_headline = (
                latest_headline
                if latest_headline is not None
                else last_succeeded_headline
            )
            score_display = {
                "state": "ready",
                "headline_score": display_headline,
                "label": None,
            }
        allowed_routes = UNLOCKED_ALLOWED_ROUTES
    elif app_access == "soft_locked_running":
        score_display = {
            "state": "calculating",
            "headline_score": None,
            "label": "Calculating…",
        }
        allowed_routes = LOCKED_ALLOWED_ROUTES
    else:
        score_display = {
            "state": "not_calculated",
            "headline_score": None,
            "label": "Not calculated",
        }
        allowed_routes = LOCKED_ALLOWED_ROUTES

    progress_run = active_run if active_run is not None else latest_terminal
    run_progress = build_run_progress(progress_run, lock_reason=lock_reason)
    enrichment = build_status_enrichment(
        data_run=latest_terminal,
        company=company,
    )

    return {
        "app_access": app_access,
        "lock_reason": lock_reason,
        "message": message,
        "score_display": score_display,
        "latest_run": _serialize_run_summary(
            latest_terminal,
            optional_check_ids=optional_check_ids,
        ),
        "active_run": _serialize_run_summary(
            active_run,
            optional_check_ids=optional_check_ids,
        ),
        "scheduled": scheduled,
        "has_ever_scored": has_ever_scored,
        "best_headline_score": best_headline_score,
        "issues": _build_issues(
            latest_run=latest_terminal,
            lock_reason=lock_reason,
            optional_check_ids=optional_check_ids,
        ),
        "check_summary": enrichment["check_summary"],
        "dimensions": enrichment["dimensions"],
        "business_impact": enrichment["business_impact"],
        "dimension_checks": enrichment.get("dimension_checks"),
        "sample_size": enrichment.get("sample_size"),
        "allowed_routes": allowed_routes,
        "run_progress": run_progress,
    }


def resolve_dcs_app_status_for_user(*, user: User) -> dict[str, Any]:
    company = get_user_company(user)
    if company is None:
        return {
            "app_access": "hard_locked",
            "lock_reason": "no_run",
            "message": LOCK_MESSAGES["no_run"],
            "score_display": {
                "state": "not_calculated",
                "headline_score": None,
                "label": "Not calculated",
            },
            "latest_run": None,
            "active_run": None,
            "scheduled": False,
            "has_ever_scored": False,
            "best_headline_score": None,
            "issues": [],
            "check_summary": None,
            "dimensions": None,
            "business_impact": None,
            "dimension_checks": None,
            "sample_size": None,
            "allowed_routes": LOCKED_ALLOWED_ROUTES,
            "run_progress": None,
        }
    return resolve_dcs_app_status(company=company)
