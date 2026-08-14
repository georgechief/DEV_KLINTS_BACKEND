"""Manago owner topology for FD-06 — list + set primary (CONN onboarding)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from dataruns.connectors.base import decrypt_connector_config
from tenants.manago import list_users_by_client
from tenants.manago_fetch import ManagoFetchError, resolve_manago_credentials
from tenants.models import Company, Connector

logger = logging.getLogger(__name__)

MANAGO_AI_PLATFORM = "manago_ai"
SHOPIFY_PLATFORM = "shopify"
_ELIGIBLE_CONNECTOR_STATUSES = frozenset({"connected", "degraded"})
_SHOP_DOMAIN_NOISE_SUFFIXES = frozenset({"dev", "staging", "test", "shop", "store"})


class ManagoTopologyError(Exception):
    """Raised when Manago owners cannot be listed or primary cannot be applied."""


def preferred_owner_from_config(config: dict[str, Any] | None) -> str | None:
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
                if not isinstance(row, dict) or row.get("in_scope") is False:
                    continue
                owner = row.get("owner")
                if isinstance(owner, str) and owner.strip():
                    return owner.strip()
    return None


def list_manago_owners(*, config: dict[str, Any], timeout: float = 15.0) -> list[str]:
    """Return unique Manago owner emails from listByClient."""
    try:
        endpoint, client_id, api_secret = resolve_manago_credentials(config)
    except ManagoFetchError as exc:
        raise ManagoTopologyError(str(exc)) from exc

    try:
        data = list_users_by_client(
            client_id=client_id,
            api_secret=api_secret,
            endpoint=endpoint,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — surface to API
        raise ManagoTopologyError(f"Manago listByClient failed: {exc}") from exc

    if data.get("success") is False:
        message = data.get("message") or "Manago listByClient rejected credentials."
        raise ManagoTopologyError(str(message))

    owners: list[str] = []
    users = data.get("users")
    if isinstance(users, list):
        for user in users:
            if isinstance(user, str) and user.strip():
                owners.append(user.strip())
            elif isinstance(user, dict):
                email = user.get("email") or user.get("owner") or user.get("login")
                if isinstance(email, str) and email.strip():
                    owners.append(email.strip())

    seen: set[str] = set()
    unique: list[str] = []
    for owner in owners:
        key = owner.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(owner)
    return unique


def apply_primary_owner(
    *,
    config: dict[str, Any],
    primary_owner: str,
    all_owners: list[str] | None = None,
    shop_domain: str | None = None,
) -> dict[str, Any]:
    """
    Write connector config so FD-06 has exactly one in-scope owner.

    Secondary owners are marked ``in_scope=false``.
    """
    primary = primary_owner.strip()
    if not primary or "@" not in primary:
        raise ManagoTopologyError("primary_owner must be a Manago user email.")

    owners = list(all_owners or [])
    if not any(o.lower() == primary.lower() for o in owners):
        owners = [primary, *owners]

    # Preserve first-seen casing for primary.
    primary_casings = [o for o in owners if o.lower() == primary.lower()]
    primary_display = primary_casings[0] if primary_casings else primary

    accounts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for owner in owners:
        key = owner.lower()
        if key in seen:
            continue
        seen.add(key)
        is_primary = key == primary_display.lower()
        accounts.append(
            {
                "owner": owner,
                "in_scope": is_primary,
                "classification": "single_account" if is_primary else "unknown",
                "label": "primary" if is_primary else "out_of_scope",
                "shop_domain": shop_domain if is_primary else None,
            }
        )

    updated = dict(config)
    updated["owner"] = primary_display
    updated["owner_email"] = primary_display
    updated["topology"] = {"accounts": accounts}
    return updated


@dataclass(frozen=True)
class EnsureManagoPrimaryResult:
    """Outcome of attempting to persist a Manago primary owner for FD-06."""

    applied: bool
    primary_owner: str | None
    reason: str
    owner_count: int = 0


def shopify_shop_domain_for_company(company: Company) -> str | None:
    """Return the connected Shopify shop domain for a company, if any."""
    shopify = Connector.objects.filter(
        company=company,
        name=SHOPIFY_PLATFORM,
        status__in=_ELIGIBLE_CONNECTOR_STATUSES,
    ).first()
    if shopify is None:
        return None
    config = decrypt_connector_config(shopify.config)
    domain = config.get("shop_domain") or config.get("shop")
    if isinstance(domain, str) and domain.strip():
        return domain.strip()
    return None


def _shop_slug_tokens(shop_domain: str) -> list[str]:
    slug = shop_domain.strip().lower().split(".")[0]
    tokens = [
        token
        for token in slug.replace("_", "-").split("-")
        if token and token not in _SHOP_DOMAIN_NOISE_SUFFIXES
    ]
    return tokens or [slug.split("-")[0]]


def infer_primary_owner_from_shop_domain(
    owners: list[str],
    shop_domain: str | None,
) -> str | None:
    """
    Infer a unique primary owner from the Shopify shop slug.

    Example: ``klints-dev.myshopify.com`` matches ``noreplyklints@gmail.com`` when
    that is the only owner whose local-part contains ``klints``.
    """
    if len(owners) <= 1 or not shop_domain:
        return None

    tokens = _shop_slug_tokens(shop_domain)
    matches = [
        owner
        for owner in owners
        if any(token in owner.split("@", 1)[0].lower() for token in tokens)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def ensure_manago_primary_owner(
    company: Company,
    *,
    actor_user_id: str | None = None,
    performed_by: str | None = None,
    allow_single_owner_auto: bool = True,
    allow_multi_owner_inference: bool = True,
) -> EnsureManagoPrimaryResult:
    """
    Persist a Manago primary owner when FD-06 can resolve it automatically.

    Used by the DCS pipeline and post-bootstrap enqueue so scoring is not blocked
    waiting for a manual Integrations picker when the owner can be inferred safely.
    """
    connector = Connector.objects.filter(
        company=company,
        name=MANAGO_AI_PLATFORM,
        status__in=_ELIGIBLE_CONNECTOR_STATUSES,
    ).first()
    if connector is None:
        return EnsureManagoPrimaryResult(
            applied=False,
            primary_owner=None,
            reason="no_manago",
        )

    stored_config = dict(connector.config or {})
    config = decrypt_connector_config(stored_config)
    try:
        owners = list_manago_owners(config=stored_config)
    except ManagoTopologyError as exc:
        logger.warning(
            "Manago primary owner ensure skipped company_id=%s error=%s",
            company.id,
            exc,
        )
        return EnsureManagoPrimaryResult(
            applied=False,
            primary_owner=None,
            reason="list_failed",
        )

    existing = preferred_owner_from_config(config)
    if existing and any(owner.lower() == existing.lower() for owner in owners):
        return EnsureManagoPrimaryResult(
            applied=False,
            primary_owner=existing,
            reason="already_configured",
            owner_count=len(owners),
        )

    if not owners:
        return EnsureManagoPrimaryResult(
            applied=False,
            primary_owner=None,
            reason="no_owners",
        )

    primary: str | None = None
    reason = "needs_manual_selection"

    if len(owners) == 1:
        if allow_single_owner_auto:
            primary = owners[0]
            reason = "single_owner_auto"
    elif allow_multi_owner_inference:
        shop_domain = shopify_shop_domain_for_company(company)
        primary = infer_primary_owner_from_shop_domain(owners, shop_domain)
        if primary is not None:
            reason = "inferred_from_shop"

    if primary is None:
        if len(owners) > 1:
            logger.info(
                "Manago primary owner needs manual selection company_id=%s owners=%s",
                company.id,
                owners,
            )
        return EnsureManagoPrimaryResult(
            applied=False,
            primary_owner=None,
            reason=reason,
            owner_count=len(owners),
        )

    shop_domain = shopify_shop_domain_for_company(company)
    try:
        config = apply_primary_owner(
            config=config,
            primary_owner=primary,
            all_owners=owners,
            shop_domain=shop_domain,
        )
    except ManagoTopologyError as exc:
        logger.warning(
            "Manago primary owner apply failed company_id=%s error=%s",
            company.id,
            exc,
        )
        return EnsureManagoPrimaryResult(
            applied=False,
            primary_owner=None,
            reason="apply_failed",
            owner_count=len(owners),
        )

    from tenants.crypto import encrypt_config

    connector.config = encrypt_config(config)
    connector.save(update_fields=["config", "updated_at"])

    from dataruns.audit import append_audit_event, resolve_performed_by_email

    audit_actor = performed_by or resolve_performed_by_email(
        str(actor_user_id) if actor_user_id else None
    )
    append_audit_event(
        company=company,
        action="connector.manago_primary_owner_auto_set",
        summary=(
            "Manago primary owner auto-selected (single user)"
            if reason == "single_owner_auto"
            else "Manago primary owner inferred from Shopify shop"
        ),
        performed_by=audit_actor,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        metadata={
            "platform": MANAGO_AI_PLATFORM,
            "connector_id": str(connector.id),
            "primary_owner": config.get("owner"),
            "reason": reason,
            "owner_count": len(owners),
        },
    )
    logger.info(
        "Manago primary owner persisted company_id=%s owner=%s reason=%s",
        company.id,
        config.get("owner"),
        reason,
    )
    return EnsureManagoPrimaryResult(
        applied=True,
        primary_owner=str(config.get("owner") or primary),
        reason=reason,
        owner_count=len(owners),
    )


def topology_status(
    *,
    config: dict[str, Any],
    owners: list[str],
) -> dict[str, Any]:
    """Build API payload fields for owner selection."""
    primary = preferred_owner_from_config(config)
    owner_keys = {o.lower() for o in owners}
    primary_known = bool(primary and primary.lower() in owner_keys)
    # Multi-owner without a chosen primary (or primary not in live list).
    needs_primary_selection = len(owners) > 1 and not primary_known
    return {
        "owners": [{"email": o, "is_primary": bool(primary and o.lower() == primary.lower())} for o in owners],
        "primary_owner": primary if primary_known else (primary if primary else None),
        "owner_count": len(owners),
        "needs_primary_selection": needs_primary_selection,
        "topology_configured": bool(primary_known and isinstance(config.get("topology"), dict)),
    }
