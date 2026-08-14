"""Manago write adapter — dry-run + gated execute (PRD-WB-01 §6.2)."""

from __future__ import annotations

import logging
from typing import Any

from dataruns.connectors.manago_ai.client import ManagoClientError
from dataruns.writebacks.adapters.manago_transport import (
    ManagoWriteContext,
    add_contact_tag,
    batch_add_external_events,
    remove_contact_tag,
    resolve_manago_write_context,
    upsert_contacts,
)
from dataruns.writebacks.rollback_snapshot import refresh_rollback_snapshot
from dataruns.writebacks.capabilities import capability_allows_execute
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company

logger = logging.getLogger(__name__)


class ManagoWriteAdapter:
    target = "manago"

    def dry_run(self, company: Company, intents: list[WriteIntent]) -> list[WriteIntent]:
        updated: list[WriteIntent] = []
        for intent in intents:
            if intent.status == "error":
                updated.append(intent)
                continue
            if intent.target_system not in ("manago", "manago_ai"):
                updated.append(intent)
                continue
            if not capability_allows_execute(intent.capability_id):
                intent.status = "error"
                intent.error_reason = "capability_not_confirmed"
                updated.append(intent)
                continue
            if not self._validate_payload(intent, execute=False):
                intent.status = "error"
                intent.error_reason = intent.error_reason or "invalid_payload"
                updated.append(intent)
                continue
            intent.status = "ready"
            updated.append(intent)
        return updated

    def execute(
        self,
        company: Company,
        intents: list[WriteIntent],
        *,
        approval_id: str | None,
        idempotency_key: str | None,
    ) -> list[WriteIntent]:
        del approval_id  # BL-017 consumes later
        try:
            ctx = resolve_manago_write_context(company)
        except Exception as exc:
            for intent in intents:
                intent.status = "error"
                intent.error_reason = f"manago_context_failed:{type(exc).__name__}"
                intent.execute_result = {"ok": False, "error": str(exc)}
            return intents

        updated: list[WriteIntent] = []
        for intent in intents:
            if intent.status != "ready":
                updated.append(intent)
                continue
            if not self._validate_payload(intent, execute=True):
                intent.status = "error"
                intent.error_reason = intent.error_reason or "invalid_payload"
                updated.append(intent)
                continue
            try:
                refresh_rollback_snapshot(company, intent)
                intent.execute_result = self._execute_intent(
                    ctx,
                    intent,
                    company=company,
                    idempotency_key=idempotency_key,
                )
                intent.status = "executed"
            except ManagoClientError as exc:
                logger.warning("Manago write failed op=%s: %s", intent.operation, exc)
                intent.status = "error"
                intent.error_reason = "manago_write_failed"
                intent.execute_result = {"ok": False, "error": str(exc)}
            except NotImplementedError:
                intent.status = "error"
                intent.error_reason = "adapter_not_implemented"
                intent.execute_result = {"ok": False, "error": "adapter_not_implemented"}
            updated.append(intent)
        return updated

    def rollback_intent(
        self,
        company: Company,
        intent: WriteIntent,
    ) -> dict[str, Any]:
        ctx = resolve_manago_write_context(company)
        payload = intent.payload or {}
        snapshot = intent.rollback_snapshot or {}

        if intent.op_kind == "detail_set":
            detail_key = next(iter((payload.get("properties") or {}).keys()), None)
            if not detail_key:
                raise ManagoClientError("rollback detail_set missing detail key")
            prior = snapshot.get(detail_key)
            contact = {
                "email": payload.get("email"),
                "contactId": payload.get("contactId"),
                "properties": {detail_key: prior},
            }
            contact = {k: v for k, v in contact.items() if v is not None}
            response = upsert_contacts(ctx, [contact])
            return {"ok": True, "response": _safe_response(response)}

        if intent.op_kind == "tag_add":
            tag = str(payload.get("tag") or "")
            if snapshot.get("present"):
                return {"ok": True, "skipped": "tag_already_present"}
            remove_contact_tag(
                ctx,
                email=str(payload.get("email") or "") or None,
                contact_id=str(payload.get("contactId") or "") or None,
                tag=tag,
            )
            return {"ok": True, "removed_tag": tag}

        if intent.op_kind == "contact_upsert":
            email = str(payload.get("email") or snapshot.get("email") or "")
            if snapshot.get("existed"):
                return {"ok": True, "skipped": "contact_pre_existed"}
            contact = {
                "email": email or None,
                "contactId": payload.get("contactId") or snapshot.get("contactId"),
                "properties": {"klints_backfill": None},
            }
            contact = {k: v for k, v in contact.items() if v is not None}
            response = upsert_contacts(ctx, [contact])
            return {"ok": True, "cleared_backfill_marker": True, "response": _safe_response(response)}

        raise NotImplementedError(f"rollback not supported for {intent.op_kind}")

    def _execute_intent(
        self,
        ctx: ManagoWriteContext,
        intent: WriteIntent,
        *,
        company: Company,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        payload = intent.payload or {}
        if intent.op_kind == "contact_upsert":
            contact = {
                k: v
                for k, v in payload.items()
                if v is not None and not str(k).startswith("_")
            }
            self._apply_klints_backfill_marker(intent, contact)
            response = upsert_contacts(ctx, [contact])
            return {
                "ok": True,
                "idempotency_key": idempotency_key,
                "response": _safe_response(response),
            }
        if intent.op_kind == "detail_set":
            contact = {
                "email": payload.get("email"),
                "contactId": payload.get("contactId"),
                "properties": payload.get("properties"),
            }
            contact = {k: v for k, v in contact.items() if v is not None}
            response = upsert_contacts(ctx, [contact])
            return {
                "ok": True,
                "idempotency_key": idempotency_key,
                "response": _safe_response(response),
            }
        if intent.op_kind == "tag_add":
            response = add_contact_tag(
                ctx,
                email=str(payload.get("email") or "") or None,
                contact_id=str(payload.get("contactId") or "") or None,
                tag=str(payload.get("tag") or ""),
            )
            return {
                "ok": True,
                "idempotency_key": idempotency_key,
                "response": _safe_response(response),
            }
        if intent.op_kind == "event_ingest":
            event = {
                k: v
                for k, v in payload.items()
                if v is not None and not str(k).startswith("_")
            }
            if not str(event.get("email") or event.get("contactId") or "").strip():
                raise ManagoClientError("event_ingest requires email or contactId")
            response = batch_add_external_events(ctx, [event])
            return {
                "ok": True,
                "idempotency_key": idempotency_key,
                "response": _safe_response(response),
            }
        raise NotImplementedError(f"adapter_not_implemented:{intent.op_kind}")

    def _validate_payload(self, intent: WriteIntent, *, execute: bool) -> bool:
        payload = intent.payload or {}
        if intent.op_kind == "contact_upsert":
            if not str(payload.get("email") or "").strip():
                intent.error_reason = "missing_email"
                return False
            return True
        if intent.op_kind == "detail_set":
            props = payload.get("properties")
            if not isinstance(props, dict) or not props:
                intent.error_reason = "missing_detail_properties"
                return False
            if not str(payload.get("email") or payload.get("contactId") or "").strip():
                intent.error_reason = "missing_contact_reference"
                return False
            return True
        if intent.op_kind == "tag_add":
            if not str(payload.get("tag") or "").strip():
                intent.error_reason = "missing_tag"
                return False
            if execute and not str(payload.get("email") or payload.get("contactId") or "").strip():
                intent.error_reason = "missing_contact_reference"
                return False
            return True
        if intent.op_kind == "event_ingest":
            if not str(payload.get("externalId") or "").strip():
                intent.error_reason = "missing_external_id"
                return False
            if execute and not str(
                payload.get("email") or payload.get("contactId") or ""
            ).strip():
                intent.error_reason = "missing_contact_reference"
                return False
            return True
        intent.error_reason = "adapter_not_implemented"
        return False

    def _apply_klints_backfill_marker(self, intent: WriteIntent, contact: dict[str, Any]) -> None:
        if not intent.payload.get("_mark_klints_backfill"):
            return
        props = contact.get("properties")
        if not isinstance(props, dict):
            props = {}
            contact["properties"] = props
        props.setdefault("klints_backfill", "true")


def _safe_response(response: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in response.items()
        if key not in {"apiKey", "sha", "apiSecret"}
    }
