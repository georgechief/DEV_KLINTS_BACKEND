"""DCS-09 Step 4 — Slice A supplemental executors (CI-08, CC-06).

Catalogue 02 detection is qualitative. Thresholds below are provisional MVP1
bands with ``STOP_AND_FLAG`` — do not silently invent Catalogue cutovers.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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
# CI-08: sheet 02 Suggested Fix = "Flag invalid set" → any hit FAIL (no % cutover).
# CC-06 window: Use Case Library sheet 03 UC-05 blueprint Wait (2 days) =
#   "Allow the initial confirmation window to pass" (+ UC-05_blueprint.json).
# CC-06 stuck-share %: Catalogue silent — provisional FAIL band below.
# Deferred (Catalogue text, not measurable in Slice A inputs): confirmation-email
# deliverability; DOI policy consistency across signup sources.
# ---------------------------------------------------------------------------
CI08_SAMPLE = 50

# UC-05 Wait (2 days) — Use Case Library sheet 03: "initial confirmation window".
CC06_CONFIRMATION_WINDOW_DAYS = 2
# STOP_AND_FLAG: share stuck beyond window. Catalogue 02 has no % — provisional.
CC06_FAIL_STUCK_SHARE = 0.05
CC06_SAMPLE = 50

# RFC-lite (not full RFC 5322) — Catalogue: "Syntactic validation … (RFC-lite)".
_EMAIL_RFC_LITE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# Obvious typo domains — Catalogue explicitly cites gmial.com etc.
# STOP_AND_FLAG: expand only from Catalogue / ops list, not guessed at scale.
_TYPO_DOMAINS = frozenset(
    {
        "gmial.com",
        "gmal.com",
        "gamil.com",
        "gnail.com",
        "gmai.com",
        "hotnail.com",
        "hotmial.com",
        "outlok.com",
        "yaho.com",
        "yahooo.com",
    }
)

# Disposable mailbox hosts — provisional seed list (STOP_AND_FLAG).
_DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "guerrillamail.org",
        "10minutemail.com",
        "tempmail.com",
        "trashmail.com",
        "yopmail.com",
        "sharklasers.com",
        "discard.email",
    }
)

# Manago / pack "Not confirmed" vocabulary (UC-05 trigger).
_NOT_CONFIRMED_TOKENS = frozenset(
    {
        "NOT_CONFIRMED",
        "NOT-CONFIRMED",
        "NOT CONFIRMED",
        "NOTCONFIRMED",
        "PENDING_CONFIRMATION",
        "PENDING-CONFIRMATION",
        "AWAITING_CONFIRMATION",
        "AWAITING-CONFIRMATION",
        "UNCONFIRMED",
        "DOI_PENDING",
        "DOUBLE_OPT_IN_PENDING",
    }
)

# Explicit confirmed / reachable opt-in vocabulary (for DOI measurability).
_CONFIRMED_TOKENS = frozenset(
    {
        "CONFIRMED",
        "CONFIRMED_OPT_IN",
        "DOUBLE_OPT_IN",
        "DOUBLE-OPT-IN",
        "DOI_CONFIRMED",
        "OPT_IN_CONFIRMED",
    }
)


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


def _load_manago_contacts(
    ctx: SupplementalGateContext,
) -> tuple[list[dict[str, Any]], str]:
    """
    Prefer frozen snapshot inputs; else latest Manago ConnectorSnapshot raw.

    Snapshot preference:
    1. ``gate_inputs.manago_contacts`` (test / evaluate inject; empty list wins)
    2. ``supplemental.manago_contacts`` (empty list wins)
    3. ConnectorSnapshot ``raw.contacts`` via company
    4. Identity snapshot emails (``manago_ai`` + ``both``) — format-only
    """
    snapshot = ctx.snapshot()
    for key_path, node in (
        ("gate_inputs", snapshot.get("gate_inputs")),
        ("supplemental", snapshot.get("supplemental")),
    ):
        if isinstance(node, dict) and "manago_contacts" in node:
            contacts = node.get("manago_contacts")
            if isinstance(contacts, list):
                return (
                    [c for c in contacts if isinstance(c, dict)],
                    f"snapshot.{key_path}.manago_contacts",
                )

    from dataruns.dcs.lifecycle_join import _latest_connector_raw

    raw = _latest_connector_raw(company=ctx.company, platform="manago_ai")
    contacts = [c for c in (raw.get("contacts") or []) if isinstance(c, dict)]
    if contacts:
        return contacts, "connector_snapshot.raw.contacts"

    # Fallback: identity join emails already on DCS score snapshot (format-only).
    identity_contacts = snapshot.get("contacts")
    if isinstance(identity_contacts, list) and identity_contacts:
        rows: list[dict[str, Any]] = []
        for item in identity_contacts:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            if source not in {"manago_ai", "both"}:
                continue
            email = item.get("person.email") or item.get("email") or ""
            rows.append(
                {
                    "email": email,
                    "contactId": item.get("manago_contact_id")
                    or item.get("external_key")
                    or "",
                    "_from_identity_snapshot": True,
                }
            )
        if rows:
            return rows, "snapshot.contacts(manago_ai)"

    return [], "none"


def _email_for_format_check(email: str) -> str:
    """Lowercase + strip whitespace only (do not strip plus-aliases for RFC-lite)."""
    return re.sub(r"\s+", "", str(email or "").strip().lower())


def _email_domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def _classify_email(email: str, *, manago_invalid: Any = None) -> str | None:
    """
    Return failure reason code fragment, or None if OK.

    Catalogue CI-08: RFC-lite + disposable + typo domains; Manago ``invalid``
    when present is treated as hard invalid (deliverability flag).
    """
    text = str(email or "").strip()
    if not text:
        return None  # blank skipped by caller
    if manago_invalid is True:
        return "manago_invalid"
    normalized = _email_for_format_check(text)
    if ".." in normalized or normalized.startswith(".") or normalized.endswith("."):
        return "rfc_lite"
    if not _EMAIL_RFC_LITE.match(normalized):
        return "rfc_lite"
    domain = _email_domain(normalized)
    if not domain:
        return "rfc_lite"
    if domain in _TYPO_DOMAINS:
        return "typo_domain"
    if domain in _DISPOSABLE_DOMAINS:
        return "disposable_domain"
    return None


def _normalize_state_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text


def _is_not_confirmed(contact: dict[str, Any]) -> bool:
    state = _normalize_state_token(contact.get("state"))
    if state in {_normalize_state_token(t) for t in _NOT_CONFIRMED_TOKENS}:
        return True
    # Loose contains for "Not confirmed" variants from Manago UI copy.
    raw = str(contact.get("state") or "").strip().lower()
    if "not confirm" in raw or "not-confirm" in raw:
        return True
    doi = contact.get("doiStatus") or contact.get("doi_status") or contact.get("optInStatus")
    doi_tok = _normalize_state_token(doi)
    if doi_tok in {_normalize_state_token(t) for t in _NOT_CONFIRMED_TOKENS}:
        return True
    if doi_tok in {"PENDING", "NOT_CONFIRMED", "UNCONFIRMED"}:
        return True
    return False


def _is_confirmed(contact: dict[str, Any]) -> bool:
    state = _normalize_state_token(contact.get("state"))
    if state in {_normalize_state_token(t) for t in _CONFIRMED_TOKENS}:
        return True
    doi = contact.get("doiStatus") or contact.get("doi_status") or contact.get("optInStatus")
    doi_tok = _normalize_state_token(doi)
    if doi_tok in {_normalize_state_token(t) for t in _CONFIRMED_TOKENS}:
        return True
    if doi_tok in {"CONFIRMED", "COMPLETED", "DOUBLE_OPT_IN"}:
        return True
    return False


def _contact_created_at(contact: dict[str, Any]) -> datetime | None:
    for key in (
        "createdOn",
        "created_at",
        "doi_requested_at",
        "doiRequestedAt",
        "modifiedOn",
    ):
        parsed = _parse_ts(contact.get(key))
        if parsed is not None:
            return parsed
    return None


def evaluate_ci08(ctx: SupplementalGateContext) -> CheckResult:
    """CI-08 Email format validity (Manago) — Catalogue 02."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = str(ctx.evaluated_at or "") or "1970-01-01T00:00:00Z"
    contacts, source = _load_manago_contacts(ctx)

    if not contacts:
        if not _connector_connected(snapshot, "manago_ai"):
            return make_supplemental_result(
                check_id="CI-08",
                status=STATUS_NOT_CONNECTED,
                ctx=ctx,
                reason_code="NOT_CONNECTED:manago",
                message="CI-08 requires Manago connected (or injected manago contacts).",
                confidence="HIGH",
                evidence=[
                    _evidence(
                        source="pilot_gates",
                        locator="connectors.manago_ai",
                        value=False,
                        observed_at=observed,
                    )
                ],
            )
        return result_unknown_missing_input(
            check_id="CI-08",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_contacts",
            message="CI-08: no Manago contacts available to validate.",
            detail={"source": source},
        )

    invalid_rows: list[dict[str, Any]] = []
    evaluated = 0
    for contact in contacts:
        email = str(contact.get("email") or contact.get("person.email") or "").strip()
        if not email:
            continue
        evaluated += 1
        reason = _classify_email(email, manago_invalid=contact.get("invalid"))
        if reason is None:
            continue
        invalid_rows.append(
            {
                "email": email,
                "reason": reason,
                "contactId": str(
                    contact.get("contactId") or contact.get("id") or ""
                ),
                "domain": _email_domain(_email_for_format_check(email)),
            }
        )

    if evaluated == 0:
        return result_unknown_missing_input(
            check_id="CI-08",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_emails",
            message="CI-08: Manago contacts present but none have email values.",
            detail={"contacts": len(contacts), "source": source},
        )

    invalid_n = len(invalid_rows)
    invalid_share = round(invalid_n / max(evaluated, 1), 4)
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="ci08.summary",
            value={
                "source": source,
                "evaluated_emails": evaluated,
                "invalid_count": invalid_n,
                "invalid_share": invalid_share,
                # STOP_AND_FLAG note for Catalogue threshold gap
                "threshold": "any_invalid_FAIL",
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="ci08.invalid_sample",
            value=invalid_rows[:CI08_SAMPLE],
            observed_at=observed,
        ),
    ]

    if invalid_n > 0:
        return make_supplemental_result(
            check_id="CI-08",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="CI08_INVALID_EMAIL_SET",
            message=(
                f"CI-08 FAIL: {invalid_n}/{evaluated} Manago emails fail RFC-lite / "
                f"typo / disposable / invalid flag (share={invalid_share})."
            ),
            confidence="HIGH",
            evidence=evidence,
        )

    return make_supplemental_result(
        check_id="CI-08",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=f"CI-08 PASS: {evaluated} Manago emails passed format checks.",
        confidence="HIGH",
        evidence=evidence,
    )


def evaluate_cc06(ctx: SupplementalGateContext) -> CheckResult:
    """CC-06 Double opt-in state integrity (Manago) — Catalogue 02 / UC-05."""
    from dataruns.dcs.pilot_gates.executors import (
        REASON_MISSING_INPUT,
        make_supplemental_result,
        result_unknown_missing_input,
    )

    snapshot = ctx.snapshot()
    observed = str(ctx.evaluated_at or "") or "1970-01-01T00:00:00Z"
    as_of = _as_of(ctx, snapshot)
    contacts, source = _load_manago_contacts(ctx)

    if not contacts:
        if not _connector_connected(snapshot, "manago_ai"):
            return make_supplemental_result(
                check_id="CC-06",
                status=STATUS_NOT_CONNECTED,
                ctx=ctx,
                reason_code="NOT_CONNECTED:manago",
                message="CC-06 requires Manago connected (or injected manago contacts).",
                confidence="HIGH",
                evidence=[
                    _evidence(
                        source="pilot_gates",
                        locator="connectors.manago_ai",
                        value=False,
                        observed_at=observed,
                    )
                ],
            )
        return result_unknown_missing_input(
            check_id="CC-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:manago_contacts",
            message="CC-06: no Manago contacts available for DOI state check.",
            detail={"source": source},
        )

    # Identity-snapshot fallback has no state → cannot invent PASS.
    if source.startswith("snapshot.contacts"):
        return result_unknown_missing_input(
            check_id="CC-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:doi_state",
            message=(
                "CC-06: identity snapshot emails lack Manago DOI/state fields; "
                "need ConnectorSnapshot raw contacts."
            ),
            detail={"source": source, "contacts": len(contacts)},
        )

    not_confirmed = [c for c in contacts if _is_not_confirmed(c)]
    confirmed = [c for c in contacts if _is_confirmed(c)]
    doi_measurable = bool(not_confirmed or confirmed)
    if not doi_measurable:
        # Catalogue also mentions confirmation-email deliverability + signup-source
        # DOI policy — not measurable from contact state alone here.
        return result_unknown_missing_input(
            check_id="CC-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:doi_state",
            message=(
                "CC-06: no Not-confirmed/Confirmed DOI vocabulary on Manago contacts "
                "(STOP_AND_FLAG: cannot invent PASS)."
            ),
            detail={
                "source": source,
                "contacts": len(contacts),
                "note": (
                    "deliverability + signup-source DOI policy consistency not "
                    "evaluated in Slice A without dedicated email/list inputs"
                ),
            },
        )

    window = timedelta(days=CC06_CONFIRMATION_WINDOW_DAYS)
    stuck: list[dict[str, Any]] = []
    age_unknown = 0
    for contact in not_confirmed:
        created = _contact_created_at(contact)
        if created is None:
            # Cannot prove "beyond confirmation window" without a timestamp.
            age_unknown += 1
            continue
        age_days = max(int((as_of - created).total_seconds() // 86400), 0)
        if created > (as_of - window):
            continue
        stuck.append(
            {
                "contactId": str(
                    contact.get("contactId") or contact.get("id") or ""
                ),
                "email": str(contact.get("email") or ""),
                "state": contact.get("state"),
                "age_days": age_days,
            }
        )

    if not_confirmed and age_unknown == len(not_confirmed):
        return result_unknown_missing_input(
            check_id="CC-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:doi_timestamps",
            message=(
                "CC-06: Not-confirmed contacts lack createdOn/doi_requested_at; "
                "cannot measure confirmation window (STOP_AND_FLAG: no invented FAIL)."
            ),
            detail={
                "source": source,
                "not_confirmed": len(not_confirmed),
                "confirmation_window_days": CC06_CONFIRMATION_WINDOW_DAYS,
            },
        )

    denom = max(len(contacts), 1)
    stuck_share = round(len(stuck) / denom, 4)
    evidence = [
        _evidence(
            source="pilot_gates",
            locator="cc06.summary",
            value={
                "source": source,
                "contacts": len(contacts),
                "not_confirmed": len(not_confirmed),
                "confirmed": len(confirmed),
                "stuck_beyond_window": len(stuck),
                "not_confirmed_age_unknown": age_unknown,
                "stuck_share": stuck_share,
                "confirmation_window_days": CC06_CONFIRMATION_WINDOW_DAYS,
                "fail_stuck_share": CC06_FAIL_STUCK_SHARE,
                "stop_and_flag": (
                    "window from Use Case Library sheet 03 UC-05 Wait (2d); "
                    "stuck-share cutover provisional"
                ),
            },
            observed_at=observed,
        ),
        _evidence(
            source="pilot_gates",
            locator="cc06.stuck_sample",
            value=stuck[:CC06_SAMPLE],
            observed_at=observed,
        ),
    ]

    if stuck_share > CC06_FAIL_STUCK_SHARE:
        return make_supplemental_result(
            check_id="CC-06",
            status=STATUS_FAIL,
            ctx=ctx,
            reason_code="CC06_DOI_STUCK_SHARE",
            message=(
                f"CC-06 FAIL: {len(stuck)}/{len(contacts)} contacts stuck "
                f"Not-confirmed beyond {CC06_CONFIRMATION_WINDOW_DAYS}d "
                f"(share={stuck_share} > {CC06_FAIL_STUCK_SHARE})."
            ),
            confidence="MEDIUM",
            evidence=evidence,
        )

    # Incomplete ages → do not invent PASS for the unmeasurable Not-confirmed set.
    if age_unknown > 0:
        return result_unknown_missing_input(
            check_id="CC-06",
            ctx=ctx,
            reason_code=f"{REASON_MISSING_INPUT}:doi_timestamps",
            message=(
                f"CC-06: {age_unknown} Not-confirmed contact(s) lack timestamps; "
                "stuck share within band on measurable subset only — "
                "cannot issue PASS (STOP_AND_FLAG)."
            ),
            detail={
                "source": source,
                "stuck_share_measurable": stuck_share,
                "not_confirmed_age_unknown": age_unknown,
            },
        )

    # Measurable DOI vocabulary and stuck share within band → PASS.
    # Deliverability / multi-source policy consistency: not separately scored yet.
    return make_supplemental_result(
        check_id="CC-06",
        status=STATUS_PASS,
        ctx=ctx,
        reason_code=None,
        message=(
            f"CC-06 PASS: stuck Not-confirmed share={stuck_share} within "
            f"provisional band (window={CC06_CONFIRMATION_WINDOW_DAYS}d)."
        ),
        confidence="MEDIUM",
        evidence=evidence,
    )


SLICE_A_EXECUTORS = {
    "CI-08": evaluate_ci08,
    "CC-06": evaluate_cc06,
}
