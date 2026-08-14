"""Manago API list helpers for connector fetch (contacts, transactions, events)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib.parse import urljoin

from django.utils import timezone

from tenants.crypto import decrypt_api_key
from tenants.manago import (
    build_auth_payload,
    list_users_by_client,
    resolve_manago_api_base_url,
)

_PAGE_SIZE = 1000
_LIST_BY_ID_BATCH_SIZE = 50
_MAX_MODIFIED_WINDOW_DAYS = 30
_TRANSACTION_EVENT_TYPES = frozenset({"PURCHASE", "TRANSACTION"})


class ManagoFetchError(Exception):
    """Raised when a Manago API list request fails."""


def resolve_manago_credentials(config: dict[str, Any]) -> tuple[str, str, str]:
    """
    Extract endpoint, client id, and API secret from a Connector config.

    ``api_key`` is stored encrypted (see ``tenants.crypto.encrypt_config``).
    ``workspace_id`` is used as Manago ``clientId``.
    """
    endpoint = resolve_manago_api_base_url(config)

    client_id = config.get("workspace_id") or config.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise ManagoFetchError("Manago connector is missing workspace_id.")

    encrypted_key = config.get("api_key")
    if not isinstance(encrypted_key, str) or not encrypted_key:
        raise ManagoFetchError("Manago connector is missing api_key.")

    try:
        api_secret = decrypt_api_key(encrypted_key)
    except Exception as exc:  # noqa: BLE001 — Fernet InvalidToken, etc.
        raise ManagoFetchError("Could not decrypt Manago api_key.") from exc

    return endpoint, client_id.strip(), api_secret


def fetch_contacts(
    *,
    config: dict[str, Any],
    modified_from: datetime,
    modified_to: datetime,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """
    Fetch full Manago contacts modified within ``modified_from`` … ``modified_to``.

    Uses ``contact/paginatedModifiedContacts`` then ``contact/listById``.
    """
    endpoint, client_id, api_secret = resolve_manago_credentials(config)
    owner = _resolve_owner(
        config=config,
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        timeout=timeout,
    )
    contact_ids = _list_modified_contact_ids(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
        modified_from=modified_from,
        modified_to=modified_to,
        timeout=timeout,
    )
    return _fetch_contacts_by_id(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
        contact_ids=contact_ids,
        timeout=timeout,
    )


def fetch_transactions(
    *,
    config: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """
    Fetch Manago purchase/transaction external events in the date window.

    Derived from ``contactExtEvents`` on contacts modified in the window.
    """
    contacts = fetch_contacts(
        config=config,
        modified_from=window_start,
        modified_to=window_end,
        timeout=timeout,
    )
    return _extract_external_events(
        contacts,
        window_start=window_start,
        window_end=window_end,
        transactions=True,
    )


def fetch_events(
    *,
    config: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """
    Fetch Manago CRM external events (non-purchase) in the date window.

    Events are snapshot-only in v1. Derived from ``contactExtEvents``.
    """
    contacts = fetch_contacts(
        config=config,
        modified_from=window_start,
        modified_to=window_end,
        timeout=timeout,
    )
    return _extract_external_events(
        contacts,
        window_start=window_start,
        window_end=window_end,
        transactions=False,
    )


def fetch_recent_activity(
    *,
    config: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    timeout: float = 20.0,
    all_visits: bool = False,
) -> dict[str, Any]:
    """
    Fetch Manago ``api/contact/recentActivity`` for a date window.

    Returns the full JSON body (includes ``recentActivities`` / visit lists
    and ``monitoredContacts``). Used for FD-07 VISIT / smclient proxies.
    """
    endpoint, client_id, api_secret = resolve_manago_credentials(config)
    return _post_manago(
        endpoint=endpoint,
        path="api/contact/recentActivity",
        client_id=client_id,
        api_secret=api_secret,
        payload={
            "from": _datetime_to_epoch_ms(window_start),
            "to": _datetime_to_epoch_ms(window_end),
            "allVisits": bool(all_visits),
            "ipDetails": False,
        },
        timeout=timeout,
    )


def _resolve_owner(
    *,
    config: dict[str, Any],
    endpoint: str,
    client_id: str,
    api_secret: str,
    timeout: float,
) -> str:
    for key in ("owner", "owner_email"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    try:
        data = list_users_by_client(
            client_id=client_id,
            api_secret=api_secret,
            endpoint=endpoint,
            timeout=timeout,
        )
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc)
        raise ManagoFetchError(
            f"Manago returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ManagoFetchError(f"Could not reach Manago: {reason}") from exc
    except TimeoutError as exc:
        raise ManagoFetchError("Manago request timed out.") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ManagoFetchError(f"Invalid Manago response: {exc}") from exc

    users = data.get("users")
    if isinstance(users, list):
        for user in users:
            if isinstance(user, str) and user.strip():
                return user.strip()

    raise ManagoFetchError("Could not resolve Manago contact owner.")


def _list_modified_contact_ids(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    modified_from: datetime,
    modified_to: datetime,
    timeout: float,
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
            )
            modified_contacts = data.get("modifiedContacts")
            if modified_contacts is None:
                raise ManagoFetchError(
                    "Manago response did not include 'modifiedContacts'."
                )
            if not isinstance(modified_contacts, list):
                raise ManagoFetchError(
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
        )
        page_contacts = data.get("contacts")
        if page_contacts is None:
            raise ManagoFetchError(
                "Manago response did not include 'contacts'."
            )
        if not isinstance(page_contacts, list):
            raise ManagoFetchError("Manago contacts field was not a JSON array.")
        contacts.extend(item for item in page_contacts if isinstance(item, dict))

    return contacts


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
                {
                    **event,
                    "contactId": contact_id,
                    "contactEmail": contact_email,
                }
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
    return _read_json(request, timeout=timeout)


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
        raise ManagoFetchError(
            f"Manago returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ManagoFetchError(f"Could not reach Manago: {reason}") from exc
    except TimeoutError as exc:
        raise ManagoFetchError("Manago request timed out.") from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ManagoFetchError("Manago returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ManagoFetchError("Manago response was not a JSON object.")
    if data.get("success") is not True:
        raise ManagoFetchError(_manago_error_message(data))
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
