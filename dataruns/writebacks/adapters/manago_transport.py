"""Manago HTTP transport for writeback execute / rollback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dataruns.connectors.base import decrypt_connector_config, get_connector
from dataruns.connectors.manago_ai.client import (
    ManagoClientError,
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
    return ManagoWriteContext(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
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
