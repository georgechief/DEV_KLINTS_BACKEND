"""Manago API HTTP client for connector import."""

from __future__ import annotations

# KNOWN LIMITATION (Excel PT-01 / PT-03 — flag for ops / George):
# Manago public API exposes catalogList (API v3 key) + product upsert, but no
# product-list endpoint. Full Manago catalog product entries need connector
# config ``api_v3_key`` and/or ``product_feed_url`` (XML feed). Without them,
# DCS correctly returns UNKNOWN + MISSING_INPUT — check code is complete.
# BR-01 margin needs ERP in scope; otherwise NOT_CONNECTED.

import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib.parse import urljoin

from django.utils import timezone

from tenants.manago import build_auth_payload, list_users_by_client, resolve_manago_api_base_url

_PAGE_SIZE = 1000
_LIST_BY_ID_BATCH_SIZE = 50
_MAX_MODIFIED_WINDOW_DAYS = 30
_TRANSACTION_EVENT_TYPES = frozenset({"PURCHASE", "TRANSACTION"})
_WORKFLOW_STATS_CAP = 25
_MANAGO_V3_BASE = "https://api.manago.ai"
# api.manago.ai is behind Cloudflare; Python urllib's default User-Agent is blocked (CF 1010).
_MANAGO_V3_USER_AGENT = "Klints-Backend/1.0 (Manago API v3; connector-import)"


def _manago_v3_url(path: str) -> str:
    return f"{_MANAGO_V3_BASE}/v3/{path.lstrip('/')}"


def _manago_v3_headers(
    *,
    api_v3_key: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Headers for all Manago API v3 calls (API-KEY auth + Cloudflare-safe UA)."""
    headers = {
        "API-KEY": api_v3_key.strip(),
        "Accept": "application/json",
        "User-Agent": _MANAGO_V3_USER_AGENT,
    }
    if extra:
        headers.update(extra)
    return headers


class ManagoClientError(Exception):
    """Raised when a Manago API request fails."""


@dataclass(frozen=True)
class FetchWindow:
    window_start: datetime
    window_end: datetime


class ManagoClient:
    """HTTP-only Manago connector client."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.last_rate_budget: dict[str, Any] | None = None

    def fetch(
        self,
        window: FetchWindow,
        *,
        timeout: float = 30.0,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Fetch raw Manago contacts, transactions, and events for the given window.

        Returns platform payloads only (PRD §6 step 7).
        Tracks request samples into ``last_rate_budget`` for FD-04.
        """
        from dataruns.dcs.rate_budget import build_manago_rate_budget

        endpoint, client_id, api_secret = _resolve_credentials(self._config)
        counter = {"sampled": 0, "ok": 0, "hit_rate_limit": False}
        try:
            owner = _resolve_owner(
                endpoint=endpoint,
                client_id=client_id,
                api_secret=api_secret,
                timeout=timeout,
                request_counter=counter,
                config=self._config,
            )
            contacts = _fetch_contacts(
                endpoint=endpoint,
                client_id=client_id,
                api_secret=api_secret,
                owner=owner,
                modified_from=window.window_start,
                modified_to=window.window_end,
                timeout=timeout,
                request_counter=counter,
            )
            transactions = _extract_external_events(
                contacts,
                window_start=window.window_start,
                window_end=window.window_end,
                transactions=True,
            )
            events = _extract_external_events(
                contacts,
                window_start=window.window_start,
                window_end=window.window_end,
                transactions=False,
            )
            # Batch 4c Excel surfaces (best-effort; missing key/feed → empty + note).
            product_catalogs, catalog_note = _fetch_product_catalogs_v3(
                config=self._config,
                timeout=timeout,
                request_counter=counter,
            )
            products, products_note = _fetch_catalog_products(
                config=self._config,
                timeout=timeout,
            )
            workflows, workflow_note = _fetch_workflows(
                endpoint=endpoint,
                client_id=client_id,
                api_secret=api_secret,
                timeout=timeout,
                request_counter=counter,
            )
            workflow_stats = _fetch_workflow_stats(
                endpoint=endpoint,
                client_id=client_id,
                api_secret=api_secret,
                workflows=workflows,
                timeout=timeout,
                request_counter=counter,
            )
            tags, tags_note = _fetch_contact_tags(
                endpoint=endpoint,
                client_id=client_id,
                api_secret=api_secret,
                owner=owner,
                timeout=timeout,
                request_counter=counter,
            )
            email_stats, email_stats_note = _fetch_email_global_stats(
                endpoint=endpoint,
                client_id=client_id,
                api_secret=api_secret,
                owner=owner,
                window_start=window.window_start,
                window_end=window.window_end,
                timeout=timeout,
                request_counter=counter,
            )
        except ManagoClientError as exc:
            message = str(exc)
            if "429" in message or "rate limit" in message.lower():
                counter["hit_rate_limit"] = True
            self.last_rate_budget = build_manago_rate_budget(
                requests_sampled=counter["sampled"],
                requests_ok=counter["ok"],
                hit_rate_limit=counter["hit_rate_limit"],
                source="import",
            )
            raise

        self.last_rate_budget = build_manago_rate_budget(
            requests_sampled=counter["sampled"],
            requests_ok=counter["ok"],
            hit_rate_limit=counter["hit_rate_limit"],
            source="import",
        )
        return {
            "contacts": contacts,
            "transactions": transactions,
            "events": events,
            "product_catalogs": product_catalogs,
            "products": products,
            "workflows": workflows,
            "workflow_stats": workflow_stats,
            "tags": tags,
            "email_stats": email_stats,
            "catalog_fetch_note": catalog_note,
            "products_fetch_note": products_note,
            "workflows_fetch_note": workflow_note,
            "tags_fetch_note": tags_note,
            "email_stats_fetch_note": email_stats_note,
        }


def _resolve_credentials(config: dict[str, Any]) -> tuple[str, str, str]:
    base_url = resolve_manago_api_base_url(config)

    workspace_id = config.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ManagoClientError("Manago connector is missing workspace_id.")

    api_key = config.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise ManagoClientError("Manago connector is missing api_key.")

    return base_url, workspace_id.strip(), api_key


def _resolve_owner(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    timeout: float,
    request_counter: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    """Resolve Manago contact owner email.

    Prefer connector ``owner`` / ``owner_email`` / topology primary when set,
    so multi-user clients do not silently ingest the first listByClient user.
    """
    preferred = _preferred_owner_from_config(config)
    if request_counter is not None:
        request_counter["sampled"] = int(request_counter.get("sampled") or 0) + 1
    try:
        data = list_users_by_client(
            client_id=client_id,
            api_secret=api_secret,
            endpoint=endpoint,
            timeout=timeout,
        )
    except urllib.error.HTTPError as exc:
        if request_counter is not None and exc.code == 429:
            request_counter["hit_rate_limit"] = True
        detail = _http_error_detail(exc)
        raise ManagoClientError(
            f"Manago returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ManagoClientError(f"Could not reach Manago: {reason}") from exc
    except TimeoutError as exc:
        raise ManagoClientError("Manago request timed out.") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ManagoClientError(f"Invalid Manago response: {exc}") from exc

    if request_counter is not None:
        request_counter["ok"] = int(request_counter.get("ok") or 0) + 1

    users: list[str] = []
    raw_users = data.get("users")
    if isinstance(raw_users, list):
        for user in raw_users:
            if isinstance(user, str) and user.strip():
                users.append(user.strip())
            elif isinstance(user, dict):
                email = user.get("email") or user.get("owner") or user.get("login")
                if isinstance(email, str) and email.strip():
                    users.append(email.strip())

    if preferred:
        if not users or any(u.lower() == preferred.lower() for u in users):
            return preferred
        # Configured owner not in listByClient — still honor explicit config.
        return preferred

    if users:
        return users[0]

    raise ManagoClientError("Could not resolve Manago contact owner.")


def _preferred_owner_from_config(config: dict[str, Any] | None) -> str | None:
    if not isinstance(config, dict):
        return None
    for key in ("owner", "owner_email"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    topology = config.get("topology")
    if isinstance(topology, dict):
        accounts = topology.get("accounts")
        if isinstance(accounts, list):
            for row in accounts:
                if not isinstance(row, dict):
                    continue
                if row.get("in_scope") is False:
                    continue
                owner = row.get("owner")
                if isinstance(owner, str) and owner.strip():
                    return owner.strip()
    return None


def _fetch_contacts(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    modified_from: datetime,
    modified_to: datetime,
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    contact_ids = _list_modified_contact_ids(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
        modified_from=modified_from,
        modified_to=modified_to,
        timeout=timeout,
        request_counter=request_counter,
    )
    return _fetch_contacts_by_id(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
        contact_ids=contact_ids,
        timeout=timeout,
        request_counter=request_counter,
    )


def _list_modified_contact_ids(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    modified_from: datetime,
    modified_to: datetime,
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> list[str]:
    contact_ids: list[str] = []
    seen: set[str] = set()

    for chunk_start, chunk_end in _chunk_time_range(modified_from, modified_to):
        page = 1
        while True:
            data = _post_manago(
                endpoint=endpoint,
                path="api/contact/paginatedModifiedContacts",
                client_id=client_id,
                api_secret=api_secret,
                payload={
                    "owner": owner,
                    "from": _datetime_to_epoch_ms(chunk_start),
                    "to": _datetime_to_epoch_ms(chunk_end),
                    "page": page,
                    "size": _PAGE_SIZE,
                },
                timeout=timeout,
                request_counter=request_counter,
            )
            modified_contacts = data.get("modifiedContacts")
            if modified_contacts is None:
                raise ManagoClientError(
                    "Manago response did not include 'modifiedContacts'."
                )
            if not isinstance(modified_contacts, list):
                raise ManagoClientError(
                    "Manago modifiedContacts field was not a JSON array."
                )

            for item in modified_contacts:
                if not isinstance(item, dict):
                    continue
                contact_id = item.get("id") or item.get("contactId")
                if contact_id is None:
                    continue
                external_id = str(contact_id)
                if external_id not in seen:
                    seen.add(external_id)
                    contact_ids.append(external_id)

            if not data.get("hasMore"):
                break
            page += 1

    return contact_ids


def _fetch_contacts_by_id(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    contact_ids: list[str],
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []

    for offset in range(0, len(contact_ids), _LIST_BY_ID_BATCH_SIZE):
        batch = contact_ids[offset : offset + _LIST_BY_ID_BATCH_SIZE]
        if not batch:
            continue
        data = _post_manago(
            endpoint=endpoint,
            path="api/contact/listById",
            client_id=client_id,
            api_secret=api_secret,
            payload={
                "owner": owner,
                "contactId": batch,
            },
            timeout=timeout,
            request_counter=request_counter,
        )
        page_contacts = data.get("contacts")
        if page_contacts is None:
            raise ManagoClientError(
                "Manago response did not include 'contacts'."
            )
        if not isinstance(page_contacts, list):
            raise ManagoClientError("Manago contacts field was not a JSON array.")
        contacts.extend(
            _normalize_contact_record(item)
            for item in page_contacts
            if isinstance(item, dict)
        )

    return contacts


def _normalize_contact_record(contact: dict[str, Any]) -> dict[str, Any]:
    """Expose contactId for map.json when the API returns id only."""
    normalized = dict(contact)
    if not normalized.get("contactId") and normalized.get("id") is not None:
        normalized["contactId"] = normalized["id"]
    return normalized


def _normalize_event_record(
    event: dict[str, Any],
    *,
    contact_id: Any,
    contact_email: str,
) -> dict[str, Any]:
    """Add map.json aliases while preserving original Manago event fields."""
    normalized = {
        **event,
        "contactId": contact_id,
        "contactEmail": contact_email,
    }
    if not normalized.get("transactionId") and normalized.get("externalId") is not None:
        normalized["transactionId"] = normalized["externalId"]
    if not normalized.get("email") and contact_email:
        normalized["email"] = contact_email
    return normalized


def _extract_external_events(
    contacts: list[dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
    transactions: bool,
) -> list[dict[str, Any]]:
    start_ms = _datetime_to_epoch_ms(window_start)
    end_ms = _datetime_to_epoch_ms(window_end)
    collected: list[dict[str, Any]] = []

    for contact in contacts:
        contact_id = contact.get("id") or contact.get("contactId")
        contact_email = contact.get("email") or ""
        for event in contact.get("contactExtEvents") or []:
            if not isinstance(event, dict):
                continue
            event_date = event.get("date")
            if not isinstance(event_date, (int, float)):
                continue
            if event_date < start_ms or event_date > end_ms:
                continue
            event_type = str(event.get("contactExtEventType") or "").upper()
            is_transaction = event_type in _TRANSACTION_EVENT_TYPES
            if transactions and not is_transaction:
                continue
            if not transactions and is_transaction:
                continue
            collected.append(
                _normalize_event_record(
                    event,
                    contact_id=contact_id,
                    contact_email=contact_email,
                )
            )

    return collected


def _post_manago(
    *,
    endpoint: str,
    path: str,
    client_id: str,
    api_secret: str,
    payload: dict[str, Any],
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = urljoin(f"{endpoint}/", path.lstrip("/"))
    body = json.dumps(
        {
            **build_auth_payload(client_id=client_id, api_secret=api_secret),
            **payload,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json",
        },
    )
    if request_counter is not None:
        request_counter["sampled"] = int(request_counter.get("sampled") or 0) + 1
    try:
        data = _read_json(request, timeout=timeout)
    except ManagoClientError as exc:
        if request_counter is not None and (
            "429" in str(exc) or "rate limit" in str(exc).lower()
        ):
            request_counter["hit_rate_limit"] = True
        raise
    if request_counter is not None:
        request_counter["ok"] = int(request_counter.get("ok") or 0) + 1
    return data


def _read_json(
    request: urllib.request.Request,
    *,
    timeout: float,
) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc)
        raise ManagoClientError(
            f"Manago returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ManagoClientError(f"Could not reach Manago: {reason}") from exc
    except TimeoutError as exc:
        raise ManagoClientError("Manago request timed out.") from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ManagoClientError("Manago returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ManagoClientError("Manago response was not a JSON object.")
    if data.get("success") is not True:
        raise ManagoClientError(_manago_error_message(data))
    return data


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            return _manago_error_message(data)
    except Exception:  # noqa: BLE001
        pass
    return exc.reason or "no response body"


def _manago_error_message(data: dict[str, Any]) -> str:
    message = data.get("message")
    if isinstance(message, list) and message:
        parts = [str(item) for item in message if item is not None]
        if parts:
            return "; ".join(parts)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "Manago request failed."


def _chunk_time_range(
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime]]:
    start = _as_utc(window_start)
    end = _as_utc(window_end)
    if end <= start:
        return [(start, end)]

    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    max_span = timedelta(days=_MAX_MODIFIED_WINDOW_DAYS)
    while cursor < end:
        chunk_end = min(cursor + max_span, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def _datetime_to_epoch_ms(value: datetime) -> int:
    return int(_as_utc(value).timestamp() * 1000)


def _as_utc(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc)


def _fetch_product_catalogs_v3(
    *,
    config: dict[str, Any],
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Excel PT-01/03: GET /v3/product/catalogList (requires API v3 key)."""
    api_v3_key = config.get("api_v3_key") or config.get("apiV3Key")
    if not isinstance(api_v3_key, str) or not api_v3_key.strip():
        return [], "MISSING_INPUT:api_v3_key"
    url = _manago_v3_url("product/catalogList")
    request = urllib.request.Request(
        url,
        method="GET",
        headers=_manago_v3_headers(api_v3_key=api_v3_key),
    )
    if request_counter is not None:
        request_counter["sampled"] = int(request_counter.get("sampled") or 0) + 1
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 — soft-fail for optional v3 surface
        return [], f"catalogList_failed:{exc}"
    if request_counter is not None:
        request_counter["ok"] = int(request_counter.get("ok") or 0) + 1
    if not isinstance(data, dict):
        return [], "catalogList_invalid_response"
    catalogs = data.get("catalogs") or []
    if not isinstance(catalogs, list):
        return [], "catalogList_invalid_catalogs"
    return [c for c in catalogs if isinstance(c, dict)], None


def _fetch_catalog_products(
    *,
    config: dict[str, Any],
    timeout: float,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Excel PT-01/03 Manago product entries.

    Public API has upsert but no product list. Excel also accepts XML Product Feed —
    load from connector ``product_feed_url`` when configured.
    """
    feed_url = config.get("product_feed_url") or config.get("xml_product_feed_url")
    if not isinstance(feed_url, str) or not feed_url.strip():
        return [], "MISSING_INPUT:product_feed_url"
    request = urllib.request.Request(
        feed_url.strip(),
        method="GET",
        headers={"Accept": "application/xml, text/xml, */*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        return _parse_product_feed_xml(raw), None
    except Exception as exc:  # noqa: BLE001
        return [], f"product_feed_failed:{exc}"


def _parse_product_feed_xml(raw: bytes) -> list[dict[str, Any]]:
    """Parse common Manago/SALESmanago XML product feed shapes into product dicts."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    products: list[dict[str, Any]] = []
    # Accept <product>, <item>, or rss/channel/item style nodes.
    candidates = list(root.iter())
    for node in candidates:
        tag = node.tag.split("}")[-1].lower() if isinstance(node.tag, str) else ""
        if tag not in {"product", "item"}:
            continue
        fields: dict[str, Any] = {}
        for child in list(node):
            ctag = child.tag.split("}")[-1] if isinstance(child.tag, str) else ""
            if not ctag:
                continue
            text = (child.text or "").strip()
            fields[ctag] = text
        # Also attributes on the product node.
        for k, v in node.attrib.items():
            fields.setdefault(k, v)
        product_id = (
            fields.get("productId")
            or fields.get("product_id")
            or fields.get("id")
            or fields.get("sku")
            or fields.get("g:id")
        )
        if not product_id:
            continue
        products.append(
            {
                "productId": str(product_id),
                "name": fields.get("name") or fields.get("title") or "",
                "sku": fields.get("sku") or "",
                "available": _xml_bool(fields.get("available")),
                "active": _xml_bool(fields.get("active"), default=True),
                "price": fields.get("price"),
                "margin": fields.get("margin") or fields.get("cost") or fields.get("costPrice"),
                "productUrl": fields.get("productUrl") or fields.get("url") or fields.get("link"),
                "mainCategory": fields.get("mainCategory") or fields.get("category"),
                "raw_fields": fields,
            }
        )
    return products


def _xml_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _fetch_workflows(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Excel ME-02: POST /api/workflow/list."""
    try:
        data = _post_manago(
            endpoint=endpoint,
            path="api/workflow/list",
            client_id=client_id,
            api_secret=api_secret,
            payload={},
            timeout=timeout,
            request_counter=request_counter,
        )
    except ManagoClientError as exc:
        return [], f"workflow_list_failed:{exc}"
    workflows = data.get("workflows") or []
    if not isinstance(workflows, list):
        return [], "workflow_list_invalid"
    return [w for w in workflows if isinstance(w, dict)], None


def _fetch_contact_tags(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Excel SP-08: POST /api/contact/tags → tag + numberOfTagged."""
    try:
        data = _post_manago(
            endpoint=endpoint,
            path="api/contact/tags",
            client_id=client_id,
            api_secret=api_secret,
            payload={
                "owner": owner,
                "showSystemTags": False,
            },
            timeout=timeout,
            request_counter=request_counter,
        )
    except ManagoClientError as exc:
        return [], f"contact_tags_failed:{exc}"
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        return [], "contact_tags_invalid"
    out: list[dict[str, Any]] = []
    for row in tags:
        if not isinstance(row, dict):
            continue
        name = row.get("tag")
        if not name:
            continue
        try:
            count = int(row.get("numberOfTagged") or 0)
        except (TypeError, ValueError):
            count = 0
        out.append({"tag": str(name), "numberOfTagged": count})
    return out, None


def _fetch_email_global_stats(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    window_start: datetime,
    window_end: datetime,
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Excel ME-09: POST /api/email/globalConversationStatistics (bounces).

    Manago docs use ``user`` (owner email), not ``owner`` — sending ``owner``
    yields ``User cannot be empty``.
    """
    try:
        data = _post_manago(
            endpoint=endpoint,
            path="api/email/globalConversationStatistics",
            client_id=client_id,
            api_secret=api_secret,
            payload={
                "user": owner,
                "from": _datetime_to_epoch_ms(window_start),
                "to": _datetime_to_epoch_ms(window_end),
            },
            timeout=timeout,
            request_counter=request_counter,
        )
    except ManagoClientError as exc:
        return {}, f"email_global_stats_failed:{exc}"

    def _int(key: str) -> int:
        try:
            return int(data.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    sent = _int("sent")
    soft = _int("softBounce")
    hard = _int("hardBounce")
    resigned = _int("resigned")
    bounce_total = soft + hard
    return {
        "from": data.get("from"),
        "to": data.get("to"),
        "sent": sent,
        "opened": _int("opened"),
        "clicked": _int("clicked"),
        "openedUnique": _int("openedUnique"),
        "clickedUnique": _int("clickedUnique"),
        "softBounce": soft,
        "hardBounce": hard,
        "resigned": resigned,
        "bounce_total": bounce_total,
        "bounce_rate": (bounce_total / sent) if sent > 0 else None,
        "hard_bounce_rate": (hard / sent) if sent > 0 else None,
        "soft_bounce_rate": (soft / sent) if sent > 0 else None,
    }, None


def _fetch_workflow_stats(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    workflows: list[dict[str, Any]],
    timeout: float,
    request_counter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Excel ME-02: revenueStats via /api/workflow/statistics (capped)."""
    out: list[dict[str, Any]] = []
    for workflow in workflows[:_WORKFLOW_STATS_CAP]:
        external_id = workflow.get("externalId") or workflow.get("id")
        if external_id is None:
            continue
        try:
            data = _post_manago(
                endpoint=endpoint,
                path="api/workflow/statistics",
                client_id=client_id,
                api_secret=api_secret,
                payload={
                    "externalId": external_id,
                    "period": "LAST_30_DAYS",
                },
                timeout=timeout,
                request_counter=request_counter,
            )
        except ManagoClientError:
            out.append(
                {
                    "externalId": external_id,
                    "name": workflow.get("name"),
                    "stats_ok": False,
                    "revenueStats": None,
                }
            )
            continue
        revenue = data.get("revenueStats")
        out.append(
            {
                "externalId": external_id,
                "name": data.get("name") or workflow.get("name"),
                "stats_ok": True,
                "launchesNumber": data.get("launchesNumber"),
                "revenueStats": revenue if isinstance(revenue, dict) else {},
            }
        )
    return out
