"""DCS headline score history from terminal score runs (for trend charts)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from dataruns.dcs.status import (
    _coerce_headline_score,
    _company_dcs_runs_in_window,
    _extract_dcs_payload,
)
from dataruns.dcs.worklist import extract_business_impact, extract_dimensions
from tenants.models import Company

_MAX_HISTORY_DAYS = 366


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=timezone.utc)
    return parsed


def _parse_until(value: str | None) -> datetime | None:
    return _parse_since(value)


def _parse_days(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, min(days, _MAX_HISTORY_DAYS))


def _resolve_history_window(
    *,
    days: int | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
    until: datetime | None = None,
) -> tuple[datetime, datetime]:
    resolved_until = _parse_until(until_raw) or until or timezone.now()
    since = _parse_since(since_raw)
    if since is None and days is not None:
        since = resolved_until - timedelta(days=days)
    if since is None:
        since = resolved_until - timedelta(days=90)
    return since, resolved_until


def _coerce_capture_amount(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def _dimension_scores_from_metadata(metadata: dict[str, Any]) -> dict[str, float] | None:
    """Per-dimension scores from a terminal run (for period-over-period deltas)."""
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


def _capture_amounts_from_metadata(metadata: dict[str, Any]) -> tuple[float | None, float | None]:
    """
    Read per-run captured value amounts when persisted on the DataRun.

    Uses explicit captured fields only — never the at-stake ``estimate`` rollup.
    """
    business_impact = extract_business_impact(metadata)
    if not isinstance(business_impact, dict):
        return None, None

    revenue = _coerce_capture_amount(
        business_impact.get("revenue_captured", business_impact.get("captured_revenue"))
    )
    margin = _coerce_capture_amount(
        business_impact.get("margin_captured", business_impact.get("captured_margin"))
    )
    return revenue, margin


def _period_compare_snapshot(run: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "data_run_id": run["data_run_id"],
        "at": run["at"],
        "headline_score": run["headline_score"],
    }
    if run.get("dimensions"):
        snapshot["dimensions"] = run["dimensions"]
    if run.get("business_impact"):
        snapshot["business_impact"] = run["business_impact"]
    return snapshot


def _build_period_compare(qualifying_runs: list[dict[str, Any]]) -> dict[str, Any]:
    run_count = len(qualifying_runs)
    if run_count == 0:
        return {
            "available": False,
            "run_count": 0,
            "first": None,
            "last": None,
            "deltas": None,
        }

    first = qualifying_runs[0]
    last = qualifying_runs[-1]
    if run_count < 2:
        return {
            "available": False,
            "run_count": run_count,
            "first": _period_compare_snapshot(first),
            "last": _period_compare_snapshot(last),
            "deltas": None,
        }

    first_headline = first.get("headline_score")
    last_headline = last.get("headline_score")
    headline_delta = None
    if first_headline is not None and last_headline is not None:
        headline_delta = float(last_headline) - float(first_headline)

    dimension_deltas: dict[str, float] = {}
    first_dims = first.get("dimensions") or {}
    last_dims = last.get("dimensions") or {}
    for key in sorted(set(first_dims) | set(last_dims)):
        prev_score = first_dims.get(key)
        curr_score = last_dims.get(key)
        if prev_score is None or curr_score is None:
            continue
        dimension_deltas[key] = float(curr_score) - float(prev_score)

    first_estimate = (first.get("business_impact") or {}).get("estimate")
    last_estimate = (last.get("business_impact") or {}).get("estimate")
    estimate_delta = None
    captured_from_estimate = None
    if first_estimate is not None and last_estimate is not None:
        estimate_delta = float(last_estimate) - float(first_estimate)
        captured_from_estimate = max(0.0, float(first_estimate) - float(last_estimate))

    deltas: dict[str, Any] = {}
    if headline_delta is not None:
        deltas["headline_score"] = headline_delta
    if dimension_deltas:
        deltas["dimensions"] = dimension_deltas
    if estimate_delta is not None:
        deltas["estimate"] = estimate_delta
    if captured_from_estimate is not None:
        deltas["captured_from_estimate"] = captured_from_estimate

    return {
        "available": True,
        "run_count": run_count,
        "first": _period_compare_snapshot(first),
        "last": _period_compare_snapshot(last),
        "deltas": deltas or None,
    }


def build_dcs_histories(
    *,
    company: Company,
    days: int | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> dict[str, Any]:
    """
    Build score/value-capture history and period compare from one queryset pass.

    Returns points, value_capture, period_compare, and at_stake_series.
    """
    since, until = _resolve_history_window(
        days=days,
        since_raw=since_raw,
        until_raw=until_raw,
    )

    points: list[dict[str, Any]] = []
    revenue: list[dict[str, Any]] = []
    margin: list[dict[str, Any]] = []
    qualifying_runs: list[dict[str, Any]] = []
    at_stake_series: list[dict[str, Any]] = []

    for data_run in _company_dcs_runs_in_window(
        company=company,
        since=since,
        until=until,
    ):
        metadata = data_run.metadata if isinstance(data_run.metadata, dict) else {}
        at = data_run.finished_at or data_run.created_at
        if at is None:
            continue
        at_iso = at.isoformat().replace("+00:00", "Z")

        payload = _extract_dcs_payload(metadata)
        score = _coerce_headline_score(payload["headline_score"])
        dimension_scores = _dimension_scores_from_metadata(metadata)
        estimate_snapshot = _estimate_snapshot(metadata)

        if estimate_snapshot is not None:
            at_stake_series.append(
                {
                    "at": at_iso,
                    "value": estimate_snapshot["estimate"],
                    "data_run_id": data_run.id,
                    "currency": estimate_snapshot.get("currency"),
                }
            )

        if score is not None:
            point: dict[str, Any] = {
                "at": at_iso,
                "score": score,
                "data_run_id": data_run.id,
                "run_state": payload.get("run_state"),
            }
            if dimension_scores:
                point["dimensions"] = dimension_scores
            points.append(point)
            qualifying_runs.append(
                {
                    "data_run_id": data_run.id,
                    "at": at_iso,
                    "headline_score": score,
                    "dimensions": dimension_scores,
                    "business_impact": estimate_snapshot,
                }
            )

        revenue_amount, margin_amount = _capture_amounts_from_metadata(metadata)
        if revenue_amount is not None:
            revenue.append(
                {
                    "at": at_iso,
                    "value": revenue_amount,
                    "data_run_id": data_run.id,
                }
            )
        if margin_amount is not None:
            margin.append(
                {
                    "at": at_iso,
                    "value": margin_amount,
                    "data_run_id": data_run.id,
                }
            )

    return {
        "points": points,
        "value_capture": {"revenue": revenue, "margin": margin},
        "period_compare": _build_period_compare(qualifying_runs),
        "at_stake_series": at_stake_series,
        "since": since,
        "until": until,
    }


def build_dcs_score_history(
    *,
    company: Company,
    days: int | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> list[dict[str, Any]]:
    """Return chronological scored runs with a headline score in the window."""
    return build_dcs_histories(
        company=company,
        days=days,
        since_raw=since_raw,
        until_raw=until_raw,
    )["points"]


def build_dcs_value_capture_history(
    *,
    company: Company,
    days: int | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Chronological captured revenue / margin points for value-bar spark charts."""
    return build_dcs_histories(
        company=company,
        days=days,
        since_raw=since_raw,
        until_raw=until_raw,
    )["value_capture"]


def resolve_dcs_score_history_for_user(
    *,
    user,
    days_raw: str | None = None,
    since_raw: str | None = None,
    until_raw: str | None = None,
) -> dict[str, Any]:
    from tenants.auth.services import get_user_company

    company = get_user_company(user)
    days = _parse_days(days_raw)
    if company is None:
        return {
            "points": [],
            "value_capture": {"revenue": [], "margin": []},
            "at_stake_series": [],
            "period_compare": {
                "available": False,
                "run_count": 0,
                "first": None,
                "last": None,
                "deltas": None,
            },
            "since": None,
            "until": None,
        }

    histories = build_dcs_histories(
        company=company,
        days=days,
        since_raw=since_raw,
        until_raw=until_raw,
    )
    since = histories["since"]
    until = histories["until"]
    return {
        "points": histories["points"],
        "value_capture": histories["value_capture"],
        "at_stake_series": histories["at_stake_series"],
        "period_compare": histories["period_compare"],
        "since": since.isoformat().replace("+00:00", "Z"),
        "until": until.isoformat().replace("+00:00", "Z"),
    }
