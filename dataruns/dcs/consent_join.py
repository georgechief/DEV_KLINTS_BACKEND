"""Excel sheet 02/06 consent join for DCS scoring snapshot (PRD-DCS-04 batch 4b).

Surfaces:
- Shopify ``email_marketing_consent`` / ``sms_marketing_consent``
  (state, opt_in_level, consent_updated_at)
- Manago ``optedOut`` / ``optedOutPhone`` + ``consents[]`` provenance
- Manago ``invalid`` as hard-bounce / suppression proxy when present
- Link spine: Manago ``externalId`` ↔ Shopify customer id; fallback email
- Propagation lag from Shopify consent_updated_at vs Manago modifiedOn
- Soft phone reachability (CI-09-lite) for CC-02 joint surfacing
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from statistics import median
from typing import Any

from dataruns.dcs.identity_join import normalize_email
from dataruns.dcs.lifecycle_join import _latest_connector_raw
from tenants.models import Company

CC_SAMPLE = 50

# Shopify consent states → opt-in boolean (Excel CC-01/02).
_SHOPIFY_IN = frozenset({"subscribed"})
_SHOPIFY_OUT = frozenset({"not_subscribed", "unsubscribed", "redacted"})

# Soft E.164-lite for CC-02 joint CI-09 surfacing (CI-09 not in MVP1 scored set).
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_DIGITS_RE = re.compile(r"^\d{10,15}$")


def _shopify_consent_in(consent: Any) -> bool | None:
    if not isinstance(consent, dict):
        return None
    state = str(consent.get("state") or "").lower().strip()
    if state in _SHOPIFY_IN:
        return True
    if state in _SHOPIFY_OUT or state == "pending":
        # pending = not fully opted in for marketing sends
        return False
    if not state:
        return None
    return False


def _manago_email_in(contact: dict[str, Any]) -> bool | None:
    if "optedOut" not in contact:
        return None
    # optedOut True → out; False → in
    return contact.get("optedOut") is False


def _manago_sms_in(contact: dict[str, Any]) -> bool | None:
    if "optedOutPhone" not in contact:
        return None
    return contact.get("optedOutPhone") is False


def _provenance_ok(consents: Any) -> tuple[bool, bool, str | None]:
    """
    Excel CC-03: source/reason + timestamp on opted-in contacts.

    Returns (has_provenance, is_weak_agent_like, note).
    Empty consents[] on an opt-in = no customer-originated evidence.
    """
    if not isinstance(consents, list) or not consents:
        return False, True, "empty_consents_array"
    for item in consents:
        if not isinstance(item, dict):
            continue
        # Common Manago consent object shapes.
        source = (
            item.get("source")
            or item.get("consentSource")
            or item.get("agreementFrom")
            or item.get("ip")
            or item.get("url")
        )
        reason = item.get("reason") or item.get("name") or item.get("consentName")
        ts = (
            item.get("agreementDate")
            or item.get("consentDate")
            or item.get("createdOn")
            or item.get("date")
            or item.get("timestamp")
        )
        if (source or reason) and ts:
            return True, False, None
        if source or reason or ts:
            # Partial — still weak vs full provenance
            return False, True, "partial_consent_fields"
    return False, True, "consents_without_source_or_timestamp"


def _quadrant(shopify_in: bool | None, manago_in: bool | None) -> str | None:
    if shopify_in is None or manago_in is None:
        return None
    if shopify_in and manago_in:
        return "in_in"
    if shopify_in and not manago_in:
        return "in_out"
    if (not shopify_in) and manago_in:
        return "out_in"
    return "out_out"


def phone_valid_e164_lite(phone: Any) -> bool:
    """CI-09-lite: parseable E.164 or plain 10–15 digit national form."""
    raw = str(phone or "").strip()
    if not raw:
        return False
    compact = re.sub(r"[\s\-().]", "", raw)
    if _E164_RE.match(compact):
        return True
    if compact.startswith("00") and _DIGITS_RE.match(compact[2:]):
        return True
    return bool(_DIGITS_RE.match(compact))


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Manago often uses epoch ms
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
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _lag_seconds(a: Any, b: Any) -> float | None:
    ta = _parse_ts(a)
    tb = _parse_ts(b)
    if ta is None or tb is None:
        return None
    return abs((ta - tb).total_seconds())


def build_consent_snapshot(*, company: Company) -> dict[str, Any]:
    shopify_raw = _latest_connector_raw(company=company, platform="shopify")
    manago_raw = _latest_connector_raw(company=company, platform="manago_ai")
    shopify_customers = [
        c for c in (shopify_raw.get("customers") or []) if isinstance(c, dict)
    ]
    manago_contacts = [
        c for c in (manago_raw.get("contacts") or []) if isinstance(c, dict)
    ]
    shopify_from_raw = bool(shopify_customers)
    manago_from_raw = bool(manago_contacts)

    shopify_by_id: dict[str, dict[str, Any]] = {}
    shopify_by_email: dict[str, dict[str, Any]] = {}
    for cust in shopify_customers:
        cid = cust.get("id")
        if cid is None:
            continue
        sid = str(cid)
        email_c = cust.get("email_marketing_consent")
        sms_c = cust.get("sms_marketing_consent")
        row = {
            "shopify_customer_id": sid,
            "person.email": normalize_email(cust.get("email")),
            "person.phone": str(cust.get("phone") or ""),
            "email_marketing_consent": email_c if isinstance(email_c, dict) else {},
            "sms_marketing_consent": sms_c if isinstance(sms_c, dict) else {},
            "email_in": _shopify_consent_in(email_c),
            "sms_in": _shopify_consent_in(sms_c),
            "email_consent_updated_at": (
                (email_c or {}).get("consent_updated_at")
                if isinstance(email_c, dict)
                else None
            ),
            "sms_consent_updated_at": (
                (sms_c or {}).get("consent_updated_at")
                if isinstance(sms_c, dict)
                else None
            ),
            "email_opt_in_level": (
                (email_c or {}).get("opt_in_level")
                if isinstance(email_c, dict)
                else None
            ),
            "sms_opt_in_level": (
                (sms_c or {}).get("opt_in_level")
                if isinstance(sms_c, dict)
                else None
            ),
        }
        shopify_by_id[sid] = row
        if row["person.email"]:
            shopify_by_email[row["person.email"]] = row

    # Manago ``invalid`` field presence = suppression signal available (CC-05).
    invalid_field_seen = False
    manago_rows: list[dict[str, Any]] = []
    for contact in manago_contacts:
        mid = str(contact.get("contactId") or contact.get("id") or "")
        link = str(contact.get("externalId") or "").strip()
        email = normalize_email(contact.get("email"))
        consents = contact.get("consents")
        email_in = _manago_email_in(contact)
        sms_in = _manago_sms_in(contact)
        prov_ok, weak, prov_note = _provenance_ok(consents)
        if "invalid" in contact:
            invalid_field_seen = True
        phone = str(contact.get("phone") or "")
        manago_rows.append(
            {
                "manago_contact_id": mid,
                "person.external_key": link,
                "person.email": email,
                "person.phone": phone,
                "phone_valid": phone_valid_e164_lite(phone),
                "email_in": email_in,
                "sms_in": sms_in,
                "optedOut": contact.get("optedOut"),
                "optedOutPhone": contact.get("optedOutPhone"),
                "invalid": contact.get("invalid"),
                "consents": consents if isinstance(consents, list) else [],
                "provenance_ok": prov_ok,
                "provenance_weak": weak,
                "provenance_note": prov_note,
                "modified_on": contact.get("modifiedOn") or contact.get("createdOn"),
                "state": contact.get("state"),
            }
        )

    linked: list[dict[str, Any]] = []
    used_shopify: set[str] = set()
    for m in manago_rows:
        shopify = None
        link_kind = None
        link = m["person.external_key"]
        if link and link in shopify_by_id:
            shopify = shopify_by_id[link]
            link_kind = "external_key"
        elif m["person.email"] and m["person.email"] in shopify_by_email:
            shopify = shopify_by_email[m["person.email"]]
            link_kind = "email"
        if shopify is None:
            continue
        used_shopify.add(shopify["shopify_customer_id"])
        email_q = _quadrant(shopify["email_in"], m["email_in"])
        sms_q = _quadrant(shopify["sms_in"], m["sms_in"])
        phone_for_sms = m["person.phone"] or shopify.get("person.phone") or ""
        phone_ok = phone_valid_e164_lite(phone_for_sms)
        email_lag = _lag_seconds(
            shopify["email_consent_updated_at"], m["modified_on"]
        )
        sms_lag = _lag_seconds(shopify["sms_consent_updated_at"], m["modified_on"])
        linked.append(
            {
                "person.email": m["person.email"],
                "person.external_key": m["person.external_key"],
                "person.phone": phone_for_sms,
                "phone_valid": phone_ok,
                "manago_contact_id": m["manago_contact_id"],
                "manago_email_in": m["email_in"],
                "manago_sms_in": m["sms_in"],
                "optedOut": m["optedOut"],
                "optedOutPhone": m["optedOutPhone"],
                "manago_invalid": m["invalid"],
                "provenance_ok": m["provenance_ok"],
                "provenance_weak": m["provenance_weak"],
                "provenance_note": m["provenance_note"],
                "modified_on": m["modified_on"],
                "shopify_customer_id": shopify["shopify_customer_id"],
                "shopify_email_in": shopify["email_in"],
                "shopify_sms_in": shopify["sms_in"],
                "shopify_email_consent": shopify["email_marketing_consent"],
                "shopify_sms_consent": shopify["sms_marketing_consent"],
                "shopify_email_consent_updated_at": shopify["email_consent_updated_at"],
                "shopify_sms_consent_updated_at": shopify["sms_consent_updated_at"],
                "shopify_email_opt_in_level": shopify["email_opt_in_level"],
                "shopify_sms_opt_in_level": shopify["sms_opt_in_level"],
                "link_kind": link_kind,
                "email_quadrant": email_q,
                "sms_quadrant": sms_q,
                "email_propagation_lag_seconds": email_lag,
                "sms_propagation_lag_seconds": sms_lag,
            }
        )

    def _matrix(field: str) -> dict[str, int]:
        counts = {"in_in": 0, "in_out": 0, "out_in": 0, "out_out": 0, "unknown": 0}
        for row in linked:
            q = row.get(field)
            if q in counts:
                counts[q] += 1
            else:
                counts["unknown"] += 1
        return counts

    email_matrix = _matrix("email_quadrant")
    sms_matrix = _matrix("sms_quadrant")

    # CC-03 cohorts on Manago opt-ins (email).
    opted_in_manago = [m for m in manago_rows if m.get("email_in") is True]
    with_prov = [m for m in opted_in_manago if m.get("provenance_ok")]
    weak_prov = [m for m in opted_in_manago if m.get("provenance_weak")]
    no_prov = [m for m in opted_in_manago if not m.get("provenance_ok")]

    # Shopify consent_updated_at cross-ref (Excel CC-03 c9).
    shopify_evidence_cohort: list[dict[str, Any]] = []
    manago_only_unevidenced: list[dict[str, Any]] = []
    for m in no_prov:
        match = next(
            (
                r
                for r in linked
                if r.get("manago_contact_id") == m["manago_contact_id"]
            ),
            None,
        )
        shopify_ts = (match or {}).get("shopify_email_consent_updated_at")
        shopify_level = (match or {}).get("shopify_email_opt_in_level")
        shopify_in = (match or {}).get("shopify_email_in")
        # Evidence on Shopify side: timestamp preferred; else subscribed + opt_in_level.
        holds_evidence = bool(shopify_ts) or (
            shopify_in is True and bool(shopify_level)
        )
        entry = {
            "person.email": m.get("person.email"),
            "manago_contact_id": m.get("manago_contact_id"),
            "provenance_note": m.get("provenance_note"),
            "shopify_customer_id": (match or {}).get("shopify_customer_id"),
            "shopify_email_consent_updated_at": shopify_ts,
            "shopify_email_opt_in_level": shopify_level,
            "shopify_holds_evidence": holds_evidence,
        }
        if holds_evidence:
            shopify_evidence_cohort.append(entry)
        else:
            manago_only_unevidenced.append(entry)

    # CC-05 propagation gaps (state-level; lag when timestamps present).
    email_optout_not_in_shopify = [
        r
        for r in linked
        if r.get("email_quadrant") == "in_out"  # Shopify still in, Manago out
    ]
    email_optout_not_in_manago = [
        r
        for r in linked
        if r.get("email_quadrant") == "out_in"  # Shopify out, Manago still in
    ]
    sms_optout_not_in_shopify = [
        r for r in linked if r.get("sms_quadrant") == "in_out"
    ]
    sms_optout_not_in_manago = [
        r for r in linked if r.get("sms_quadrant") == "out_in"
    ]

    gap_rows = (
        email_optout_not_in_shopify
        + email_optout_not_in_manago
        + sms_optout_not_in_shopify
        + sms_optout_not_in_manago
    )
    lag_values: list[float] = []
    for r in gap_rows:
        for key in ("email_propagation_lag_seconds", "sms_propagation_lag_seconds"):
            lag = r.get(key)
            if isinstance(lag, (int, float)):
                lag_values.append(float(lag))
    # Also measure lag on agreed opt-outs (both out) when both timestamps exist.
    for r in linked:
        if r.get("email_quadrant") == "out_out":
            lag = r.get("email_propagation_lag_seconds")
            if isinstance(lag, (int, float)):
                lag_values.append(float(lag))
        if r.get("sms_quadrant") == "out_out":
            lag = r.get("sms_propagation_lag_seconds")
            if isinstance(lag, (int, float)):
                lag_values.append(float(lag))

    lag_values_sorted = sorted(lag_values)
    lag_p95 = None
    if lag_values_sorted:
        idx = min(len(lag_values_sorted) - 1, int(0.95 * (len(lag_values_sorted) - 1)))
        lag_p95 = round(lag_values_sorted[idx], 1)

    # Suppression parity: Manago invalid / hard-bounce still subscribed in Shopify.
    invalid_still_in_shopify = [
        r
        for r in linked
        if r.get("manago_invalid") is True and r.get("shopify_email_in") is True
    ]
    invalid_count = sum(1 for r in linked if r.get("manago_invalid") is True)

    # CC-01 field coverage (opt_in_level + consent_updated_at).
    opt_in_level_counts: dict[str, int] = {}
    email_updated_at_present = 0
    for r in linked:
        level = str(r.get("shopify_email_opt_in_level") or "unknown")
        opt_in_level_counts[level] = opt_in_level_counts.get(level, 0) + 1
        if r.get("shopify_email_consent_updated_at"):
            email_updated_at_present += 1

    # CC-02 joint phone validity (consented SMS but unreachable).
    sms_consented = [
        r
        for r in linked
        if r.get("manago_sms_in") is True or r.get("shopify_sms_in") is True
    ]
    consented_unreachable = [r for r in sms_consented if not r.get("phone_valid")]

    def _sample(rows: list[dict[str, Any]], *, channel: str) -> list[dict[str, Any]]:
        out = []
        for r in rows[:CC_SAMPLE]:
            out.append(
                {
                    "person.email": r.get("person.email"),
                    "shopify_customer_id": r.get("shopify_customer_id"),
                    "manago_contact_id": r.get("manago_contact_id"),
                    "channel": channel,
                    "email_quadrant": r.get("email_quadrant"),
                    "sms_quadrant": r.get("sms_quadrant"),
                    "shopify_email_consent_updated_at": r.get(
                        "shopify_email_consent_updated_at"
                    ),
                    "shopify_email_opt_in_level": r.get("shopify_email_opt_in_level"),
                    "manago_modified_on": r.get("modified_on"),
                    "email_propagation_lag_seconds": r.get(
                        "email_propagation_lag_seconds"
                    ),
                    "sms_propagation_lag_seconds": r.get("sms_propagation_lag_seconds"),
                    "person.phone": r.get("person.phone"),
                    "phone_valid": r.get("phone_valid"),
                    "manago_invalid": r.get("manago_invalid"),
                }
            )
        return out

    return {
        "consent_rows": linked[:500],
        "consent": {
            "linked_identities": len(linked),
            "shopify_customers_with_consent": len(shopify_by_id),
            "manago_contacts_with_consent": len(manago_rows),
            "email_quadrant_matrix": email_matrix,
            "sms_quadrant_matrix": sms_matrix,
            "email_mismatches": email_matrix["in_out"] + email_matrix["out_in"],
            "sms_mismatches": sms_matrix["in_out"] + sms_matrix["out_in"],
            "compliance_exposure_email": email_matrix["out_in"],  # out Shopify / in Manago
            "compliance_exposure_sms": sms_matrix["out_in"],
            "lost_reach_email": email_matrix["in_out"],
            "lost_reach_sms": sms_matrix["in_out"],
            "opted_in_manago_email": len(opted_in_manago),
            "opted_in_with_provenance": len(with_prov),
            "opted_in_weak_or_missing_provenance": len(no_prov),
            "opted_in_weak_agent_like": len(weak_prov),
            "provenance_share": (
                round(len(with_prov) / max(len(opted_in_manago), 1), 4)
            ),
            # Excel CC-03: Shopify consent_updated_at cross-ref cohorts.
            "shopify_evidence_backfill_candidates": len(shopify_evidence_cohort),
            "manago_only_unevidenced_optins": len(manago_only_unevidenced),
            "email_field_coverage": {
                "opt_in_level_distribution": opt_in_level_counts,
                "consent_updated_at_present": email_updated_at_present,
                "consent_updated_at_share": round(
                    email_updated_at_present / max(len(linked), 1), 4
                ),
            },
            "sms_phone_reachability": {
                "sms_consented_linked": len(sms_consented),
                "consented_but_unreachable": len(consented_unreachable),
                "note": "CI-09-lite soft surface for CC-02; CI-09 not in MVP1 scored 42",
            },
            "propagation": {
                "email_manago_out_shopify_in": len(email_optout_not_in_shopify),
                "email_shopify_out_manago_in": len(email_optout_not_in_manago),
                "sms_manago_out_shopify_in": len(sms_optout_not_in_shopify),
                "sms_shopify_out_manago_in": len(sms_optout_not_in_manago),
            },
            "propagation_lag": {
                "measurable_pairs": len(lag_values_sorted),
                "median_seconds": (
                    round(median(lag_values_sorted), 1) if lag_values_sorted else None
                ),
                "p95_seconds": lag_p95,
                "max_seconds": (
                    round(max(lag_values_sorted), 1) if lag_values_sorted else None
                ),
            },
            "suppression": {
                "invalid_field_present": invalid_field_seen,
                "manago_invalid_linked": invalid_count,
                "invalid_still_subscribed_shopify": len(invalid_still_in_shopify),
                "note": (
                    "Manago contact.invalid used as hard-bounce/complaint proxy; "
                    "dedicated bounce/complaint event stream not ingested"
                ),
            },
            "mismatch_samples": {
                "email_in_out": _sample(email_optout_not_in_shopify, channel="email"),
                "email_out_in": _sample(email_optout_not_in_manago, channel="email"),
                "sms_in_out": _sample(sms_optout_not_in_shopify, channel="sms"),
                "sms_out_in": _sample(sms_optout_not_in_manago, channel="sms"),
                "weak_provenance": [
                    {
                        "person.email": m.get("person.email"),
                        "manago_contact_id": m.get("manago_contact_id"),
                        "provenance_note": m.get("provenance_note"),
                    }
                    for m in no_prov[:CC_SAMPLE]
                ],
                "shopify_holds_evidence": shopify_evidence_cohort[:CC_SAMPLE],
                "manago_only_unevidenced": manago_only_unevidenced[:CC_SAMPLE],
                "consented_unreachable_sms": _sample(
                    consented_unreachable, channel="sms"
                ),
                "invalid_still_in_shopify": _sample(
                    invalid_still_in_shopify, channel="email"
                ),
            },
            # True when Manago exposes invalid (or we later ingest bounce events).
            "hard_bounce_complaint_available": invalid_field_seen,
            "raw_enrichment": {
                "shopify_customers_from_raw": shopify_from_raw,
                "manago_contacts_from_raw": manago_from_raw,
                "consent_fields_present": shopify_from_raw and manago_from_raw,
            },
        },
    }
