"""Shopify write adapter (PRD-WB-01 §6.1)."""

from __future__ import annotations

import logging

from dataruns.connectors.shopify.client import ShopifyClientError
from dataruns.writebacks.adapters.shopify_transport import (
    resolve_shopify_write_context,
    update_customer,
)
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company

logger = logging.getLogger(__name__)


class ShopifyWriteAdapter:
    target = "shopify"

    def dry_run(self, company: Company, intents: list[WriteIntent]) -> list[WriteIntent]:
        for intent in intents:
            if intent.status == "error":
                continue
            if intent.op_kind in ("shopify_customer_update", "shopify_metafield_set"):
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
            for intent in intents:
                intent.status = "error"
                intent.error_reason = f"shopify_context_failed:{type(exc).__name__}"
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
                if intent.op_kind == "shopify_customer_update":
                    payload = intent.payload or {}
                    customer_id = str(payload.get("id") or payload.get("customer_id") or "")
                    body = {
                        key: value
                        for key, value in payload.items()
                        if key not in {"id", "customer_id"} and value is not None
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
                    intent.execute_result = {"ok": False, "error": "adapter_not_implemented"}
            except ShopifyClientError as exc:
                logger.warning("Shopify write failed op=%s: %s", intent.operation, exc)
                intent.status = "error"
                intent.error_reason = "shopify_write_failed"
                intent.execute_result = {"ok": False, "error": str(exc)}
            updated.append(intent)
        return updated

    def _validate_payload(self, intent: WriteIntent, *, execute: bool) -> bool:
        payload = intent.payload or {}
        if intent.op_kind == "shopify_customer_update":
            customer_id = str(payload.get("id") or payload.get("customer_id") or "")
            if execute and not customer_id:
                intent.error_reason = "missing_customer_id"
                return False
            return True
        if intent.op_kind == "shopify_metafield_set":
            if execute:
                intent.error_reason = "adapter_not_implemented"
                return False
            return True
        intent.error_reason = "adapter_not_implemented"
        return False
