"""DCS-09 Step 8 — Slice B supplemental executors (remaining 10 checks).

Catalogue 02 detection is qualitative. Thresholds below are provisional MVP1
bands with ``STOP_AND_FLAG`` — do not silently invent Catalogue cutovers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dataruns.dcs.pilot_gates.context import SupplementalGateContext
from dataruns.dcs.pilot_gates.contract import (
    STATUS_FAIL,
    STATUS_NOT_CONNECTED,
    STATUS_PASS,
)
from dataruns.dcs.types import CheckResult, Evidence

# Executors helpers imported lazily inside evaluate_* to avoid circular import
# (executors registers this module at import time).

# ---------------------------------------------------------------------------
# STOP_AND_FLAG — provisional bands (Catalogue 02 has no numeric cutovers).
# ---------------------------------------------------------------------------
SAMPLE_CAP = 50

# SP-10: missing RFM among purchase-history contacts.
SP10_FAIL_MISSING_RFM_SHARE = 0.10
# LE-07: cart capture rate vs abandoned checkouts with email.
LE07_FAIL_CAPTURE_RATE = 0.70
# LE-10: OTHER dumping-ground share.
LE10_FAIL_OTHER_SHARE = 0.25
# PT-05: relative price delta vs Shopify (max(shopify, 1) denom).
PT05_FAIL_PRICE_REL_DIFF = 0.05
# PT-11: incomplete required attribute share.
PT11_FAIL_INCOMPLETE_SHARE = 0.10
# BR-09: missing pack_size / consumption_days share.
BR09_FAIL_MISSING_INPUT_SHARE = 0.10

# SP-04 plausibility window for parsed dates.
SP04_YEAR_MIN = 1990
SP04_YEAR_MAX = 2100


def _evidence(*, source: str, locator: str, value: Any, observed_at: str) -> Evidence:
    return Evidence(
        source=source,
        locator=locator,
        value=value,
        observed_at=observed_at,
    )


def _connector_connected(snapshot: dict[str, Any], platform: str) -> bool:
    connectors = snapshot.get("connectors")
    if not isinstance(connectors, dict):
        return False
    row = connectors.get(platform)
    if not isinstance(row, dict):
        return False
    return str(row.get("status") or "") in {"connected", "degraded"}


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        n = float(value)
        if n > 1e12:
            n = n / 1000.0
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_ts(int(text))
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _as_of(ctx: SupplementalGateContext, snapshot: dict[str, Any]) -> datetime:
    for raw in (snapshot.get("as_of"), ctx.evaluated_at):
        parsed = _parse_ts(raw)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc).replace(microsecond=0)


def _observed(ctx: SupplementalGateContext) -> str:
    return str(ctx.evaluated_at or "") or "1970-01-01T00:00:00Z"


def _load_list_input(
    ctx: SupplementalGateContext,
    key: str,
) -> tuple[list[dict[str, Any]] | None, str]:
    """
    Prefer ``gate_inputs[key]`` then ``supplemental[key]``.

    Empty list is authoritative (return ``[], source``).
    If key absent → ``(None, "")``.
    """
    snapshot = ctx.snapshot()
    for key_path, node in (
        ("gate_inputs", snapshot.get("gate_inputs")),
        ("supplemental", snapshot.get("supplemental")),
    ):
        if not isinstance(node, dict) or key not in node:
            continue
        raw = node.get(key)
        if isinstance(raw, list):
            rows = [row for row in raw if isinstance(row, dict)]
            # Non-empty list with zero dict rows is malformed — do not treat as
            # authoritative empty (that would invent PASS).
            if raw and not rows:
                return None, f"snapshot.{key_path}.{key}:malformed"
            return rows, f"snapshot.{key_path}.{key}"
        # Present but wrong type → missing/unknown (not empty).
        return None, f"snapshot.{key_path}.{key}:invalid_type"
    return None, ""


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    n = _as_float(value)
    if n is None:
        return None
    try:
        return int(n)
    except (TypeError, ValueError):
        return None


def _email_of(row: dict[str, Any]) -> str:
    return str(row.get("email") or row.get("person.email") or "").strip().lower()


def _product_ids(row: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("product_id", "variant_id", "productId", "variantId"):
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        text = str(raw).strip()
        if text and text not in ids:
            ids.append(text)
    return ids


def _qty_of(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in row:
            return _as_float(row.get(key))
    return None


def _rfm_assigned(contact: dict[str, Any]) -> bool:
    for key in ("rfm_segment", "rfm", "rfmSegment"):
        raw = contact.get(key)
        if raw is None:
            continue
        if isinstance(raw, dict):
            if any(str(v).strip() for v in raw.values() if v is not None):
                return True
            continue
        if str(raw).strip():
            return True
    return False


def _has_purchase_history(contact: dict[str, Any]) -> bool:
    if contact.get("has_purchase_history") is True:
        return True
    if contact.get("hasPurchaseHistory") is True:
        return True
    count = _as_int(contact.get("purchase_count"))
    return count is not None and count > 0


def _shopify_code_usable(row: dict[str, Any]) -> bool:
    if row.get("expired") is True:
        return False
    if row.get("valid") is False:
        return False
    status = str(row.get("status") or "").strip().lower()
    if status in {"expired", "invalid", "disabled", "inactive", "archived"}:
        return False
    return True


def _is_cart_type(row: dict[str, Any]) -> bool:
    text = str(row.get("type") or row.get("event_type") or "").strip().upper()
    return "CART" in text


def _event_type(row: dict[str, Any]) -> str:
    return str(row.get("event_type") or row.get("type") or "").strip().upper()


def _is_reservation_purchase(row: dict[str, Any]) -> bool:
    if _event_type(row) != "PURCHASE":
        return False
    if row.get("is_reservation") is True:
        return True
    purpose = str(row.get("purpose") or "").strip().lower()
    return purpose == "reservation"


def _parse_date_plausible(value: Any) -> datetime | None:
    """Parse date-like values; require year in [SP04_YEAR_MIN, SP04_YEAR_MAX]."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        parsed = dt.astimezone(timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        # Date-only YYYY-MM-DD
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            try:
                parsed = datetime(
                    int(text[0:4]),
                    int(text[5:7]),
                    int(text[8:10]),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                return None
        else:
            parsed = _parse_ts(text)
            if parsed is None:
                return None
    if parsed.year < SP04_YEAR_MIN or parsed.year > SP04_YEAR_MAX:
        return None
    return parsed


def _attr(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) is not None and row.get(key) != "":
            return row.get(key)
    return None


def _not_connected(
    *,
    check_id: str,
    ctx: SupplementalGateContext,
    platform: str,
    reason_platform: str,
    message: str,
    make_supplemental_result: Any,
) -> CheckResult:
    observed = _observed(ctx)
    return make_supplemental_result(
        check_id=check_id,
        status=STATUS_NOT_CONNECTED,
        ctx=ctx,
        reason_code=f"NOT_CONNECTED:{reason_platform}",
        message=message,
        confidence="HIGH",
        evidence=[
            _evidence(
                source="pilot_gates",
                locator=f"connectors.{platform}",
                value=False,
                observed_at=observed,
            )
        ],
    )


# ---------------------------------------------------------------------------
# SP-10 RFM computability coverage
# ---------------------------------------------------------------------------


def evaluate_sp10(ctx: SupplementalGateContext) -> CheckResult:
    """SP-10 RFM computability — Catalogue 02 / UC-06B."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    contacts, source = _load_list_input(ctx, "manago_contacts")

    if contacts is None:
        if not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="SP-10",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="SP-10 requires Manago connected (or injected manago contacts).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="SP-10",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_contacts",
            message="SP-10: manago_contacts input missing.",
            detail={"source": source or "none"},
        )

    purchasers = 0
    missing_rfm: list[dict[str, Any]] = []
    for contact in contacts:
        if not _has_purchase_history(contact):
            continue
        purchasers += 1
        if _rfm_assigned(contact):
            continue
        missing_rfm.append(
            {
                "contactId": str(
                    contact.get("contactId") or contact.get("id") or ""
                ),
                "email": str(contact.get("email") or ""),
                "purchase_count": contact.get("purchase_count"),
                "has_purchase_history": contact.get("has_purchase_history"),
            }
        )

    missing_n = len(missing_rfm)
    missing_events_share = round(missing_n / max(purchasers, 1), 4) if purchasers else 0.0
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="sp10.summary",
            value={
                "source": source,
                "contacts": len(contacts),
                "purchasers": purchasers,
                "missing_rfm": missing_n,
                "missing_events_share": missing_events_share,
                "fail_missing_rfm_share": SP10_FAIL_MISSING_RFM_SHARE,
                # STOP_AND_FLAG: Catalogue 02 has no % cutover for missing-events.
                "stop_and_flag": "missing RFM share provisional; no Catalogue numeric",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="sp10.missing_rfm_sample",
            value=missing_rfm[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    # Contacts present but no purchase-history fields at all → cannot measure.
    if contacts and not any(
        ("purchase_count" in c)
        or ("has_purchase_history" in c)
        or ("hasPurchaseHistory" in c)
        for c in contacts
    ):
        return result_unknown_missing_input(
            check_id="SP-10",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:purchase_history",
            message=(
                "SP-10: contacts present but purchase_count / "
                "has_purchase_history fields absent (cannot invent PASS)."
            ),
            detail={"contacts": len(contacts), "purchasers": 0},
        )

    if purchasers > 0 and missing_events_share > SP10_FAIL_MISSING_RFM_SHARE:
        return make_supplemental_result(
            check_id="SP-10",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="SP10_MISSING_RFM_SHARE",
            message=(
                f"SP-10 FAIL: missing RFM share={missing_events_share} "
                f"among {purchasers} purchasers "
                f"(>{SP10_FAIL_MISSING_RFM_SHARE})."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="SP-10",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=(
            f"SP-10 PASS: missing RFM share={missing_events_share} "
            f"within provisional band (purchasers={purchasers})."
        ),
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# PT-13 Coupon / discount consistency
# ---------------------------------------------------------------------------


def evaluate_pt13(ctx: SupplementalGateContext) -> CheckResult:
    """PT-13 Coupon and discount consistency — Catalogue 02 / UC-04."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    coupons, coupons_src = _load_list_input(ctx, "manago_coupons")
    codes, codes_src = _load_list_input(ctx, "shopify_discount_codes")

    if coupons is None or codes is None:
        if codes is None and not _connector_connected(snapshot, "shopify"):
            return _not_connected(
                check_id="PT-13",
                ctx=ctx,
                platform="shopify",
                reason_platform="shopify",
                message="PT-13 requires Shopify connected (or injected coupon lists).",
                make_supplemental_result=make_supplemental_result,
            )
        if coupons is None and not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="PT-13",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="PT-13 requires Manago connected (or injected coupon lists).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="PT-13",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:coupon_lists",
            message="PT-13: need manago_coupons and shopify_discount_codes.",
            detail={
                "manago_coupons": coupons_src or "absent",
                "shopify_discount_codes": codes_src or "absent",
            },
        )

    shopify_by_code: dict[str, dict[str, Any]] = {}
    for row in codes:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        shopify_by_code[code.lower()] = row

    mismatches: list[dict[str, Any]] = []
    for row in coupons:
        code = str(row.get("code") or "").strip()
        if not code:
            mismatches.append({"code": "", "reason": "missing_code"})
            continue
        shop = shopify_by_code.get(code.lower())
        if shop is None:
            mismatches.append({"code": code, "reason": "missing_in_shopify"})
            continue
        if not _shopify_code_usable(shop):
            mismatches.append(
                {
                    "code": code,
                    "reason": "invalid_or_expired",
                    "shopify_status": shop.get("status"),
                    "valid": shop.get("valid"),
                    "expired": shop.get("expired"),
                }
            )

    evidence = [
        _evidence(
            source="pilot_gates",
            locator="pt13.summary",
            value={
                "manago_coupons_source": coupons_src,
                "shopify_codes_source": codes_src,
                "manago_coupons": len(coupons),
                "shopify_discount_codes": len(codes),
                "mismatches": len(mismatches),
                "stop_and_flag": "any mismatch FAIL; Catalogue 02 has no % band",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="pt13.mismatch_sample",
            value=mismatches[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if mismatches:
        return make_supplemental_result(
            check_id="PT-13",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="PT13_COUPON_MISMATCH",
            message=(
                f"PT-13 FAIL: {len(mismatches)} Manago coupon(s) missing/"
                "invalid/expired in Shopify."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="PT-13",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=f"PT-13 PASS: {len(coupons)} Manago coupon(s) match usable Shopify codes.",
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# LE-07 Cart event coverage
# ---------------------------------------------------------------------------


def evaluate_le07(ctx: SupplementalGateContext) -> CheckResult:
    """LE-07 Cart event coverage — Catalogue 02 / UC-21."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    abandoned, abd_src = _load_list_input(ctx, "shopify_abandoned_checkouts")
    cart_events, cart_src = _load_list_input(ctx, "manago_cart_events")

    if abandoned is None or cart_events is None:
        if abandoned is None and not _connector_connected(snapshot, "shopify"):
            return _not_connected(
                check_id="LE-07",
                ctx=ctx,
                platform="shopify",
                reason_platform="shopify",
                message="LE-07 requires Shopify connected (or injected cart lists).",
                make_supplemental_result=make_supplemental_result,
            )
        if cart_events is None and not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="LE-07",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="LE-07 requires Manago connected (or injected cart lists).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="LE-07",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:cart_coverage_lists",
            message=(
                "LE-07: need shopify_abandoned_checkouts and manago_cart_events."
            ),
            detail={
                "shopify_abandoned_checkouts": abd_src or "absent",
                "manago_cart_events": cart_src or "absent",
            },
        )

    # Injected lists are authoritative — only NOT_CONNECTED when lists absent
    # (handled above via UNKNOWN) and caller relies on live connectors later.
    abandoned_with_email = [r for r in abandoned if _email_of(r)]
    abandoned_without_email = [
        {
            "id": str(r.get("id") or ""),
            "reason": "missing_email",
        }
        for r in abandoned
        if not _email_of(r)
    ]
    abandoned_emails = {_email_of(r) for r in abandoned_with_email}
    cart_emails = {
        _email_of(r)
        for r in cart_events
        if _is_cart_type(r) and _email_of(r)
    }
    matched_emails = abandoned_emails & cart_emails
    unmatched_abandoned = sorted(abandoned_emails - cart_emails)
    denom = len(abandoned_emails)
    capture_rate = (
        round(len(matched_emails) / max(denom, 1), 4) if denom else 0.0
    )
    # Identity gaps count as fail samples; also drag capture when abandoned>=1.
    identity_fail = len(abandoned_without_email) > 0
    rate_fail = len(abandoned) >= 1 and (
        denom == 0 or capture_rate < LE07_FAIL_CAPTURE_RATE
    )

    fail_sample: list[dict[str, Any]] = list(abandoned_without_email[:SAMPLE_CAP])
    if len(fail_sample) < SAMPLE_CAP:
        for email in unmatched_abandoned:
            fail_sample.append({"email": email, "reason": "no_cart_event"})
            if len(fail_sample) >= SAMPLE_CAP:
                break
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="le07.summary",
            value={
                "abandoned_source": abd_src,
                "cart_events_source": cart_src,
                "abandoned": len(abandoned),
                "abandoned_with_email": denom,
                "abandoned_without_email": len(abandoned_without_email),
                "manago_cart_emails": len(cart_emails),
                "matched_emails": len(matched_emails),
                "unmatched_abandoned_emails": len(unmatched_abandoned),
                "capture_rate": capture_rate,
                "fail_capture_rate": LE07_FAIL_CAPTURE_RATE,
                # STOP_AND_FLAG: 0.70 provisional; Catalogue 02 silent on %.
                "stop_and_flag": "capture_rate cutover provisional",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="le07.fail_sample",
            value=fail_sample,
            observed_at=observed,
        ),
    ]

    if identity_fail or rate_fail:
        parts: list[str] = []
        if identity_fail:
            parts.append(
                f"{len(abandoned_without_email)} abandoned without email"
            )
        if rate_fail:
            parts.append(
                f"capture_rate={capture_rate} < {LE07_FAIL_CAPTURE_RATE}"
            )
        return make_supplemental_result(
            check_id="LE-07",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="LE07_CART_CAPTURE",
            message=f"LE-07 FAIL: {'; '.join(parts)}.",
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="LE-07",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=(
            f"LE-07 PASS: capture_rate={capture_rate} "
            f"(abandoned={len(abandoned)})."
        ),
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# LE-10 Event type discipline
# ---------------------------------------------------------------------------


def evaluate_le10(ctx: SupplementalGateContext) -> CheckResult:
    """LE-10 Event type discipline — Catalogue 02 / UC-09."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    events, source = _load_list_input(ctx, "manago_events")

    if events is None:
        if not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="LE-10",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="LE-10 requires Manago connected (or injected manago_events).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="LE-10",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_events",
            message="LE-10: manago_events input missing.",
            detail={"source": source or "none"},
        )

    other_n = 0
    other_rows: list[dict[str, Any]] = []
    type_changed_rows: list[dict[str, Any]] = []
    reservation_rows: list[dict[str, Any]] = []
    for ev in events:
        et = _event_type(ev)
        if et == "OTHER":
            other_n += 1
            if len(other_rows) < SAMPLE_CAP:
                other_rows.append(
                    {
                        "event_type": "OTHER",
                        "id": str(ev.get("id") or ""),
                    }
                )
        if ev.get("type_changed") is True:
            if len(type_changed_rows) < SAMPLE_CAP:
                type_changed_rows.append(
                    {
                        "event_type": et,
                        "id": str(ev.get("id") or ""),
                        "type_changed": True,
                    }
                )
        if _is_reservation_purchase(ev):
            if len(reservation_rows) < SAMPLE_CAP:
                reservation_rows.append(
                    {
                        "event_type": et,
                        "id": str(ev.get("id") or ""),
                        "is_reservation": ev.get("is_reservation"),
                        "purpose": ev.get("purpose"),
                    }
                )

    total = len(events)
    other_share = round(other_n / max(total, 1), 4) if total else 0.0
    fail_other = total > 0 and other_share > LE10_FAIL_OTHER_SHARE
    fail_changed = len(type_changed_rows) > 0
    fail_reservation = len(reservation_rows) > 0

    # Prefer type_changed / reservation samples so OTHER volume cannot starve them.
    sample: list[dict[str, Any]] = []
    for bucket in (type_changed_rows, reservation_rows, other_rows):
        for row in bucket:
            if len(sample) >= SAMPLE_CAP:
                break
            sample.append(row)
        if len(sample) >= SAMPLE_CAP:
            break
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="le10.summary",
            value={
                "source": source,
                "events": total,
                "other_count": other_n,
                "other_share": other_share,
                "fail_other_share": LE10_FAIL_OTHER_SHARE,
                "type_changed": len(type_changed_rows),
                "reservation_purchases": len(reservation_rows),
                # STOP_AND_FLAG: OTHER share 0.25 provisional.
                "stop_and_flag": "OTHER share cutover provisional",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="le10.fail_sample",
            value=sample,
            observed_at=observed,
        ),
    ]

    if fail_other or fail_changed or fail_reservation:
        parts: list[str] = []
        if fail_other:
            parts.append(f"OTHER share={other_share} > {LE10_FAIL_OTHER_SHARE}")
        if fail_changed:
            parts.append(f"{len(type_changed_rows)} type_changed")
        if fail_reservation:
            parts.append(f"{len(reservation_rows)} reservation PURCHASE")
        return make_supplemental_result(
            check_id="LE-10",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="LE10_EVENT_DISCIPLINE",
            message=f"LE-10 FAIL: {'; '.join(parts)}.",
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="LE-10",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=f"LE-10 PASS: event type discipline ok (events={total}).",
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# PT-05 Price parity
# ---------------------------------------------------------------------------


def evaluate_pt05(ctx: SupplementalGateContext) -> CheckResult:
    """PT-05 Price parity catalog vs commerce — Catalogue 02 / UC-13."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    manago, manago_src = _load_list_input(ctx, "manago_products")
    shopify, shopify_src = _load_list_input(ctx, "shopify_products")

    if manago is None or shopify is None:
        if shopify is None and not _connector_connected(snapshot, "shopify"):
            return _not_connected(
                check_id="PT-05",
                ctx=ctx,
                platform="shopify",
                reason_platform="shopify",
                message="PT-05 requires Shopify connected (or injected product lists).",
                make_supplemental_result=make_supplemental_result,
            )
        if manago is None and not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="PT-05",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="PT-05 requires Manago connected (or injected product lists).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="PT-05",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:product_price_lists",
            message="PT-05: need manago_products and shopify_products.",
            detail={
                "manago_products": manago_src or "absent",
                "shopify_products": shopify_src or "absent",
            },
        )

    shopify_by_id: dict[str, dict[str, Any]] = {}
    for row in shopify:
        for pid in _product_ids(row):
            shopify_by_id.setdefault(pid, row)

    mismatches: list[dict[str, Any]] = []
    compared = 0
    for row in manago:
        manago_price = _as_float(row.get("price"))
        discount_price = _as_float(
            row.get("discount_price")
            if "discount_price" in row
            else row.get("discountPrice")
        )
        if discount_price is not None and manago_price is not None:
            if discount_price > manago_price:
                mismatches.append(
                    {
                        "ids": _product_ids(row),
                        "reason": "discount_gt_price",
                        "price": manago_price,
                        "discount_price": discount_price,
                    }
                )

        matched: dict[str, Any] | None = None
        matched_id = ""
        for pid in _product_ids(row):
            if pid in shopify_by_id:
                matched = shopify_by_id[pid]
                matched_id = pid
                break
        if matched is None or manago_price is None:
            continue
        shop_price = _as_float(matched.get("price"))
        if shop_price is None:
            continue
        compared += 1
        rel = abs(manago_price - shop_price) / max(shop_price, 1.0)
        if rel > PT05_FAIL_PRICE_REL_DIFF:
            mismatches.append(
                {
                    "id": matched_id,
                    "reason": "price_delta",
                    "manago_price": manago_price,
                    "shopify_price": shop_price,
                    "rel_diff": round(rel, 4),
                }
            )

    evidence = [
        _evidence(
            source="pilot_gates",
            locator="pt05.summary",
            value={
                "manago_source": manago_src,
                "shopify_source": shopify_src,
                "manago_products": len(manago),
                "shopify_products": len(shopify),
                "compared": compared,
                "mismatches": len(mismatches),
                "fail_price_rel_diff": PT05_FAIL_PRICE_REL_DIFF,
                # STOP_AND_FLAG: 5% relative band provisional.
                "stop_and_flag": "price rel-diff cutover provisional",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="pt05.mismatch_sample",
            value=mismatches[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if mismatches:
        return make_supplemental_result(
            check_id="PT-05",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="PT05_PRICE_PARITY",
            message=f"PT-05 FAIL: {len(mismatches)} price/discount parity issue(s).",
            confidence="HIGH",
            evidence=evidence,
        )

    # Do not invent PASS when catalogs are present but nothing joined.
    if compared == 0 and (len(manago) > 0 or len(shopify) > 0):
        return result_unknown_missing_input(
            check_id="PT-05",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:price_join",
            message=(
                "PT-05: no comparable product/variant price pairs "
                "(cannot invent PASS)."
            ),
            detail={
                "manago_products": len(manago),
                "shopify_products": len(shopify),
                "compared": 0,
            },
        )

    return make_supplemental_result(
        check_id="PT-05",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=f"PT-05 PASS: price parity ok (compared={compared}).",
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# PT-06 Stock quantity parity (ERP-sensitive; framework handles ERP-out)
# ---------------------------------------------------------------------------


def evaluate_pt06(ctx: SupplementalGateContext) -> CheckResult:
    """PT-06 Stock quantity parity — Catalogue 02 / UC-12, UC-21.

    When ``erp_in_scope=false`` the framework short-circuits to NOT_CONNECTED
    before this executor. Do not emit ERP-out NOT_CONNECTED here.
    """
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    manago, manago_src = _load_list_input(ctx, "manago_products")
    inventory, inv_src = _load_list_input(ctx, "shopify_inventory")
    erp_stock, erp_src = _load_list_input(ctx, "erp_stock")

    if manago is None or inventory is None:
        if inventory is None and not _connector_connected(snapshot, "shopify"):
            return _not_connected(
                check_id="PT-06",
                ctx=ctx,
                platform="shopify",
                reason_platform="shopify",
                message=(
                    "PT-06 requires Shopify connected "
                    "(or injected stock lists) when ERP is in scope."
                ),
                make_supplemental_result=make_supplemental_result,
            )
        if manago is None and not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="PT-06",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message=(
                    "PT-06 requires Manago connected "
                    "(or injected stock lists) when ERP is in scope."
                ),
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="PT-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:stock_lists",
            message="PT-06: need manago_products and shopify_inventory.",
            detail={
                "manago_products": manago_src or "absent",
                "shopify_inventory": inv_src or "absent",
                "erp_stock": erp_src or "absent_optional",
            },
        )

    shopify_by_id: dict[str, float] = {}
    for row in inventory:
        qty = _qty_of(row, "quantity", "qty", "stock", "available")
        if qty is None:
            continue
        for pid in _product_ids(row):
            shopify_by_id.setdefault(pid, qty)

    mismatches: list[dict[str, Any]] = []
    compared = 0
    for row in manago:
        manago_qty = _qty_of(row, "qty", "quantity", "stock")
        ids = _product_ids(row)
        already_flagged = False
        if manago_qty is not None and manago_qty < 0:
            mismatches.append(
                {"ids": ids, "reason": "negative_manago_qty", "qty": manago_qty}
            )
            already_flagged = True
        shop_qty: float | None = None
        matched_id = ""
        for pid in ids:
            if pid in shopify_by_id:
                shop_qty = shopify_by_id[pid]
                matched_id = pid
                break
        if shop_qty is not None and shop_qty < 0:
            mismatches.append(
                {
                    "id": matched_id,
                    "reason": "negative_shopify_qty",
                    "qty": shop_qty,
                }
            )
            already_flagged = True
        if manago_qty is None or shop_qty is None:
            continue
        compared += 1
        if already_flagged:
            continue
        if abs(manago_qty - shop_qty) > 0:
            mismatches.append(
                {
                    "id": matched_id,
                    "reason": "qty_diff",
                    "manago_qty": manago_qty,
                    "shopify_qty": shop_qty,
                    "abs_diff": abs(manago_qty - shop_qty),
                }
            )

    evidence = [
        _evidence(
            source="pilot_gates",
            locator="pt06.summary",
            value={
                "manago_source": manago_src,
                "shopify_inventory_source": inv_src,
                "erp_stock_source": erp_src or "absent_optional",
                "erp_stock_rows": len(erp_stock or []),
                "manago_products": len(manago),
                "shopify_inventory": len(inventory),
                "compared": compared,
                "mismatches": len(mismatches),
                # STOP_AND_FLAG: any abs diff FAIL; ERP three-way deferred v1.
                "stop_and_flag": (
                    "v1 Manago↔Shopify only; erp_stock evidence-only; "
                    "Catalogue silent on tolerance"
                ),
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="pt06.mismatch_sample",
            value=mismatches[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if mismatches:
        return make_supplemental_result(
            check_id="PT-06",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="PT06_STOCK_PARITY",
            message=f"PT-06 FAIL: {len(mismatches)} stock parity issue(s).",
            confidence="HIGH",
            evidence=evidence,
        )

    # Do not invent PASS when stock lists are present but nothing joined.
    if compared == 0 and (len(manago) > 0 or len(inventory) > 0):
        return result_unknown_missing_input(
            check_id="PT-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:stock_join",
            message=(
                "PT-06: no comparable product stock pairs "
                "(cannot invent PASS)."
            ),
            detail={
                "manago_products": len(manago),
                "shopify_inventory": len(inventory),
                "compared": 0,
            },
        )

    return make_supplemental_result(
        check_id="PT-06",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=f"PT-06 PASS: stock parity ok (compared={compared}).",
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# PT-11 Product attribute completeness
# ---------------------------------------------------------------------------


def evaluate_pt11(ctx: SupplementalGateContext) -> CheckResult:
    """PT-11 Product attribute completeness — Catalogue 02 / UC-28."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    products, source = _load_list_input(ctx, "manago_products")

    if products is None:
        if not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="PT-11",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="PT-11 requires Manago connected (or injected catalog).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="PT-11",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_products",
            message="PT-11: manago_products catalog list missing.",
            detail={"source": source or "none"},
        )

    incomplete: list[dict[str, Any]] = []
    for row in products:
        missing: list[str] = []
        if not _attr(row, "category"):
            missing.append("category")
        if not _attr(row, "brand"):
            missing.append("brand")
        if not _attr(row, "image_url", "imageUrl"):
            missing.append("image_url")
        if not _attr(row, "product_url", "productUrl"):
            missing.append("product_url")
        if not missing:
            continue
        incomplete.append(
            {
                "ids": _product_ids(row),
                "missing": missing,
            }
        )

    total = len(products)
    incomplete_share = round(len(incomplete) / max(total, 1), 4) if total else 0.0
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="pt11.summary",
            value={
                "source": source,
                "products": total,
                "incomplete": len(incomplete),
                "incomplete_share": incomplete_share,
                "fail_incomplete_share": PT11_FAIL_INCOMPLETE_SHARE,
                # STOP_AND_FLAG: 10% incomplete share provisional.
                "stop_and_flag": "incomplete_share cutover provisional",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="pt11.incomplete_sample",
            value=incomplete[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if total > 0 and incomplete_share > PT11_FAIL_INCOMPLETE_SHARE:
        return make_supplemental_result(
            check_id="PT-11",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="PT11_ATTR_INCOMPLETE",
            message=(
                f"PT-11 FAIL: incomplete_share={incomplete_share} "
                f"> {PT11_FAIL_INCOMPLETE_SHARE}."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="PT-11",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=(
            f"PT-11 PASS: incomplete_share={incomplete_share} "
            f"within provisional band."
        ),
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# BR-03 OOS in active surfaces
# ---------------------------------------------------------------------------


def evaluate_br03(ctx: SupplementalGateContext) -> CheckResult:
    """BR-03 Out-of-stock exposure in active surfaces — Catalogue 02 / UC-28."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    products, source = _load_list_input(ctx, "active_surface_products")

    if products is None:
        if not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="BR-03",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message=(
                    "BR-03 requires Manago connected "
                    "(or injected active_surface_products)."
                ),
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="BR-03",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:active_surface_products",
            message="BR-03: active_surface_products list missing.",
            detail={"source": source or "none"},
        )

    oos: list[dict[str, Any]] = []
    missing_stock: list[dict[str, Any]] = []
    for row in products:
        stock = _qty_of(row, "stock", "quantity", "available")
        pid = str(row.get("product_id") or row.get("id") or "")
        if stock is None:
            missing_stock.append(
                {
                    "product_id": pid,
                    "surface": row.get("surface"),
                    "reason": "missing_stock",
                }
            )
            continue
        if stock <= 0:
            oos.append(
                {
                    "product_id": pid,
                    "surface": row.get("surface"),
                    "stock": stock,
                }
            )

    evidence = [
        _evidence(
            source="pilot_gates",
            locator="br03.summary",
            value={
                "source": source,
                "products": len(products),
                "oos": len(oos),
                "missing_stock": len(missing_stock),
                # STOP_AND_FLAG: any OOS FAIL; Catalogue qualitative.
                "stop_and_flag": "any active-surface OOS FAIL",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="br03.oos_sample",
            value=(oos + missing_stock)[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if oos:
        return make_supplemental_result(
            check_id="BR-03",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="BR03_ACTIVE_OOS",
            message=(
                f"BR-03 FAIL: {len(oos)} active-surface product(s) with stock<=0."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    if missing_stock:
        return result_unknown_missing_input(
            check_id="BR-03",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:stock",
            message=(
                f"BR-03: {len(missing_stock)} active-surface product(s) lack "
                "stock/quantity/available (cannot invent PASS)."
            ),
            detail={"missing_stock": len(missing_stock), "source": source},
        )

    return make_supplemental_result(
        check_id="BR-03",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=f"BR-03 PASS: {len(products)} active-surface product(s) in stock.",
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# BR-09 Replenishment inputs (ERP-sensitive; framework handles ERP-out)
# ---------------------------------------------------------------------------


def evaluate_br09(ctx: SupplementalGateContext) -> CheckResult:
    """BR-09 Replenishment input completeness — Catalogue 02 / UC-08, UC-11.

    When ``erp_in_scope=false`` the framework short-circuits to NOT_CONNECTED
    before this executor. Do not emit ERP-out NOT_CONNECTED here.
    """
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    observed = _observed(ctx)
    products, source = _load_list_input(ctx, "replenishment_products")

    if products is None:
        return result_unknown_missing_input(
            check_id="BR-09",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:replenishment_products",
            message="BR-09: replenishment_products list missing.",
            detail={"source": source or "none"},
        )

    incomplete: list[dict[str, Any]] = []
    for row in products:
        pack = row.get("pack_size")
        consumption = row.get("consumption_days")
        if consumption is None:
            consumption = row.get("expected_consumption_days")
        missing: list[str] = []
        if pack is None or pack == "" or _as_float(pack) is None:
            missing.append("pack_size")
        if consumption is None or consumption == "" or _as_float(consumption) is None:
            missing.append("consumption_days")
        if not missing:
            continue
        incomplete.append(
            {
                "product_id": str(row.get("product_id") or row.get("id") or ""),
                "missing": missing,
            }
        )

    total = len(products)
    missing_share = round(len(incomplete) / max(total, 1), 4) if total else 0.0
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="br09.summary",
            value={
                "source": source,
                "products": total,
                "incomplete": len(incomplete),
                "missing_share": missing_share,
                "fail_missing_input_share": BR09_FAIL_MISSING_INPUT_SHARE,
                # STOP_AND_FLAG: 10% missing share provisional.
                "stop_and_flag": "replenishment missing-share cutover provisional",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="br09.incomplete_sample",
            value=incomplete[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if total > 0 and missing_share > BR09_FAIL_MISSING_INPUT_SHARE:
        return make_supplemental_result(
            check_id="BR-09",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="BR09_REPLENISHMENT_INPUTS",
            message=(
                f"BR-09 FAIL: missing pack_size/consumption_days "
                f"share={missing_share} > {BR09_FAIL_MISSING_INPUT_SHARE}."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="BR-09",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=(
            f"BR-09 PASS: replenishment input missing_share={missing_share} "
            "within provisional band."
        ),
        confidence="HIGH",
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# SP-04 Date-prefixed detail validity
# ---------------------------------------------------------------------------


def evaluate_sp04(ctx: SupplementalGateContext) -> CheckResult:
    """SP-04 Date-prefixed detail validity — Catalogue 02 / UC-11.

    STOP_AND_FLAG: Manago proximity trigger may require dictionary vs date.
    detail type for ``klints_next_refill`` — confirm against Manago docs before
    treating type mismatch as PASS/FAIL beyond parseability.
    """
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = _observed(ctx)
    contacts, source = _load_list_input(ctx, "manago_contacts")

    if contacts is None:
        if not _connector_connected(snapshot, "manago_ai"):
            return _not_connected(
                check_id="SP-04",
                ctx=ctx,
                platform="manago_ai",
                reason_platform="manago",
                message="SP-04 requires Manago connected (or injected contacts).",
                make_supplemental_result=make_supplemental_result,
            )
        return result_unknown_missing_input(
            check_id="SP-04",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_contacts",
            message="SP-04: manago_contacts list missing.",
            detail={"source": source or "none"},
        )

    invalid: list[dict[str, Any]] = []
    checked = 0

    def _check_date_field(
        *,
        contact_id: str,
        key: str,
        value: Any,
    ) -> None:
        nonlocal checked
        checked += 1
        if _parse_date_plausible(value) is None:
            invalid.append(
                {
                    "contactId": contact_id,
                    "key": key,
                    "value": value,
                    "reason": "invalid_or_implausible_date",
                }
            )

    for contact in contacts:
        contact_id = str(contact.get("contactId") or contact.get("id") or "")
        details = contact.get("details")
        if isinstance(details, dict):
            for key, value in details.items():
                key_text = str(key)
                if not key_text.lower().startswith("date."):
                    continue
                _check_date_field(contact_id=contact_id, key=key_text, value=value)

        date_details = contact.get("date_details")
        if isinstance(date_details, list):
            for item in date_details:
                if not isinstance(item, dict):
                    continue
                key_text = str(
                    item.get("key") or item.get("name") or item.get("field") or ""
                )
                value = item.get("value") if "value" in item else item.get("date")
                if key_text and not key_text.lower().startswith("date."):
                    continue
                if key_text or value is not None:
                    _check_date_field(
                        contact_id=contact_id,
                        key=key_text or "date_details",
                        value=value,
                    )

        # klints_next_refill — date-like when present (STOP_AND_FLAG type note).
        if "klints_next_refill" in contact:
            _check_date_field(
                contact_id=contact_id,
                key="klints_next_refill",
                value=contact.get("klints_next_refill"),
            )
        elif isinstance(details, dict) and "klints_next_refill" in details:
            _check_date_field(
                contact_id=contact_id,
                key="details.klints_next_refill",
                value=details.get("klints_next_refill"),
            )

    evidence = [
        _evidence(
            source="pilot_gates",
            locator="sp04.summary",
            value={
                "source": source,
                "contacts": len(contacts),
                "date_fields_checked": checked,
                "invalid": len(invalid),
                "year_window": [SP04_YEAR_MIN, SP04_YEAR_MAX],
                # STOP_AND_FLAG: dictionary vs date. detail type for proximity.
                "stop_and_flag": (
                    "verify Manago proximity trigger consumes date. detail vs "
                    "dictionary detail for klints_next_refill"
                ),
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="sp04.invalid_sample",
            value=invalid[:SAMPLE_CAP],
            observed_at=observed,
        ),
    ]

    if invalid:
        return make_supplemental_result(
            check_id="SP-04",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="SP04_INVALID_DATE_DETAIL",
            message=(
                f"SP-04 FAIL: {len(invalid)} date-prefixed / refill "
                "detail(s) invalid or outside plausibility window."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    # Contacts present but no date.* / refill fields to validate → UNKNOWN.
    if checked == 0 and len(contacts) > 0:
        return result_unknown_missing_input(
            check_id="SP-04",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:date_details",
            message=(
                "SP-04: contacts present but no date.-prefixed / "
                "klints_next_refill fields to validate."
            ),
            detail={"contacts": len(contacts), "date_fields_checked": 0},
        )

    return make_supplemental_result(
        check_id="SP-04",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=(
            f"SP-04 PASS: {checked} date field(s) parsed within "
            f"{SP04_YEAR_MIN}-{SP04_YEAR_MAX}."
        ),
        confidence="HIGH",
        evidence=evidence,
    )


SLICE_B_EXECUTORS = {
    "SP-10": evaluate_sp10,
    "PT-13": evaluate_pt13,
    "LE-07": evaluate_le07,
    "LE-10": evaluate_le10,
    "PT-05": evaluate_pt05,
    "PT-06": evaluate_pt06,
    "PT-11": evaluate_pt11,
    "BR-03": evaluate_br03,
    "BR-09": evaluate_br09,
    "SP-04": evaluate_sp04,
}

# Import-time lock: map keys must equal contract Slice B set.
from dataruns.dcs.pilot_gates.contract import SLICE_B_CHECK_IDS as _SLICE_B_IDS

if set(SLICE_B_EXECUTORS) != set(_SLICE_B_IDS):
    raise RuntimeError(
        "SLICE_B_EXECUTORS keys must equal SLICE_B_CHECK_IDS "
        f"(missing={sorted(set(_SLICE_B_IDS) - set(SLICE_B_EXECUTORS))} "
        f"extra={sorted(set(SLICE_B_EXECUTORS) - set(_SLICE_B_IDS))})"
    )
