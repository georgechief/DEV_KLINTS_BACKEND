"""Shopify write adapter (PRD-WB-01 §6.1 / PRD-WB-01B §4)."""

from __future__ import annotations

import logging
from typing import Any

from dataruns.connectors.shopify.client import ShopifyClientError
from dataruns.writebacks.adapters.shopify_transport import (
    get_customer,
    resolve_shopify_write_context,
    update_customer,
)
from dataruns.writebacks.capabilities import capability_allows_execute
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company

logger = logging.getLogger(__name__)


class ShopifyWriteAdapter:
    target = "shopify"

    def dry_run(self, company: Company, intents: list[WriteIntent]) -> list[WriteIntent]:
        del company
        for intent in intents:
            if intent.status == "error":
                continue
            if intent.op_kind in ("shopify_customer_update", "shopify_metafield_set"):
                if not capability_allows_execute(intent.capability_id):
                    intent.status = "error"
                    intent.error_reason = "capability_not_confirmed"
                    continue
                if self._validate_payload(intent, execute=False):
                    intent.status = "ready"
                else:
                    intent.status = "error"
                    intent.error_reason = intent.error_reason or "invalid_payload"
            else:
                intent.status = "error"
                intent.error_reason = "adapter_not_implemented"
        return intents

    def execute(
        self,
        company: Company,
        intents: list[WriteIntent],
        *,
        approval_id: str | None,
        idempotency_key: str | None,
    ) -> list[WriteIntent]:
        del approval_id
        try:
            ctx = resolve_shopify_write_context(company)
        except Exception as exc:
            logger.exception("Shopify write context failed company=%s", company.id)
            for intent in intents:
                intent.status = "error"
                intent.error_reason = "upstream_error"
                intent.execute_result = {"ok": False}
            return intents

        updated: list[WriteIntent] = []
        for intent in intents:
            if intent.status != "ready":
                updated.append(intent)
                continue
            if not capability_allows_execute(intent.capability_id):
                intent.status = "error"
                intent.error_reason = "capability_not_confirmed"
                updated.append(intent)
                continue
            if not self._validate_payload(intent, execute=True):
                intent.status = "error"
                intent.error_reason = intent.error_reason or "invalid_payload"
                updated.append(intent)
                continue
            try:
                if intent.op_kind == "shopify_customer_update":
                    self._refresh_customer_note_snapshot(ctx, intent)
                    payload = intent.payload or {}
                    customer_id = str(payload.get("id") or payload.get("customer_id") or "")
                    body = {
                        key: value
                        for key, value in payload.items()
                        if key not in {"id", "customer_id", "email"} and value is not None
                    }
                    response = update_customer(ctx, customer_id=customer_id, payload=body)
                    intent.execute_result = {
                        "ok": True,
                        "idempotency_key": idempotency_key,
                        "response": response,
                    }
                    intent.status = "executed"
                else:
                    intent.status = "error"
                    intent.error_reason = "adapter_not_implemented"
                    intent.execute_result = {"ok": False}
            except ShopifyClientError as exc:
                logger.warning("Shopify write failed op=%s: %s", intent.operation, exc)
                intent.status = "error"
                intent.error_reason = "upstream_error"
                intent.execute_result = {"ok": False}
            updated.append(intent)
        return updated

    def rollback_intent(
        self,
        company: Company,
        intent: WriteIntent,
    ) -> dict[str, Any]:
        ctx = resolve_shopify_write_context(company)
        payload = intent.payload or {}
        snapshot = intent.rollback_snapshot or {}
        customer_id = str(
            payload.get("id") or payload.get("customer_id") or snapshot.get("id") or ""
        )
        if not customer_id:
            raise ShopifyClientError("rollback shopify_customer_update missing customer id")

        if intent.op_kind == "shopify_customer_update":
            prior_note = snapshot.get("note")
            # Empty string clears the note when prior was absent.
            restore = "" if prior_note is None else str(prior_note)
            response = update_customer(ctx, customer_id=customer_id, payload={"note": restore})
            return {
                "ok": True,
                "restored_note": restore,
                "response": response,
            }

        raise NotImplementedError(f"rollback not supported for {intent.op_kind}")

    def _refresh_customer_note_snapshot(self, ctx, intent: WriteIntent) -> None:
        payload = intent.payload or {}
        customer_id = str(payload.get("id") or payload.get("customer_id") or "")
        if not customer_id:
            return
        try:
            customer = get_customer(ctx, customer_id=customer_id)
            prior_note = customer.get("note")
        except ShopifyClientError:
            prior_note = (intent.rollback_snapshot or {}).get("note")
        intent.rollback_snapshot = {
            "id": customer_id,
            "note": prior_note if prior_note not in (None, "") else None,
        }
        intent.before = {
            **(intent.before or {}),
            "id": customer_id,
            "note": intent.rollback_snapshot.get("note"),
        }

    def _validate_payload(self, intent: WriteIntent, *, execute: bool) -> bool:
        payload = intent.payload or {}
        if intent.op_kind == "shopify_customer_update":
            customer_id = str(payload.get("id") or payload.get("customer_id") or "")
            if execute and not customer_id:
                intent.error_reason = "missing_customer_id"
                return False
            if "note" not in payload and execute:
                intent.error_reason = "missing_note"
                return False
            return True
        if intent.op_kind == "shopify_metafield_set":
            if execute:
                intent.error_reason = "adapter_not_implemented"
                return False
            return True
        intent.error_reason = "adapter_not_implemented"
        return False
