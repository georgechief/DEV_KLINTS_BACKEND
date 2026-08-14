"""DCS-10 consecutive run-diff (audit) helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dataruns.dcs.worklist import (
    build_check_summary,
    coerce_headline_score,
    extract_business_impact,
    extract_dcs_payload,
    extract_dimensions,
    get_previous_scored_dcs_run,
)
from dataruns.models import DataRun
from tenants.models import Company

RUN_DIFF_SCHEMA_VERSION = 1


def _iso_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _dimension_scores_map(metadata: dict[str, Any]) -> dict[str, float] | None:
    dimensions = extract_dimensions(metadata)
    if not dimensions:
        return None
    scores: dict[str, float] = {}
    for name, dim in dimensions.items():
        if not isinstance(dim, dict):
            continue
        score = dim.get("score")
        if score is None or isinstance(score, bool):
            continue
        try:
            scores[str(name)] = float(score)
        except (TypeError, ValueError):
            continue
    return scores or None


def _estimate_snapshot(metadata: dict[str, Any]) -> dict[str, Any] | None:
    business_impact = extract_business_impact(metadata)
    if not isinstance(business_impact, dict):
        return None
    estimate = business_impact.get("estimate")
    if estimate is None or isinstance(estimate, bool):
        return None
    try:
        estimate_value = float(estimate)
    except (TypeError, ValueError):
        return None
    currency = business_impact.get("currency")
    snapshot: dict[str, Any] = {"estimate": estimate_value}
    if isinstance(currency, str) and currency.strip():
        snapshot["currency"] = currency.strip()
    return snapshot


def _check_summary_counts(metadata: dict[str, Any]) -> dict[str, int]:
    payload = extract_dcs_payload(metadata)
    check_results = [
        row for row in payload.get("check_results", []) if isinstance(row, dict)
    ]
    summary = build_check_summary(check_results) if check_results else {}
    blocked = payload.get("blocking_gates_failed")
    try:
        blocked_count = int(blocked or 0)
    except (TypeError, ValueError):
        blocked_count = 0
    return {
        "passed": int(summary.get("PASS", 0)),
        "failed": int(summary.get("FAIL", 0)),
        "blocked": blocked_count,
    }


def _delta_section(
    *,
    previous: float | int | None,
    current: float | int | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if previous is None and current is None:
        return None
    section: dict[str, Any] = {
        "previous": previous,
        "current": current,
        "delta": (
            float(current) - float(previous)
            if previous is not None and current is not None
            else None
        ),
    }
    if extra:
        section.update(extra)
    return section


def _dimension_delta_section(
    *,
    previous: dict[str, float] | None,
    current: dict[str, float] | None,
) -> dict[str, dict[str, Any]] | None:
    if not current and not previous:
        return None
    keys = set()
    if previous:
        keys.update(previous.keys())
    if current:
        keys.update(current.keys())
    if not keys:
        return None

    deltas: dict[str, dict[str, Any]] = {}
    for key in sorted(keys):
        prev_score = previous.get(key) if previous else None
        curr_score = current.get(key) if current else None
        section = _delta_section(previous=prev_score, current=curr_score)
        if section is not None:
            deltas[key] = section
    return deltas or None


def _summary_delta_section(
    *,
    previous: dict[str, int],
    current: dict[str, int],
) -> dict[str, dict[str, Any]]:
    return {
        key: _delta_section(
            previous=previous.get(key),
            current=current.get(key),
        )
        for key in ("passed", "failed", "blocked")
        if _delta_section(previous=previous.get(key), current=current.get(key)) is not None
    }


def build_consecutive_run_diff(
    *,
    current_metadata: dict[str, Any],
    previous_metadata: dict[str, Any] | None,
    previous_data_run: DataRun | None = None,
) -> dict[str, Any]:
    """Build PRD-DCS-10 consecutive run-diff payload."""
    if previous_metadata is None or previous_data_run is None:
        return {
            "schema_version": RUN_DIFF_SCHEMA_VERSION,
            "baseline": True,
            "compared_to_data_run_id": None,
            "compared_to_finished_at": None,
            "headline_score": None,
            "dimensions": None,
            "business_impact": None,
            "check_summary": None,
        }

    current_payload = extract_dcs_payload(current_metadata)
    previous_payload = extract_dcs_payload(previous_metadata)
    current_headline = coerce_headline_score(current_payload.get("headline_score"))
    previous_headline = coerce_headline_score(previous_payload.get("headline_score"))

    current_dims = _dimension_scores_map(current_metadata)
    previous_dims = _dimension_scores_map(previous_metadata)
    current_estimate = _estimate_snapshot(current_metadata)
    previous_estimate = _estimate_snapshot(previous_metadata)

    business_impact = None
    if current_estimate or previous_estimate:
        business_impact = {
            "estimate": _delta_section(
                previous=(previous_estimate or {}).get("estimate"),
                current=(current_estimate or {}).get("estimate"),
                extra={
                    "currency": (
                        (current_estimate or {}).get("currency")
                        or (previous_estimate or {}).get("currency")
                    )
                },
            )
        }

    return {
        "schema_version": RUN_DIFF_SCHEMA_VERSION,
        "baseline": False,
        "compared_to_data_run_id": previous_data_run.id,
        "compared_to_finished_at": _iso_timestamp(
            previous_data_run.finished_at or previous_data_run.created_at
        ),
        "headline_score": _delta_section(
            previous=previous_headline,
            current=current_headline,
        ),
        "dimensions": _dimension_delta_section(
            previous=previous_dims,
            current=current_dims,
        ),
        "business_impact": business_impact,
        "check_summary": _summary_delta_section(
            previous=_check_summary_counts(previous_metadata),
            current=_check_summary_counts(current_metadata),
        ),
    }


def persist_consecutive_run_diff(
    *,
    company: Company,
    data_run: DataRun,
) -> dict[str, Any] | None:
    """
    Persist ``metadata.run_diff`` for a succeeded scored run (idempotent).

    Returns the stored diff, or None when the run has no publishable headline score.
    """
    metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
    existing = metadata.get("run_diff")
    if isinstance(existing, dict) and existing.get("schema_version") == RUN_DIFF_SCHEMA_VERSION:
        return existing

    payload = extract_dcs_payload(metadata)
    if coerce_headline_score(payload.get("headline_score")) is None:
        return None

    previous_run = get_previous_scored_dcs_run(
        company=company,
        before_data_run_id=data_run.id,
    )
    run_diff = build_consecutive_run_diff(
        current_metadata=metadata,
        previous_metadata=(
            previous_run.metadata
            if previous_run is not None
            and isinstance(previous_run.metadata, dict)
            else None
        ),
        previous_data_run=previous_run,
    )
    data_run.metadata = {**metadata, "run_diff": run_diff}
    data_run.save(update_fields=["metadata", "updated_at"])
    return run_diff


def format_audit_score_summary(
    *,
    headline_score: float | None,
    run_state: str,
    run_diff: dict[str, Any] | None,
) -> str:
    """Human-readable audit summary with consecutive score delta when available."""
    if headline_score is None:
        return f"DCS score completed · {run_state}"

    delta = None
    if isinstance(run_diff, dict):
        headline = run_diff.get("headline_score")
        if isinstance(headline, dict):
            delta = headline.get("delta")

    if delta is None or run_diff.get("baseline"):
        return f"DCS score completed · {headline_score} · {run_state}"

    if delta > 0:
        return f"DCS score completed · {headline_score} (+{delta:g}) · {run_state}"
    if delta < 0:
        return f"DCS score completed · {headline_score} ({delta:g}) · {run_state}"
    return f"DCS score completed · {headline_score} · {run_state}"


def format_audit_at_stake_meta(metadata: dict[str, Any] | None) -> str | None:
    """Optional Activity secondary when consecutive at-stake estimate improved."""
    if not metadata:
        return None
    run_diff = metadata.get("run_diff")
    if not isinstance(run_diff, dict) or run_diff.get("baseline"):
        return None
    business_impact = run_diff.get("business_impact")
    if not isinstance(business_impact, dict):
        return None
    estimate = business_impact.get("estimate")
    if not isinstance(estimate, dict):
        return None
    delta = estimate.get("delta")
    if delta is None:
        return None
    try:
        delta_value = float(delta)
    except (TypeError, ValueError):
        return None
    if delta_value >= 0:
        return None

    amount = abs(delta_value)
    currency = estimate.get("currency")
    if isinstance(currency, str) and currency.strip():
        code = currency.strip().upper()
        body = f"{amount:,.0f}"
        if code == "EUR":
            formatted = f"€{body}"
        elif code == "USD":
            formatted = f"${body}"
        elif code == "GBP":
            formatted = f"£{body}"
        else:
            formatted = f"{code} {body}"
    else:
        formatted = f"{amount:,.0f}"

    return f"At-stake −{formatted} vs prior run"
