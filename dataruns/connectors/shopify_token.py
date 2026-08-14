"""Ensure Shopify offline tokens are fresh before Celery jobs (PRD-CONN-03 / CONN-05)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from dataruns.connectors.base import decrypt_connector_config
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, ConnectorSnapshot
from tenants.shopify import (
    TOKEN_MODE_EXPIRING,
    ShopifyOAuthError,
    apply_token_bundle_to_config,
    parse_iso_utc,
    refresh_offline_access_token,
    resolve_token_mode,
    snapshot_safe_shopify_config,
)

logger = logging.getLogger(__name__)

AUTH_FAILURE_REASON_INACTIVE = "REFRESH_INACTIVE"
AUTH_FAILURE_REASON_EXPIRED = "REFRESH_EXPIRED"
AUTH_FAILURE_REASON_FAILED = "AUTH_FAILED"

_AUTH_FAILURE_SUMMARIES = {
    AUTH_FAILURE_REASON_INACTIVE: (
        "Shopify connection requires reconnect (refresh token inactive)."
    ),
    AUTH_FAILURE_REASON_EXPIRED: (
        "Shopify connection requires reconnect (refresh token expired)."
    ),
    AUTH_FAILURE_REASON_FAILED: (
        "Shopify connection requires reconnect (authentication failed)."
    ),
}


class ShopifyAuthExpiredError(ShopifyOAuthError):
    """Raised when the Shopify refresh token is expired or inactive."""


def classify_shopify_terminal_auth_failure(exc: BaseException) -> str | None:
    """
    Return a terminal auth reason code, or None when the failure is retryable
    and connector status must not be flipped (PRD-CONN-05 §4).
    """
    if isinstance(exc, ShopifyAuthExpiredError):
        return AUTH_FAILURE_REASON_EXPIRED
    if not isinstance(exc, ShopifyOAuthError):
        return None

    message = str(exc).lower()
    if "inactive" in message and "refresh" in message:
        return AUTH_FAILURE_REASON_INACTIVE
    if "refresh token expired" in message:
        return AUTH_FAILURE_REASON_EXPIRED
    if message.startswith("shopify returned http "):
        try:
            code = int(
                message.removeprefix("shopify returned http ").split(".", 1)[0]
            )
        except ValueError:
            return AUTH_FAILURE_REASON_FAILED
        if code in (429, 500, 502, 503, 504):
            return None
        if code == 401:
            return AUTH_FAILURE_REASON_FAILED
        return None
    if "could not reach shopify" in message or "timed out" in message:
        return None
    if "missing shop_domain" in message:
        return AUTH_FAILURE_REASON_FAILED
    return AUTH_FAILURE_REASON_FAILED


def mark_shopify_auth_expired(
    *,
    connector: Connector,
    company: Company,
    reason_code: str,
    source: str,
    error_message: str,
) -> bool:
    """
    Persist terminal Shopify auth failure on the connector (PRD-CONN-05 §5).

    Returns True when status transitions from connected/degraded to error
    (email + audit emitted). Returns False when already error (deduped).
    """
    from dataruns.audit import append_audit_event
    from dataruns.models import AuditLog
    from tenants.emails import MailerAPIError, send_shopify_auth_expired_email

    summary = _AUTH_FAILURE_SUMMARIES.get(
        reason_code,
        _AUTH_FAILURE_SUMMARIES[AUTH_FAILURE_REASON_FAILED],
    )
    transitioned = False
    shop_domain = ""

    with transaction.atomic():
        locked = Connector.objects.select_for_update().get(pk=connector.pk)
        prior_status = locked.status
        config = decrypt_connector_config(locked.config)
        shop_domain = str(config.get("shop_domain") or "").strip()
        now_iso = timezone.now().isoformat().replace("+00:00", "Z")

        config["auth_failure_at"] = now_iso
        config["auth_failure_reason"] = reason_code
        locked.config = encrypt_config(config)

        if prior_status in ("connected", "degraded"):
            locked.status = "error"
            transitioned = True

        locked.save(update_fields=["config", "status", "updated_at"])

    if transitioned:
        try:
            append_audit_event(
                company=company,
                action="connector.auth_expired",
                summary=summary,
                performed_by="system",
                tone=AuditLog.Tone.RISK,
                metadata={
                    "platform": "shopify",
                    "reason_code": reason_code,
                    "source": source,
                    "shop_domain": shop_domain or None,
                },
            )
        except Exception:
            logger.exception(
                "Failed to append connector.auth_expired audit connector_id=%s",
                connector.pk,
            )

        try:
            send_shopify_auth_expired_email(
                company=company,
                shop_domain=shop_domain,
                reason_code=reason_code,
                source=source,
            )
        except MailerAPIError:
            logger.exception(
                "Failed to send Shopify auth-expired email connector_id=%s",
                connector.pk,
            )
    else:
        logger.info(
            "Skipped Shopify auth-expired notify (already error) connector_id=%s "
            "reason=%s source=%s error=%s",
            connector.pk,
            reason_code,
            source,
            error_message,
        )

    return transitioned


def ensure_fresh_shopify_token(
    *,
    connector: Connector,
    skew_seconds: int = 120,
) -> dict[str, Any]:
    """
    Load encrypted config. If offline_expiring and access token expired
    (or expires within skew), refresh, save connector.config, return plain config.
    """
    with transaction.atomic():
        locked = Connector.objects.select_for_update().get(pk=connector.pk)
        config = decrypt_connector_config(locked.config)

        if locked.name != "shopify":
            return config

        token_mode = resolve_token_mode(config)
        if token_mode != TOKEN_MODE_EXPIRING or not config.get("refresh_token"):
            return config

        now = timezone.now()
        refresh_expires_at = config.get("refresh_token_expires_at")
        if isinstance(refresh_expires_at, str) and refresh_expires_at:
            if parse_iso_utc(refresh_expires_at) <= now:
                raise ShopifyAuthExpiredError(
                    "Shopify refresh token expired; reconnect required."
                )

        access_expires_at = config.get("access_token_expires_at")
        if isinstance(access_expires_at, str) and access_expires_at:
            if parse_iso_utc(access_expires_at) > now + timedelta(seconds=skew_seconds):
                return config

        shop_domain = config.get("shop_domain")
        refresh_token = config.get("refresh_token")
        if not isinstance(shop_domain, str) or not shop_domain.strip():
            raise ShopifyOAuthError("Shopify connector is missing shop_domain.")
        if not isinstance(refresh_token, str) or not refresh_token:
            return config

        bundle = refresh_offline_access_token(
            shop=shop_domain.strip(),
            refresh_token=refresh_token,
        )
        updated_config = apply_token_bundle_to_config(config, bundle)
        # Clear auth-failure metadata after a successful refresh (reconnect recovery).
        updated_config.pop("auth_failure_at", None)
        updated_config.pop("auth_failure_reason", None)
        locked.config = encrypt_config(updated_config)
        locked.save(update_fields=["config", "updated_at"])
        _maybe_bump_snapshot_metadata(connector=locked, config=updated_config)

    return updated_config


def _maybe_bump_snapshot_metadata(
    *,
    connector: Connector,
    config: dict[str, Any],
) -> None:
    """Optional metadata-only snapshot version bump (PRD-CONN-03 §7 step 8)."""
    last_version = (
        ConnectorSnapshot.objects.filter(connector=connector)
        .aggregate(Max("version"))["version__max"]
        or 0
    )
    ConnectorSnapshot.objects.create(
        connector=connector,
        version=last_version + 1,
        snapshot_data=snapshot_safe_shopify_config(config),
    )
