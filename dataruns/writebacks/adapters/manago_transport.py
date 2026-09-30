"""Manago HTTP transport for writeback execute / rollback."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dataruns.connectors.base import decrypt_connector_config, get_connector
from dataruns.connectors.manago_ai.client import (
    ManagoClientError,
    _manago_v3_headers,
    _manago_v3_url,
    _post_manago,
    _resolve_credentials,
    _resolve_owner,
)
from tenants.models import Company


@dataclass(frozen=True)
class ManagoWriteContext:
    endpoint: str
    client_id: str
    api_secret: str
    owner: str
    api_v3_key: str | None = None


def resolve_manago_write_context(company: Company) -> ManagoWriteContext:
    connector = get_connector(company=company, platform="manago_ai")
    config = decrypt_connector_config(connector.config)
    endpoint, client_id, api_secret = _resolve_credentials(config)
    owner = _resolve_owner(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        timeout=30.0,
        config=config,
    )
    api_v3_key = config.get("api_v3_key") or config.get("apiV3Key")
    if not isinstance(api_v3_key, str) or not api_v3_key.strip():
        api_v3_key = None
    else:
        api_v3_key = api_v3_key.strip()
    return ManagoWriteContext(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
        api_v3_key=api_v3_key,
    )


_CONTACT_IDENTITY_KEYS = frozenset(
    {
        "email",
        "contactId",
        "name",
        "phone",
        "fax",
        "company",
        "externalId",
        "address",
        "state",
    }
)
_UPSERT_ROOT_KEYS = frozenset(
    {
        "properties",
        "dictionaryProperties",
        "tags",
        "removeTags",
        "forceOptIn",
        "forceOptOut",
        "forcePhoneOptIn",
        "forcePhoneOptOut",
        "newEmail",
        "birthday",
        "province",
    }
)


def upsert_contacts(
    ctx: ManagoWriteContext,
    contacts: list[dict[str, Any]],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not contacts:
        raise ManagoClientError("upsert_contacts requires at least one contact")
    last: dict[str, Any] | None = None
    for raw in contacts:
        last = _post_manago(
            endpoint=ctx.endpoint,
            path="api/contact/upsert",
            client_id=ctx.client_id,
            api_secret=ctx.api_secret,
            payload=_upsert_request_payload(owner=ctx.owner, contact=raw),
            timeout=timeout,
        )
    assert last is not None
    return last


def _upsert_request_payload(*, owner: str, contact: dict[str, Any]) -> dict[str, Any]:
    """Manago ``api/contact/upsert`` takes singular ``contact`` plus root properties.

    Sending ``contacts: [...]`` makes Manago return ``No email specified``.
    """
    identity: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for key, value in contact.items():
        if str(key).startswith("_") or value is None or value == "":
            continue
        if key in _CONTACT_IDENTITY_KEYS:
            identity[key] = value
        elif key in _UPSERT_ROOT_KEYS:
            extras[key] = value
    if not identity.get("email") and not identity.get("contactId"):
        raise ManagoClientError("upsert requires email or contactId")
    payload: dict[str, Any] = {"owner": owner, "contact": identity}
    payload.update(extras)
    return payload


def add_contact_tag(
    ctx: ManagoWriteContext,
    *,
    email: str | None = None,
    contact_id: str | None = None,
    tag: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"owner": ctx.owner, "tag": tag}
    if email:
        payload["email"] = email
    if contact_id:
        payload["contactId"] = contact_id
    if not payload.get("email") and not payload.get("contactId"):
        raise ManagoClientError("add_contact_tag requires email or contactId")
    return _post_manago(
        endpoint=ctx.endpoint,
        path="api/contact/addTag",
        client_id=ctx.client_id,
        api_secret=ctx.api_secret,
        payload=payload,
        timeout=timeout,
    )


def remove_contact_tag(
    ctx: ManagoWriteContext,
    *,
    email: str | None = None,
    contact_id: str | None = None,
    tag: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"owner": ctx.owner, "tag": tag}
    if email:
        payload["email"] = email
    if contact_id:
        payload["contactId"] = contact_id
    if not payload.get("email") and not payload.get("contactId"):
        raise ManagoClientError("remove_contact_tag requires email or contactId")
    return _post_manago(
        endpoint=ctx.endpoint,
        path="api/contact/deleteTag",
        client_id=ctx.client_id,
        api_secret=ctx.api_secret,
        payload=payload,
        timeout=timeout,
    )


def batch_add_external_events(
    ctx: ManagoWriteContext,
    events: list[dict[str, Any]],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not events:
        raise ManagoClientError("batch_add_external_events requires events")
    return _post_manago(
        endpoint=ctx.endpoint,
        path="api/contact/batchAddContactExtEvent",
        client_id=ctx.client_id,
        api_secret=ctx.api_secret,
        payload={"owner": ctx.owner, "events": events},
        timeout=timeout,
    )


def update_contact_ext_event(
    ctx: ManagoWriteContext,
    event: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Update an existing external event (PRD-WB-14 / catalogue updateContactExtEvent).

    Full field resend — not upsert. Path confirmed as catalogue API name under
    ``api/contact/updateContactExtEvent`` (ingest sibling).
    """
    if not isinstance(event, dict) or not event:
        raise ManagoClientError("update_contact_ext_event requires event payload")
    if not str(event.get("externalId") or "").strip():
        raise ManagoClientError("update_contact_ext_event requires externalId")
    if not str(event.get("email") or event.get("contactId") or "").strip():
        raise ManagoClientError("update_contact_ext_event requires email or contactId")
    payload: dict[str, Any] = {"owner": ctx.owner, **event}
    return _post_manago(
        endpoint=ctx.endpoint,
        path="api/contact/updateContactExtEvent",
        client_id=ctx.client_id,
        api_secret=ctx.api_secret,
        payload=payload,
        timeout=timeout,
    )


def upsert_products(
    ctx: ManagoWriteContext,
    products: list[dict[str, Any]],
    *,
    catalog_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """PRD-WB-20 — Manago API v3 ``product/upsert`` (Excel T7 / PRODUCT.IMPORT).

    Requires connector ``api_v3_key``. Body shape refined by sandbox Loom.
    """
    if not products:
        raise ManagoClientError("upsert_products requires at least one product")
    if not ctx.api_v3_key:
        raise ManagoClientError("upsert_products requires api_v3_key on Manago connector")
    last: dict[str, Any] | None = None
    for product in products:
        if not isinstance(product, dict):
            raise ManagoClientError("upsert_products product must be an object")
        wire_product = {
            k: v
            for k, v in product.items()
            if v is not None and not str(k).startswith("_") and k != "proposed_action"
        }
        if not str(wire_product.get("productId") or "").strip():
            raise ManagoClientError("upsert_products requires productId")
        body: dict[str, Any] = {"product": wire_product}
        if catalog_id:
            body["catalogId"] = str(catalog_id).strip()
        last = _post_manago_v3_json(
            path="product/upsert",
            api_v3_key=ctx.api_v3_key,
            payload=body,
            timeout=timeout,
        )
    assert last is not None
    return last


def _post_manago_v3_json(
    *,
    path: str,
    api_v3_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    url = _manago_v3_url(path)
    body = json.dumps(payload).encode("utf-8")
    headers = _manago_v3_headers(
        api_v3_key=api_v3_key,
        extra={"Content-Type": "application/json;charset=UTF-8"},
    )
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = str(exc)
        raise ManagoClientError(f"manago_v3_http_{exc.code}:{detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ManagoClientError(f"manago_v3_request_failed:{exc}") from exc
    if not raw:
        return {"ok": True}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManagoClientError(f"manago_v3_invalid_json:{exc}") from exc
    return data if isinstance(data, dict) else {"ok": True, "raw": data}
