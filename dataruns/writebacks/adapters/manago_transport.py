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


def upsert_contacts(
    ctx: ManagoWriteContext,
    contacts: list[dict[str, Any]],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not contacts:
        raise ManagoClientError("upsert_contacts requires at least one contact")
    return _post_manago(
        endpoint=ctx.endpoint,
        path="api/contact/upsert",
        client_id=ctx.client_id,
        api_secret=ctx.api_secret,
        payload={"owner": ctx.owner, "contacts": contacts},
        timeout=timeout,
    )


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
