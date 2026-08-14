"""Excel sheet 02 DRIFT metrics join (PRD-DCS-05 — all 14).

Surfaces (sheet 02):
- CI-13: contact state + date clustering of blocked/resigned spikes
- CI-14: web identity match rate (identified vs anonymous VISIT / smclient)
- CI-15: modifiedOn >24mo + linked Manago↔Shopify updated_at freshness
- LE-08: open CART older than N days (exclude converted via PURCHASE/orders)
- LE-11: event ingestion lag / contact-not-exists 1h race loss proxy
- LE-13: rolling 7/28 PURCHASE+CART vs Shopify orders+abandoned checkouts
- PT-14: value shape — ×100 units, truncation, test-order exclusion
- SP-08: Manago /api/contact/tags populations (+ funnel proxy) + prior shift
- SP-12: property/tag decision-field freshness (stale-beyond-SLA share)
- CC-12: consent timestamp age + policy-version cohorts when present
- ME-08: baseline computability (history / AOV / repeat) Manago vs Shopify
- ME-09: deliverability (email globalConversationStatistics + invalid proxy)
- BR-02 / BR-12: inventory_levels + ERP heartbeat when surfaces present
  (executors return NOT_CONNECTED when erp_in_scope=false)

SP-08 prefers ingested tag catalog ``numberOfTagged``. All-contacts for ``tag:*``
uses contact-proxy only; ``funnel:*`` still uses contact recount. Prior SP-08
shift compares only when prior used the same population source.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.lifecycle_join import (
    _float_or_none,
    _latest_connector_raw,
    _PAID_FINANCIAL,
    _PURCHASE_TYPES,
)
from dataruns.models import DataRun
from tenants.models import Company

DRIFT_SAMPLE = 50
_CART_TYPES = frozenset({"CART", "CART_UPDATE", "ABANDONED_CART", "ADD_TO_CART"})
_VISIT_TYPES = frozenset({"VISIT", "PAGE_VIEW", "PAGEVIEW", "VIEW"})
_STALE_MONTHS = 24
_STALE_CART_DAYS = 14
# Excel CI-15: linked-pair freshness vs Shopify updated_at (SLA days).
_CI15_PAIR_LAG_DAYS = 30
# Excel SP-08: population shifted >50% since last recount.
_SP08_SHIFT_FAIL = 0.50
# Excel LE-11: contact-not-exists retry window (1h expiry).
_LE11_RACE_HOURS = 1
# Excel SP-12: decision-field stale SLA (days); BI cites ~14mo archaeology.
_SP12_SLA_DAYS = 90
_SP12_ARCHAEOLOGY_DAYS = 14 * 30
# Excel BR-02 example SLA 24h.
_BR02_SLA_HOURS = 24
# ME-08 baseline minimums (FD-05 window + volume for confidence bounds).
_ME08_MIN_HISTORY_DAYS = 30
_ME08_MIN_ORDERS = 20
_ME08_MIN_AOV_N = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
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
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _bucket_contact_state(contact: dict[str, Any]) -> str:
    """Map Manago fields → Excel CI-13 buckets (opt-in/out/resigned/blocked)."""
    state = str(contact.get("state") or "").strip().upper()
    if contact.get("invalid") is True or "BLOCK" in state:
        return "blocked"
    if "RESIGN" in state or state in {"DELETED", "REMOVED"}:
        return "resigned"
    if contact.get("optedOut") is True or "OPT_OUT" in state or state == "OPTED_OUT":
        return "opt_out"
    if contact.get("optedOut") is False or state in {
        "PROSPECT",
        "CUSTOMER",
        "ACTIVE",
        "OPT_IN",
        "SUBSCRIBED",
    }:
        return "opt_in"
    if state:
        return "other"
    return "unknown"


def _consent_meta(contact: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
    """Consent age + policy version from consents[] (Excel CC-12)."""
    best: datetime | None = None
    policy: str | None = None
    for item in contact.get("consents") or []:
        if not isinstance(item, dict):
            continue
        ts = _parse_ts(
            item.get("consentDate")
            or item.get("createdOn")
            or item.get("timestamp")
            or item.get("date")
        )
        if ts is not None and (best is None or ts > best):
            best = ts
        for key in (
            "policyVersion",
            "policy_version",
            "agreementVersion",
            "version",
            "consentVersion",
        ):
            if item.get(key) is not None and policy is None:
                policy = str(item.get(key)).strip() or None
    if best is None:
        best = _parse_ts(contact.get("modifiedOn") or contact.get("createdOn"))
    age = None
    if best is not None:
        age = max(int((as_of - best).total_seconds() // 86400), 0)
    return {"age_days": age, "policy_version": policy}


def _prior_drift_for_company(company: Company) -> dict[str, Any]:
    """Prior DCS run drift block for LE-13/SP-08 recurring compare (PRD-DCS-05)."""
    qs = (
        DataRun.objects.filter(
            metadata__kind=DCS_SCORE_KIND,
            metadata__company_id=str(company.id),
            status=DataRun.Status.SUCCEEDED,
        )
        .order_by("-created_at")[:5]
    )
    for row in qs:
        snap = row.run_snapshot if isinstance(row.run_snapshot, dict) else {}
        drift = snap.get("drift")
        if isinstance(drift, dict) and drift:
            return drift
        # Fallback: some older runs may only have metrics in metadata.
        meta = row.metadata if isinstance(row.metadata, dict) else {}
        bi = meta.get("drift")
        if isinstance(bi, dict) and bi:
            return bi
    return {}


def _iter_segment_keys(contact: dict[str, Any]) -> list[str]:
    """Tags + funnel names as segment population proxy when tag catalog absent."""
    keys: list[str] = []
    raw_tags = contact.get("contactTags") or contact.get("tags") or []
    if isinstance(raw_tags, dict):
        raw_tags = list(raw_tags.values())
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if isinstance(item, str):
                keys.append(f"tag:{item}")
            elif isinstance(item, dict):
                name = item.get("tag") or item.get("name") or item.get("label")
                if name:
                    keys.append(f"tag:{name}")
    funnels = contact.get("contactFunnels") or contact.get("funnels") or []
    if isinstance(funnels, dict):
        funnels = list(funnels.values())
    if isinstance(funnels, list):
        for item in funnels:
            if isinstance(item, str):
                keys.append(f"funnel:{item}")
            elif isinstance(item, dict):
                name = item.get("name") or item.get("funnel") or item.get("id")
                if name:
                    keys.append(f"funnel:{name}")
    return keys


def _iter_funnel_keys(contact: dict[str, Any]) -> list[str]:
    return [k for k in _iter_segment_keys(contact) if k.startswith("funnel:")]


def _contact_property_keys(contact: dict[str, Any]) -> list[str]:
    """Decision-field keys: tags + standard/dictionary properties (Excel SP-12)."""
    keys = list(_iter_segment_keys(contact))
    props = contact.get("properties") or contact.get("contactProperties") or {}
    if isinstance(props, dict):
        for name, val in props.items():
            if val is None or val == "":
                continue
            keys.append(f"prop:{name}")
    elif isinstance(props, list):
        for item in props:
            if isinstance(item, dict):
                name = item.get("name") or item.get("key") or item.get("property")
                if name:
                    keys.append(f"prop:{name}")
            elif isinstance(item, str) and item.strip():
                keys.append(f"prop:{item.strip()}")
    dict_props = contact.get("dictionaryProperties") or []
    if isinstance(dict_props, list):
        for item in dict_props:
            if isinstance(item, dict):
                name = item.get("name") or item.get("key")
                if name:
                    keys.append(f"dict:{name}")
    return keys


def _property_write_ts(contact: dict[str, Any], field_key: str) -> datetime | None:
    """Prefer dictionary DATE property values; else contact modifiedOn."""
    if field_key.startswith("dict:"):
        name = field_key[5:]
        for item in contact.get("dictionaryProperties") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or item.get("key") or "") != name:
                continue
            if str(item.get("type") or "").upper() == "DATE":
                ts = _parse_ts(item.get("value"))
                if ts is not None:
                    return ts
    return _parse_ts(contact.get("modifiedOn") or contact.get("createdOn"))


def _erp_heartbeat_surfaces(*, company: Company, as_of: datetime) -> dict[str, Any]:
    """Collect ERP sync domain ages from erp connector raw/config when present."""
    domain_ages: dict[str, float | None] = {}
    source = "missing"
    raw_present = False

    # Prefer ingested platform="erp" raw (works in unit tests + production).
    erp_raw = _latest_connector_raw(company=company, platform="erp")
    has_erp_signal = bool(
        erp_raw.get("sync_domains")
        or erp_raw.get("domains")
        or erp_raw.get("last_success_at")
        or erp_raw.get("last_sync_at")
        or erp_raw.get("synced_at")
    )
    if has_erp_signal:
        raw_present = True
        domains = erp_raw.get("sync_domains") or erp_raw.get("domains") or {}
        if isinstance(domains, dict) and domains:
            source = "erp_domains"
            for name, meta in domains.items():
                if isinstance(meta, dict):
                    ts = _parse_ts(
                        meta.get("last_success_at")
                        or meta.get("last_sync_at")
                        or meta.get("synced_at")
                    )
                else:
                    ts = _parse_ts(meta)
                domain_ages[str(name)] = (
                    (as_of - ts).total_seconds() / 3600.0 if ts is not None else None
                )
        for key in ("last_success_at", "last_sync_at", "synced_at"):
            ts = _parse_ts(erp_raw.get(key))
            if ts is not None:
                domain_ages.setdefault(
                    "default", (as_of - ts).total_seconds() / 3600.0
                )
                if source == "missing":
                    source = "erp_last_sync"

    # Optional: scan company connectors named/typed as ERP.
    try:
        from tenants.models import Connector

        connectors = list(Connector.objects.filter(company=company))
    except Exception:
        connectors = []

    erp_connectors = [
        c
        for c in connectors
        if str(c.name or "").lower() in {"erp", "netsuite", "sap", "dynamics"}
        or "erp" in str(c.name or "").lower()
        or str((c.config or {}).get("type") or "").lower() == "erp"
    ]
    for connector in erp_connectors:
        raw_present = True
        config = connector.config if isinstance(connector.config, dict) else {}
        raw = _latest_connector_raw(company=company, platform=str(connector.name))
        domains = (
            raw.get("sync_domains")
            or raw.get("domains")
            or config.get("sync_domains")
            or config.get("domains")
            or {}
        )
        if isinstance(domains, dict) and domains:
            source = "erp_domains"
            for name, meta in domains.items():
                if isinstance(meta, dict):
                    ts = _parse_ts(
                        meta.get("last_success_at")
                        or meta.get("last_sync_at")
                        or meta.get("synced_at")
                    )
                else:
                    ts = _parse_ts(meta)
                domain_ages[str(name)] = (
                    (as_of - ts).total_seconds() / 3600.0 if ts is not None else None
                )
        for key in ("last_success_at", "last_sync_at", "synced_at"):
            ts = _parse_ts(raw.get(key) or config.get(key))
            if ts is not None:
                domain_ages.setdefault(
                    "default", (as_of - ts).total_seconds() / 3600.0
                )
                if source == "missing":
                    source = "erp_last_sync"
        if not domain_ages and getattr(connector, "updated_at", None) is not None:
            ts = _parse_ts(connector.updated_at)
            if ts is not None:
                domain_ages["connector_updated_at"] = (
                    as_of - ts
                ).total_seconds() / 3600.0
                source = "connector_updated_at_proxy"

    return {
        "domain_ages": domain_ages,
        "source": source,
        "raw_present": raw_present,
    }


def _is_identified_visit(event: dict[str, Any]) -> bool:
    if event.get("contactId") or event.get("cid") or event.get("email"):
        return True
    if event.get("contactEmail"):
        return True
    return False


def build_drift_snapshot(*, company: Company) -> dict[str, Any]:
    as_of = _utcnow()
    manago_raw = _latest_connector_raw(company=company, platform="manago_ai")
    shopify_raw = _latest_connector_raw(company=company, platform="shopify")
    contacts = [c for c in (manago_raw.get("contacts") or []) if isinstance(c, dict)]
    transactions = [
        t for t in (manago_raw.get("transactions") or []) if isinstance(t, dict)
    ]
    events_blob = [e for e in (manago_raw.get("events") or []) if isinstance(e, dict)]
    orders = [o for o in (shopify_raw.get("orders") or []) if isinstance(o, dict)]
    customers = [
        c for c in (shopify_raw.get("customers") or []) if isinstance(c, dict)
    ]
    checkouts = [
        c
        for c in (
            shopify_raw.get("checkouts")
            or shopify_raw.get("abandoned_checkouts")
            or []
        )
        if isinstance(c, dict)
    ]
    prior_drift = _prior_drift_for_company(company)

    shopify_by_id: dict[str, dict[str, Any]] = {}
    for cust in customers:
        cid = cust.get("id")
        if cid is None:
            continue
        shopify_by_id[str(cid)] = cust

    # Paid non-test order ids + email|day conversion keys (LE-08 Shopify surface).
    shopify_order_ids: set[str] = set()
    shopify_order_email_days: set[str] = set()
    for order in orders:
        if order.get("test") is True:
            continue
        financial = str(order.get("financial_status") or "").lower()
        if financial and financial not in _PAID_FINANCIAL:
            continue
        oid = str(order.get("id") or "").strip()
        if oid:
            shopify_order_ids.add(oid)
        email = str(order.get("email") or "").strip().lower()
        ts = _parse_ts(order.get("created_at") or order.get("processed_at"))
        if email and ts is not None:
            shopify_order_email_days.add(f"{email}|{ts.date().isoformat()}")

    checkout_completed_ids: set[str] = set()
    checkout_completed_email_days: set[str] = set()
    for co in checkouts:
        cid = str(co.get("id") or "").strip()
        token = str(co.get("token") or "").strip()
        completed = bool(co.get("completed_at"))
        if completed:
            if cid:
                checkout_completed_ids.add(cid)
            if token:
                checkout_completed_ids.add(token)
            email = str(co.get("email") or "").strip().lower()
            ts = _parse_ts(co.get("completed_at") or co.get("updated_at") or co.get("created_at"))
            if email and ts is not None:
                checkout_completed_email_days.add(f"{email}|{ts.date().isoformat()}")

    # --- CI-13 state distribution + date clustering ---
    state_counts: Counter[str] = Counter()
    dead_by_day: Counter[str] = Counter()
    for contact in contacts:
        bucket = _bucket_contact_state(contact)
        state_counts[bucket] += 1
        if bucket in {"blocked", "resigned"}:
            ts = _parse_ts(contact.get("modifiedOn") or contact.get("createdOn"))
            if ts is not None:
                dead_by_day[ts.date().isoformat()] += 1
    n_contacts = len(contacts)
    dead_n = state_counts["blocked"] + state_counts["resigned"]
    dead_share = dead_n / max(n_contacts, 1)
    opt_out_share = state_counts["opt_out"] / max(n_contacts, 1)
    spike_day = None
    spike_count = 0
    spike_share_of_dead = 0.0
    if dead_by_day:
        spike_day, spike_count = dead_by_day.most_common(1)[0]
        spike_share_of_dead = spike_count / max(dead_n, 1)
    # Cluster spike: ≥50% of dead states on one calendar day (Excel date clustering).
    dead_date_cluster = bool(dead_n >= 3 and spike_share_of_dead >= 0.50)

    # --- CI-15 / CC-12 freshness ---
    stale_cutoff = as_of - timedelta(days=_STALE_MONTHS * 30)
    modified_ages: list[int] = []
    stale_modified = 0
    consent_ages: list[int] = []
    stale_consent = 0
    opted_in_n = 0
    policy_versions: Counter[str] = Counter()
    linked_pairs = 0
    pair_stale = 0
    pair_lag_days: list[int] = []

    for contact in contacts:
        mod = _parse_ts(contact.get("modifiedOn") or contact.get("createdOn"))
        if mod is not None:
            age = max(int((as_of - mod).total_seconds() // 86400), 0)
            modified_ages.append(age)
            if mod < stale_cutoff:
                stale_modified += 1

        # Linked-pair freshness vs Shopify customers.updated_at (Excel CI-15).
        ext = str(contact.get("externalId") or "").strip()
        shopify = shopify_by_id.get(ext) if ext else None
        if shopify is not None and mod is not None:
            s_upd = _parse_ts(shopify.get("updated_at"))
            if s_upd is not None:
                linked_pairs += 1
                lag = abs(int((mod - s_upd).total_seconds() // 86400))
                pair_lag_days.append(lag)
                if lag > _CI15_PAIR_LAG_DAYS:
                    pair_stale += 1

        if contact.get("optedOut") is False:
            opted_in_n += 1
            meta = _consent_meta(contact, as_of=as_of)
            cage = meta.get("age_days")
            if cage is not None:
                consent_ages.append(int(cage))
                if int(cage) > _STALE_MONTHS * 30:
                    stale_consent += 1
            pol = meta.get("policy_version")
            if pol:
                policy_versions[str(pol)] += 1

    stale_modified_share = stale_modified / max(len(modified_ages), 1)
    stale_consent_share = stale_consent / max(len(consent_ages), 1)
    pair_stale_share = pair_stale / max(linked_pairs, 1)

    # --- LE-08 carts ---
    # Prefer top-level raw.events (window-filtered extract). Nested contactExtEvents
    # are the same source — do not union both or carts double-count.
    cart_events: list[dict[str, Any]] = []
    email_by_contact: dict[str, str] = {
        str(c.get("contactId") or c.get("id") or ""): str(c.get("email") or "")
        .strip()
        .lower()
        for c in contacts
    }

    def _append_cart(
        *,
        contact_id: str,
        email: str,
        event: dict[str, Any],
        date_value: Any,
    ) -> None:
        et = str(
            event.get("contactExtEventType") or event.get("type") or ""
        ).upper()
        if et not in _CART_TYPES:
            return
        cart_events.append(
            {
                "contactId": contact_id,
                "email": email,
                "type": et,
                "date": date_value,
                "externalId": event.get("externalId"),
                "value": event.get("value"),
            }
        )

    if events_blob:
        for event in events_blob:
            mid = str(event.get("contactId") or "")
            _append_cart(
                contact_id=mid,
                email=str(
                    event.get("email") or email_by_contact.get(mid) or ""
                )
                .strip()
                .lower(),
                event=event,
                date_value=event.get("date") or event.get("eventDate"),
            )
    # Fall back to nested events only when the blob yielded no carts (blob may
    # contain only non-CART types while contacts still carry CART rows).
    if not cart_events:
        for contact in contacts:
            mid = str(contact.get("contactId") or contact.get("id") or "")
            for event in contact.get("contactExtEvents") or []:
                if not isinstance(event, dict):
                    continue
                _append_cart(
                    contact_id=mid,
                    email=email_by_contact.get(mid) or "",
                    event=event,
                    date_value=event.get("date"),
                )

    purchase_ext_ids = {
        str(e.get("externalId") or "").strip()
        for e in transactions
        if str(e.get("contactExtEventType") or "").upper() in _PURCHASE_TYPES
        and str(e.get("externalId") or "").strip()
    }
    cart_cutoff = as_of - timedelta(days=_STALE_CART_DAYS)
    open_stale = 0
    converted = 0
    for cart in cart_events:
        ext = str(cart.get("externalId") or "").strip()
        ts = _parse_ts(cart.get("date"))
        email = str(cart.get("email") or "").strip().lower()
        converted_hit = False
        if ext and (
            ext in purchase_ext_ids
            or ext in shopify_order_ids
            or ext in checkout_completed_ids
        ):
            converted_hit = True
        elif email and ts is not None:
            # Same-day order or completed checkout for contact email.
            day_key = f"{email}|{ts.date().isoformat()}"
            if (
                day_key in shopify_order_email_days
                or day_key in checkout_completed_email_days
            ):
                converted_hit = True
        if converted_hit:
            converted += 1
            continue
        if ts is not None and ts < cart_cutoff:
            open_stale += 1
    stale_cart_share = open_stale / max(len(cart_events), 1)

    # --- LE-13 volume drift ---
    # PURCHASE from transactions + CART once (cart_events already de-duped source).
    purchase_days: Counter[str] = Counter()
    for event in transactions:
        et = str(event.get("contactExtEventType") or "").upper()
        if et not in _PURCHASE_TYPES:
            continue
        ts = _parse_ts(event.get("date") or event.get("eventDate"))
        if ts is None:
            continue
        purchase_days[ts.date().isoformat()] += 1
    for cart in cart_events:
        ts = _parse_ts(cart.get("date"))
        if ts is None:
            continue
        purchase_days[ts.date().isoformat()] += 1

    shopify_order_days: Counter[str] = Counter()
    shopify_checkout_days: Counter[str] = Counter()
    shopify_values: list[float] = []
    for order in orders:
        if order.get("test") is True:
            continue
        financial = str(order.get("financial_status") or "").lower()
        if financial and financial not in _PAID_FINANCIAL:
            continue
        # Exclude cancelled/void from AOV shape (PT-14 test/cancel noise).
        if order.get("cancelled_at") or financial in {
            "voided",
            "cancelled",
            "canceled",
        }:
            continue
        ts = _parse_ts(order.get("created_at"))
        if ts is None:
            continue
        shopify_order_days[ts.date().isoformat()] += 1
        amount = _float_or_none(order.get("total_price"))
        if amount is not None and amount > 0:
            shopify_values.append(float(amount))
    # Excel LE-13: abandoned checkout volume. Skip completed_at — those become orders.
    for co in checkouts:
        if co.get("completed_at"):
            continue
        ts = _parse_ts(co.get("created_at") or co.get("updated_at"))
        if ts is None:
            continue
        shopify_checkout_days[ts.date().isoformat()] += 1
    shopify_days: Counter[str] = shopify_order_days + shopify_checkout_days

    day_7 = (as_of - timedelta(days=7)).date()
    day_28 = (as_of - timedelta(days=28)).date()
    manago_7 = sum(n for d, n in purchase_days.items() if d >= day_7.isoformat())
    manago_prior = sum(
        n
        for d, n in purchase_days.items()
        if day_28.isoformat() <= d < day_7.isoformat()
    )
    shopify_orders_7 = sum(
        n for d, n in shopify_order_days.items() if d >= day_7.isoformat()
    )
    shopify_checkouts_7 = sum(
        n for d, n in shopify_checkout_days.items() if d >= day_7.isoformat()
    )
    shopify_7 = sum(n for d, n in shopify_days.items() if d >= day_7.isoformat())
    shopify_prior = sum(
        n
        for d, n in shopify_days.items()
        if day_28.isoformat() <= d < day_7.isoformat()
    )

    def _rate_delta(a: float, b: float) -> float:
        return abs(a - b) / max(a, b, 1e-9)

    manago_self_delta = _rate_delta(manago_7 / 7.0, manago_prior / 21.0)
    cross_7_delta = (
        _rate_delta(float(manago_7), float(shopify_7)) if (manago_7 + shopify_7) else 0.0
    )
    # Prior-run cross delta when available (recurring LE-13).
    prior_cross = prior_drift.get("le13_cross_7d_delta")
    prior_cross_delta = None
    try:
        if prior_cross is not None:
            prior_cross_delta = abs(float(cross_7_delta) - float(prior_cross))
    except (TypeError, ValueError):
        prior_cross_delta = None

    # --- PT-14 value shape ---
    manago_values: list[float] = []
    for event in transactions:
        et = str(event.get("contactExtEventType") or "").upper()
        if et not in _PURCHASE_TYPES:
            continue
        # Skip obvious test markers on event description/location.
        blob = " ".join(
            str(event.get(k) or "")
            for k in ("description", "location", "products")
        ).lower()
        if "test order" in blob or "test_order" in blob:
            continue
        val = _float_or_none(event.get("value"))
        if val is not None and val > 0:
            manago_values.append(float(val))
    med_m = median(manago_values) if manago_values else 0.0
    med_s = median(shopify_values) if shopify_values else 0.0
    ratio = (med_m / med_s) if med_s > 0 else None
    unit_artifact = bool(ratio is not None and (ratio >= 50 or ratio <= 0.02))
    huge_manago = sum(1 for v in manago_values if v >= 10_000)
    huge_share = huge_manago / max(len(manago_values), 1)
    # Truncation heuristic: Manago all whole-currency while Shopify has cents variety.
    manago_whole = sum(1 for v in manago_values if abs(v - round(v)) < 1e-9)
    shopify_cents = sum(1 for v in shopify_values if abs(v - round(v)) >= 0.01)
    truncation_suspect = bool(
        len(manago_values) >= 5
        and len(shopify_values) >= 5
        and (manago_whole / len(manago_values)) >= 0.95
        and (shopify_cents / len(shopify_values)) >= 0.20
        and not unit_artifact
    )

    # --- SP-08 segment population: prefer API tag catalog, else contact proxy ---
    api_tags = [
        t for t in (manago_raw.get("tags") or []) if isinstance(t, dict) and t.get("tag")
    ]
    seg_counts: Counter[str] = Counter()
    if api_tags:
        for row in api_tags:
            name = f"tag:{row.get('tag')}"
            try:
                seg_counts[name] = int(row.get("numberOfTagged") or 0)
            except (TypeError, ValueError):
                seg_counts[name] = 0
    else:
        for contact in contacts:
            for key in _iter_segment_keys(contact):
                seg_counts[key] += 1
    # Funnel names remain contact-level only (no funnel-list API).
    if api_tags:
        for contact in contacts:
            for key in _iter_funnel_keys(contact):
                seg_counts[key] += 1

    # Contact-proxy counts are comparable to window n_contacts.
    # API tag numberOfTagged is workspace-wide — skip for tag:* keys.
    # Funnel keys are always contact-proxy, so still eligible when API tags exist.
    all_contacts_segs = [
        t
        for t, n in seg_counts.items()
        if n_contacts > 0
        and n >= n_contacts
        and (not api_tags or t.startswith("funnel:"))
    ]
    prior_pops = {
        str(row.get("tag") or row.get("segment") or ""): int(row.get("count") or 0)
        for row in (prior_drift.get("sp08_tag_populations_sample") or [])
        if isinstance(row, dict) and (row.get("tag") or row.get("segment"))
    }
    # Skip shift/zero-drop compare when prior populations used a different source
    # (contact-proxy vs API catalog) — counts are not comparable.
    prior_from_api = prior_drift.get("sp08_from_api_tags")
    shift_comparable = (
        not prior_pops
        or prior_from_api is None
        or bool(prior_from_api) == bool(api_tags)
    )
    zero_population = [
        name
        for name, prev_n in prior_pops.items()
        if prev_n > 0
        and seg_counts.get(name, 0) == 0
        and (shift_comparable or name.startswith("funnel:"))
    ]
    api_zero_tag_count = (
        sum(1 for n in seg_counts.values() if n == 0) if api_tags else 0
    )
    shifted: list[dict[str, Any]] = []
    if shift_comparable:
        for name, n in seg_counts.items():
            if name not in prior_pops:
                continue
            prev = prior_pops[name]
            if prev <= 0:
                continue
            delta = abs(n - prev) / max(prev, 1)
            if delta > _SP08_SHIFT_FAIL:
                shifted.append(
                    {
                        "segment": name,
                        "prev": prev,
                        "current": n,
                        "delta": round(delta, 4),
                    }
                )
    segment_shift_unavailable = not bool(prior_pops) or not shift_comparable

    # --- CI-14 web identity match rate (VISIT / smclient) ---
    visit_events: list[dict[str, Any]] = []
    for event in events_blob:
        et = str(event.get("contactExtEventType") or event.get("type") or "").upper()
        if et in _VISIT_TYPES:
            visit_events.append(event)
    if not visit_events:
        for contact in contacts:
            mid = str(contact.get("contactId") or contact.get("id") or "")
            for event in contact.get("contactExtEvents") or []:
                if not isinstance(event, dict):
                    continue
                et = str(event.get("contactExtEventType") or "").upper()
                if et not in _VISIT_TYPES:
                    continue
                visit_events.append({**event, "contactId": event.get("contactId") or mid})
    # recentActivity-style lists if ever stored on raw
    recent = manago_raw.get("recentActivities") or manago_raw.get("recentActivity") or {}
    if isinstance(recent, dict):
        for key in ("customers", "partners", "prospects", "anonymous", "allVisits"):
            for item in recent.get(key) or []:
                if isinstance(item, dict):
                    row = dict(item)
                    if key != "anonymous" and not _is_identified_visit(row):
                        row["contactId"] = row.get("contactId") or "identified"
                    if key == "anonymous":
                        row.pop("contactId", None)
                        row.pop("email", None)
                    visit_events.append(row)
    visit_total = len(visit_events)
    visit_identified = sum(1 for v in visit_events if _is_identified_visit(v))
    # Fallback proxy: monitored contacts share when no VISIT rows.
    monitored_n = sum(
        1
        for c in contacts
        if c.get("monitored") is True or str(c.get("state") or "").upper() == "MONITORED"
    )
    if visit_total > 0:
        identity_match_rate = visit_identified / visit_total
        ci14_source = "visit_events"
    elif n_contacts > 0 and monitored_n > 0:
        identity_match_rate = monitored_n / n_contacts
        ci14_source = "monitored_contacts_proxy"
    else:
        identity_match_rate = None
        ci14_source = "missing"

    # --- LE-11 event ingestion lag / 1h race loss ---
    contact_created: dict[str, datetime] = {}
    contact_email_created: dict[str, datetime] = {}
    for contact in contacts:
        mid = str(contact.get("contactId") or contact.get("id") or "")
        created = _parse_ts(contact.get("createdOn") or contact.get("created_at"))
        if mid and created is not None:
            contact_created[mid] = created
        email = str(contact.get("email") or "").strip().lower()
        if email and created is not None:
            contact_email_created[email] = created
    lag_hours: list[float] = []
    race_survivor = 0  # event.date before contact create by >0 (attached after create)
    race_drop_risk = 0  # event before create by >1h (Excel drop window)
    lifecycle_events = [
        e
        for e in transactions
        if str(e.get("contactExtEventType") or "").upper()
        in (_PURCHASE_TYPES | _CART_TYPES)
    ]
    for event in lifecycle_events:
        mid = str(event.get("contactId") or "")
        created = contact_created.get(mid)
        if created is None:
            email = str(event.get("email") or event.get("contactEmail") or "").strip().lower()
            created = contact_email_created.get(email) if email else None
        ts = _parse_ts(event.get("date") or event.get("eventDate"))
        if created is None or ts is None:
            continue
        lag_h = (created - ts).total_seconds() / 3600.0
        # Positive lag_h ⇒ contact created after event send (race).
        if lag_h > 0:
            lag_hours.append(lag_h)
            race_survivor += 1
            if lag_h > _LE11_RACE_HOURS:
                race_drop_risk += 1
        else:
            lag_hours.append(0.0)
    # Shopify new-customer orders without Manago purchase (likely 1h drop).
    manago_purchase_ext = {
        str(e.get("externalId") or "").strip()
        for e in transactions
        if str(e.get("contactExtEventType") or "").upper() in _PURCHASE_TYPES
        and str(e.get("externalId") or "").strip()
    }
    manago_purchase_email_days = set()
    for e in transactions:
        if str(e.get("contactExtEventType") or "").upper() not in _PURCHASE_TYPES:
            continue
        email = str(e.get("email") or e.get("contactEmail") or "").strip().lower()
        ts = _parse_ts(e.get("date") or e.get("eventDate"))
        if email and ts is not None:
            manago_purchase_email_days.add(f"{email}|{ts.date().isoformat()}")
    shopify_customer_created = {
        str(c.get("id")): _parse_ts(c.get("created_at"))
        for c in customers
        if c.get("id") is not None
    }
    race_loss_orders = 0
    race_matched_orders = 0
    race_loss_sample: list[dict[str, Any]] = []
    for order in orders:
        if order.get("test") is True:
            continue
        financial = str(order.get("financial_status") or "").lower()
        if financial and financial not in _PAID_FINANCIAL:
            continue
        oid = str(order.get("id") or "").strip()
        email = str(order.get("email") or "").strip().lower()
        ots = _parse_ts(order.get("created_at") or order.get("processed_at"))
        if ots is None:
            continue
        cust = order.get("customer") if isinstance(order.get("customer"), dict) else {}
        cust_id = cust.get("id") if cust else order.get("customer_id")
        cts = None
        if cust_id is not None:
            cts = shopify_customer_created.get(str(cust_id)) or _parse_ts(
                cust.get("created_at")
            )
        if cts is None:
            continue
        delta_h = (cts - ots).total_seconds() / 3600.0
        # New-customer race: customer created within ±1h of order (Excel 1h window).
        if abs(delta_h) > _LE11_RACE_HOURS:
            continue
        matched = bool(oid and oid in manago_purchase_ext)
        day_key = f"{email}|{ots.date().isoformat()}" if email else ""
        if day_key and day_key in manago_purchase_email_days:
            matched = True
        if matched:
            race_matched_orders += 1
            continue
        race_loss_orders += 1
        if len(race_loss_sample) < DRIFT_SAMPLE:
            race_loss_sample.append(
                {
                    "order_id": oid,
                    "email": email,
                    "customer_lag_hours": round(delta_h, 3),
                }
            )
    le11_events_n = len(lifecycle_events)
    le11_race_loss_share = race_loss_orders / max(
        race_loss_orders + race_matched_orders, 1
    )

    # --- SP-12 property freshness on decision fields ---
    field_last_write: dict[str, datetime] = {}
    for contact in contacts:
        for key in _contact_property_keys(contact):
            mod = _property_write_ts(contact, key)
            if mod is None:
                continue
            prev = field_last_write.get(key)
            if prev is None or mod > prev:
                field_last_write[key] = mod
    # Workflow condition inventory (when workflows expose condition/detail keys).
    workflow_decision_keys: set[str] = set()
    for workflow in manago_raw.get("workflows") or []:
        if not isinstance(workflow, dict):
            continue
        for blob_key in ("conditions", "filters", "details", "triggers"):
            blob = workflow.get(blob_key)
            if isinstance(blob, dict):
                for name in blob.keys():
                    workflow_decision_keys.add(f"wf:{name}")
            elif isinstance(blob, list):
                for item in blob:
                    if isinstance(item, dict):
                        name = (
                            item.get("name")
                            or item.get("property")
                            or item.get("detail")
                            or item.get("key")
                        )
                        if name:
                            workflow_decision_keys.add(f"wf:{name}")
                    elif isinstance(item, str) and item.strip():
                        workflow_decision_keys.add(f"wf:{item.strip()}")
    for key in workflow_decision_keys:
        # No write timestamp on workflow defs — mark present for coverage only.
        if key not in field_last_write:
            field_last_write[key] = as_of
    sp12_field_n = len(field_last_write)
    sp12_stale = 0
    sp12_archaeology = 0
    sp12_stale_sample: list[dict[str, Any]] = []
    sla_cut = as_of - timedelta(days=_SP12_SLA_DAYS)
    arch_cut = as_of - timedelta(days=_SP12_ARCHAEOLOGY_DAYS)
    for name, ts in field_last_write.items():
        if name.startswith("wf:"):
            # Workflow condition keys without write clocks are coverage-only.
            continue
        age_days = max(int((as_of - ts).total_seconds() // 86400), 0)
        if ts < sla_cut:
            sp12_stale += 1
            if len(sp12_stale_sample) < DRIFT_SAMPLE:
                sp12_stale_sample.append(
                    {"field": name, "age_days": age_days, "last_write": ts.isoformat()}
                )
        if ts < arch_cut:
            sp12_archaeology += 1
    scored_fields = sum(1 for k in field_last_write if not k.startswith("wf:"))
    sp12_stale_share = sp12_stale / max(scored_fields, 1)

    # --- ME-08 baseline computability ---
    order_dates: list[datetime] = []
    purchase_by_email: Counter[str] = Counter()
    for order in orders:
        if order.get("test") is True:
            continue
        financial = str(order.get("financial_status") or "").lower()
        if financial and financial not in _PAID_FINANCIAL:
            continue
        if order.get("cancelled_at"):
            continue
        ts = _parse_ts(order.get("created_at"))
        if ts is not None:
            order_dates.append(ts)
        email = str(order.get("email") or "").strip().lower()
        if email:
            purchase_by_email[email] += 1
    for event in transactions:
        if str(event.get("contactExtEventType") or "").upper() not in _PURCHASE_TYPES:
            continue
        ts = _parse_ts(event.get("date") or event.get("eventDate"))
        if ts is not None:
            order_dates.append(ts)
        email = str(event.get("email") or event.get("contactEmail") or "").strip().lower()
        mid = str(event.get("contactId") or "")
        key = email or mid
        if key:
            purchase_by_email[key] += 1
    if order_dates:
        span_days = max(int((max(order_dates) - min(order_dates)).total_seconds() // 86400), 0)
    else:
        span_days = 0
    paid_order_n = sum(
        1
        for o in orders
        if o.get("test") is not True
        and (
            not str(o.get("financial_status") or "").lower()
            or str(o.get("financial_status") or "").lower() in _PAID_FINANCIAL
        )
        and not o.get("cancelled_at")
    )
    manago_purchase_n = sum(
        1
        for e in transactions
        if str(e.get("contactExtEventType") or "").upper() in _PURCHASE_TYPES
    )
    repeat_buyers = sum(1 for _, n in purchase_by_email.items() if n >= 2)
    aov_n = len(shopify_values) + len(manago_values)
    me08_history_ok = span_days >= _ME08_MIN_HISTORY_DAYS
    me08_volume_ok = (paid_order_n + manago_purchase_n) >= _ME08_MIN_ORDERS
    me08_aov_ok = aov_n >= _ME08_MIN_AOV_N
    me08_repeat_ok = repeat_buyers >= 1
    me08_computable = me08_history_ok and me08_volume_ok and me08_aov_ok
    # Segment baselines (Excel ME-08 "AOV by segment"): top tags with ≥2 purchases.
    segment_baselines: list[dict[str, Any]] = []
    tag_values: dict[str, list[float]] = defaultdict(list)
    tag_buyers: dict[str, set[str]] = defaultdict(set)
    email_to_tags: dict[str, set[str]] = {}
    for contact in contacts:
        email = str(contact.get("email") or "").strip().lower()
        mid = str(contact.get("contactId") or contact.get("id") or "")
        keys = {k for k in _iter_segment_keys(contact) if k.startswith("tag:")}
        if email:
            email_to_tags[email] = keys
        if mid:
            email_to_tags[mid] = keys
    for event in transactions:
        if str(event.get("contactExtEventType") or "").upper() not in _PURCHASE_TYPES:
            continue
        val = _float_or_none(event.get("value"))
        email = str(event.get("email") or event.get("contactEmail") or "").strip().lower()
        mid = str(event.get("contactId") or "")
        buyer = email or mid
        tags = email_to_tags.get(email) or email_to_tags.get(mid) or set()
        for tag in tags:
            if val is not None and val > 0:
                tag_values[tag].append(float(val))
            if buyer:
                tag_buyers[tag].add(buyer)
    ranked = sorted(tag_values.items(), key=lambda kv: len(kv[1]), reverse=True)
    for tag, values in ranked[:20]:
        buyers = tag_buyers.get(tag) or set()
        if len(values) < 2:
            continue
        segment_baselines.append(
            {
                "segment": tag,
                "purchases": len(values),
                "buyers": len(buyers),
                "aov": round(sum(values) / len(values), 4),
                "repeat_ok": any(purchase_by_email.get(b, 0) >= 2 for b in buyers),
            }
        )
    me08_segment_baseline_n = len(segment_baselines)

    # --- ME-09 deliverability posture ---
    invalid_field_seen = False
    invalid_n = 0
    for contact in contacts:
        if "invalid" in contact:
            invalid_field_seen = True
        if contact.get("invalid") is True:
            invalid_n += 1
    invalid_share = invalid_n / max(n_contacts, 1)
    email_stats = manago_raw.get("email_stats") if isinstance(manago_raw.get("email_stats"), dict) else {}
    bounce_rate = None
    hard_bounce_rate = None
    email_sent = 0
    if email_stats:
        try:
            bounce_rate = (
                float(email_stats["bounce_rate"])
                if email_stats.get("bounce_rate") is not None
                else None
            )
        except (TypeError, ValueError):
            bounce_rate = None
        try:
            hard_bounce_rate = (
                float(email_stats["hard_bounce_rate"])
                if email_stats.get("hard_bounce_rate") is not None
                else None
            )
        except (TypeError, ValueError):
            hard_bounce_rate = None
        try:
            email_sent = int(email_stats.get("sent") or 0)
        except (TypeError, ValueError):
            email_sent = 0
    me09_dead_share = dead_share
    me09_stats_available = bool(email_stats) and email_sent > 0

    # --- BR-02 inventory freshness (prefer inventory_levels.updated_at) ---
    shopify_products = [
        p for p in (shopify_raw.get("products") or []) if isinstance(p, dict)
    ]
    manago_products = [
        p for p in (manago_raw.get("products") or []) if isinstance(p, dict)
    ]
    inventory_levels = [
        row
        for row in (shopify_raw.get("inventory_levels") or [])
        if isinstance(row, dict)
    ]
    shopify_inv_ages_h: list[float] = []
    br02_inventory_source = "missing"
    if inventory_levels:
        br02_inventory_source = "inventory_levels"
        for row in inventory_levels:
            ts = _parse_ts(row.get("updated_at"))
            if ts is None:
                continue
            shopify_inv_ages_h.append((as_of - ts).total_seconds() / 3600.0)
    if not shopify_inv_ages_h:
        br02_inventory_source = "product_variants" if shopify_products else "missing"
        for prod in shopify_products:
            for variant in prod.get("variants") or []:
                if not isinstance(variant, dict):
                    continue
                ts = _parse_ts(variant.get("updated_at") or prod.get("updated_at"))
                if ts is None:
                    continue
                shopify_inv_ages_h.append((as_of - ts).total_seconds() / 3600.0)
    manago_inv_ages_h: list[float] = []
    for prod in manago_products:
        ts = _parse_ts(
            prod.get("updatedOn")
            or prod.get("modifiedOn")
            or prod.get("updated_at")
            or prod.get("availableFrom")
        )
        if ts is None:
            continue
        manago_inv_ages_h.append((as_of - ts).total_seconds() / 3600.0)
    br02_shopify_stale = sum(1 for h in shopify_inv_ages_h if h > _BR02_SLA_HOURS)
    br02_manago_stale = sum(1 for h in manago_inv_ages_h if h > _BR02_SLA_HOURS)
    br02_shopify_stale_share = br02_shopify_stale / max(len(shopify_inv_ages_h), 1)
    br02_manago_stale_share = br02_manago_stale / max(len(manago_inv_ages_h), 1)

    # --- BR-12 ERP heartbeat ---
    erp_hb = _erp_heartbeat_surfaces(company=company, as_of=as_of)
    br12_domain_ages = erp_hb.get("domain_ages") or {}
    prior_br12 = prior_drift.get("br12_domain_ages_hours") or {}
    br12_stall = []
    if isinstance(prior_br12, dict):
        for name, age in br12_domain_ages.items():
            prev = prior_br12.get(name)
            try:
                if age is not None and prev is not None and float(age) > float(prev) + 24:
                    br12_stall.append(name)
            except (TypeError, ValueError):
                continue

    return {
        "drift": {
            "as_of": as_of.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "contacts_scanned": n_contacts,
            "ci13_state_distribution": dict(state_counts),
            "ci13_dead_share": round(dead_share, 4),
            "ci13_opt_out_share": round(opt_out_share, 4),
            "ci13_dead_date_cluster": dead_date_cluster,
            "ci13_spike_day": spike_day,
            "ci13_spike_count": spike_count,
            "ci13_spike_share_of_dead": round(spike_share_of_dead, 4),
            "ci14_visit_total": visit_total,
            "ci14_visit_identified": visit_identified,
            "ci14_identity_match_rate": (
                round(identity_match_rate, 4) if identity_match_rate is not None else None
            ),
            "ci14_monitored_contacts": monitored_n,
            "ci14_source": ci14_source,
            "ci15_stale_modified_count": stale_modified,
            "ci15_modified_with_ts": len(modified_ages),
            "ci15_stale_modified_share": round(stale_modified_share, 4),
            "ci15_stale_months": _STALE_MONTHS,
            "ci15_linked_pairs": linked_pairs,
            "ci15_pair_stale_count": pair_stale,
            "ci15_pair_stale_share": round(pair_stale_share, 4),
            "ci15_pair_lag_days_median": (
                round(median(pair_lag_days), 2) if pair_lag_days else None
            ),
            "ci15_pair_lag_sla_days": _CI15_PAIR_LAG_DAYS,
            "le08_cart_events": len(cart_events),
            "le08_converted_carts": converted,
            "le08_open_stale_carts": open_stale,
            "le08_stale_cart_share": round(stale_cart_share, 4),
            "le08_stale_days": _STALE_CART_DAYS,
            "le08_checkouts_present": bool(checkouts),
            "le11_lifecycle_events": le11_events_n,
            "le11_race_survivor_events": race_survivor,
            "le11_race_drop_risk_events": race_drop_risk,
            "le11_lag_hours_median": (
                round(median(lag_hours), 4) if lag_hours else None
            ),
            "le11_race_loss_orders": race_loss_orders,
            "le11_race_loss_share": round(le11_race_loss_share, 4),
            "le11_race_loss_sample": race_loss_sample,
            "le11_race_hours": _LE11_RACE_HOURS,
            "le13_manago_7d": manago_7,
            "le13_manago_prior_21d": manago_prior,
            "le13_shopify_7d": shopify_7,
            "le13_shopify_orders_7d": shopify_orders_7,
            "le13_shopify_checkouts_7d": shopify_checkouts_7,
            "le13_shopify_prior_21d": shopify_prior,
            "le13_manago_self_delta": round(manago_self_delta, 4),
            "le13_cross_7d_delta": round(cross_7_delta, 4),
            "le13_prior_cross_delta": (
                round(prior_cross_delta, 4) if prior_cross_delta is not None else None
            ),
            "pt14_manago_values_n": len(manago_values),
            "pt14_shopify_values_n": len(shopify_values),
            "pt14_median_manago": round(med_m, 4),
            "pt14_median_shopify": round(med_s, 4),
            "pt14_median_ratio": round(ratio, 4) if ratio is not None else None,
            "pt14_unit_artifact": unit_artifact,
            "pt14_huge_value_share": round(huge_share, 4),
            "pt14_truncation_suspect": truncation_suspect,
            "sp08_tag_count": len(seg_counts),
            "sp08_from_api_tags": bool(api_tags),
            "sp08_api_zero_tag_count": api_zero_tag_count,
            "sp08_zero_population": len(zero_population),
            "sp08_zero_population_sample": zero_population[:DRIFT_SAMPLE],
            "sp08_all_contacts_tags": all_contacts_segs[:DRIFT_SAMPLE],
            "sp08_all_contacts_tag_count": len(all_contacts_segs),
            "sp08_tag_populations_sample": [
                {"tag": t, "segment": t, "count": n}
                for t, n in seg_counts.most_common(DRIFT_SAMPLE)
                if n > 0
            ],
            "sp08_shifted_sample": shifted[:DRIFT_SAMPLE],
            "sp08_shifted_count": len(shifted),
            "sp08_shift_unavailable": segment_shift_unavailable,
            "sp08_shift_threshold": _SP08_SHIFT_FAIL,
            "sp12_decision_field_count": sp12_field_n,
            "sp12_stale_field_count": sp12_stale,
            "sp12_stale_field_share": round(sp12_stale_share, 4),
            "sp12_archaeology_field_count": sp12_archaeology,
            "sp12_stale_sample": sp12_stale_sample,
            "sp12_sla_days": _SP12_SLA_DAYS,
            "sp12_archaeology_days": _SP12_ARCHAEOLOGY_DAYS,
            "cc12_opted_in": opted_in_n,
            "cc12_consent_with_ts": len(consent_ages),
            "cc12_stale_consent_count": stale_consent,
            "cc12_stale_consent_share": round(stale_consent_share, 4),
            "cc12_stale_months": _STALE_MONTHS,
            "cc12_policy_versions": dict(policy_versions),
            "cc12_policy_version_count": len(policy_versions),
            "me08_history_span_days": span_days,
            "me08_paid_order_n": paid_order_n,
            "me08_manago_purchase_n": manago_purchase_n,
            "me08_aov_values_n": aov_n,
            "me08_repeat_buyers": repeat_buyers,
            "me08_history_ok": me08_history_ok,
            "me08_volume_ok": me08_volume_ok,
            "me08_aov_ok": me08_aov_ok,
            "me08_repeat_ok": me08_repeat_ok,
            "me08_baseline_computable": me08_computable,
            "me08_min_history_days": _ME08_MIN_HISTORY_DAYS,
            "me08_min_orders": _ME08_MIN_ORDERS,
            "me08_segment_baseline_n": me08_segment_baseline_n,
            "me08_segment_baselines_sample": segment_baselines[:DRIFT_SAMPLE],
            "me09_invalid_field_seen": invalid_field_seen,
            "me09_invalid_count": invalid_n,
            "me09_invalid_share": round(invalid_share, 4),
            "me09_opt_out_share": round(opt_out_share, 4),
            "me09_dead_share": round(me09_dead_share, 4),
            "me09_stats_available": me09_stats_available,
            "me09_email_sent": email_sent,
            "me09_bounce_rate": (
                round(bounce_rate, 4) if bounce_rate is not None else None
            ),
            "me09_hard_bounce_rate": (
                round(hard_bounce_rate, 4) if hard_bounce_rate is not None else None
            ),
            "me09_email_stats_note": manago_raw.get("email_stats_fetch_note"),
            "br02_shopify_inventory_n": len(shopify_inv_ages_h),
            "br02_manago_inventory_n": len(manago_inv_ages_h),
            "br02_shopify_stale_share": round(br02_shopify_stale_share, 4),
            "br02_manago_stale_share": round(br02_manago_stale_share, 4),
            "br02_sla_hours": _BR02_SLA_HOURS,
            "br02_inventory_source": br02_inventory_source,
            "br02_inventory_levels_n": len(inventory_levels),
            "br02_shopify_median_age_hours": (
                round(median(shopify_inv_ages_h), 2) if shopify_inv_ages_h else None
            ),
            "br02_manago_median_age_hours": (
                round(median(manago_inv_ages_h), 2) if manago_inv_ages_h else None
            ),
            "br12_domain_ages_hours": br12_domain_ages,
            "br12_domain_count": len(br12_domain_ages),
            "br12_stalled_domains": br12_stall,
            "br12_erp_raw_present": bool(erp_hb.get("raw_present")),
            "br12_heartbeat_source": erp_hb.get("source"),
            "raw_enrichment": {
                "manago_contacts_from_raw": bool(contacts),
                "manago_transactions_from_raw": bool(transactions),
                "cart_events_present": bool(cart_events),
                "visit_events_present": bool(visit_events),
                "shopify_orders_from_raw": bool(orders),
                "shopify_customers_from_raw": bool(customers),
                "shopify_checkouts_present": bool(checkouts),
                "shopify_products_present": bool(shopify_products),
                "shopify_inventory_levels_present": bool(inventory_levels),
                "manago_products_present": bool(manago_products),
                "manago_tags_from_api": bool(api_tags),
                "manago_email_stats_present": bool(email_stats),
                "tags_or_funnels_present": bool(seg_counts),
                "decision_fields_present": bool(field_last_write),
                "prior_drift_present": bool(prior_drift),
                "erp_raw_present": bool(erp_hb.get("raw_present")),
            },
        }
    }
