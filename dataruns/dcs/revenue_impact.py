"""PRD-DCS-08 — per-check revenue impact + deduped run rollup.

Numeric €/$ only for the locked allowlist (LE-05/09/04, PT-04, LE-02 alias).
Does not change DCS 0–100 score assembly.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from dataruns.dcs.types import CheckResult

ROLLUP_CHECK_IDS = frozenset({"LE-05", "LE-09", "LE-04", "PT-04"})
# LE-02 emits the same missing-GMV as LE-05 on the check card only.
CARD_ONLY_CHECK_IDS = frozenset({"LE-02"})
ALLOWLIST_CHECK_IDS = ROLLUP_CHECK_IDS | CARD_ONLY_CHECK_IDS

FORMULA_VERSION = "dcs_revenue_impact.v1"

_MONEY_EMIT_STATUSES = frozenset({"FAIL", "WARN"})
_ZERO_STATUSES = frozenset(
    {"PASS", "UNKNOWN", "NOT_CONNECTED", "NOT_APPLICABLE"}
)


def money_2(amount: float | Decimal | int | None) -> float:
    """Quantize to 2 decimal places (half-up) for storage/display."""
    if amount is None:
        return 0.0
    try:
        d = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return 0.0
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def attach_revenue_impact(
    provenance: dict[str, Any] | None,
    *,
    amount: float | Decimal | int | None,
    currency: str | None,
    formula_id: str,
    window_days: int | None,
    as_of: str | None,
    source: str,
    revenue_impact_unknown: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge PRD-DCS-08 provenance money fields onto a provenance dict."""
    out = dict(provenance or {})
    impact = money_2(amount)
    out["revenue_impact"] = impact
    out["revenue_currency"] = currency or None
    out["revenue_window_days"] = window_days
    out["revenue_as_of"] = as_of
    out["revenue_source"] = source
    out["revenue_formula_id"] = formula_id
    if revenue_impact_unknown:
        out["revenue_impact_unknown"] = True
    if extra:
        out.update(extra)
    return out


def seal_revenue_on_result(
    result: CheckResult,
    *,
    amount: float | Decimal | int | None,
    currency: str | None,
    formula_id: str,
    window_days: int | None,
    as_of: str | None,
    source: str,
    extra: dict[str, Any] | None = None,
) -> CheckResult:
    """
    Attach revenue_impact per status rules.

    PASS / UNKNOWN / NOT_CONNECTED / NOT_APPLICABLE → 0.
    FAIL / WARN → formula amount (0 + revenue_impact_unknown if gaps but no $).
    """
    status = str(result.status or "")
    if status in _ZERO_STATUSES or status not in _MONEY_EMIT_STATUSES:
        impact = 0.0
        unknown = False
    else:
        impact = money_2(amount)
        # Gaps present but no $ amounts available → flag unknown.
        unknown = impact == 0.0 and bool(extra and int(extra.get("gap_count") or 0) > 0)

    result.provenance = attach_revenue_impact(
        result.provenance if isinstance(result.provenance, dict) else {},
        amount=impact,
        currency=currency,
        formula_id=formula_id,
        window_days=window_days,
        as_of=as_of,
        source=source,
        revenue_impact_unknown=unknown and status in _MONEY_EMIT_STATUSES,
        extra=extra,
    )
    return result


def snapshot_revenue_context(
    snapshot: dict[str, Any],
    *,
    life: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Window / currency / source metadata from frozen scoring snapshot."""
    history = snapshot.get("history_depth")
    window_days = None
    if isinstance(history, dict) and history.get("common_window_days") is not None:
        try:
            window_days = int(history["common_window_days"])
        except (TypeError, ValueError):
            window_days = None
    if window_days is None and snapshot.get("window_days") is not None:
        try:
            window_days = int(snapshot["window_days"])
        except (TypeError, ValueError):
            window_days = None

    life = life if isinstance(life, dict) else (
        snapshot.get("lifecycle") if isinstance(snapshot.get("lifecycle"), dict) else {}
    )
    currency = str(life.get("primary_currency") or "").strip() or None
    raw = life.get("raw_enrichment") if isinstance(life.get("raw_enrichment"), dict) else {}
    source = (
        "snapshot_raw"
        if raw.get("shopify_orders_from_raw") or raw.get("manago_purchases_from_raw")
        else "db_fallback"
    )
    return {
        "as_of": snapshot.get("as_of"),
        "window_days": window_days,
        "currency": currency,
        "source": source,
    }


def duplicate_purchase_gmv(clusters: list[dict[str, Any]]) -> float:
    """Σ (event_count − 1) × representative_value over clusters with count ≥ 2."""
    total = Decimal("0")
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        if cluster.get("cluster_impact") is not None:
            total += Decimal(str(cluster["cluster_impact"]))
            continue
        count = int(cluster.get("count") or 0)
        if count < 2:
            continue
        if cluster.get("representative_value") is not None:
            rep = Decimal(str(cluster["representative_value"]))
        else:
            values = cluster.get("values") or []
            rep = Decimal(str(values[0] if values else 0))
        total += Decimal(count - 1) * rep
    return money_2(total)


def _result_impact(result: CheckResult) -> float:
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    raw = provenance.get("revenue_impact")
    if raw is None:
        return 0.0
    return money_2(raw)


def _result_currency(result: CheckResult) -> str | None:
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    cur = provenance.get("revenue_currency")
    return str(cur).strip() if cur else None


def rollup_revenue_impact(results: list[CheckResult]) -> dict[str, Any]:
    """
    Deduped run-level business_impact.

    Includes LE-05/09/04/PT-04 only. LE-02 is recorded under excluded_from_rollup.
    Mixed currencies → estimate=null + revenue_mixed_currency=true.
    """
    by_check: dict[str, float] = {}
    excluded: dict[str, float] = {}
    currencies: set[str] = set()
    window_days = None
    as_of = None

    for result in results:
        cid = result.check_id
        if cid not in ALLOWLIST_CHECK_IDS:
            continue
        if str(result.status or "") not in _MONEY_EMIT_STATUSES:
            continue
        impact = _result_impact(result)
        cur = _result_currency(result)
        if cur:
            currencies.add(cur)
        provenance = result.provenance if isinstance(result.provenance, dict) else {}
        if window_days is None and provenance.get("revenue_window_days") is not None:
            window_days = provenance.get("revenue_window_days")
        if as_of is None and provenance.get("revenue_as_of"):
            as_of = provenance.get("revenue_as_of")

        if cid in CARD_ONLY_CHECK_IDS:
            excluded[cid] = impact
            continue
        if cid in ROLLUP_CHECK_IDS:
            by_check[cid] = impact

    mixed = len(currencies) > 1
    currency = next(iter(currencies)) if len(currencies) == 1 else (
        None if mixed else None
    )
    if mixed:
        estimate = None
    else:
        estimate = money_2(sum(by_check.values()))

    return {
        "currency": currency,
        "estimate": estimate,
        "by_check": by_check,
        "excluded_from_rollup": excluded,
        "window_days": window_days,
        "as_of": as_of,
        "formula_version": FORMULA_VERSION,
        "revenue_mixed_currency": mixed,
    }
