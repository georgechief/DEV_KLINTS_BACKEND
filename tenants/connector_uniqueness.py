"""Global connector account ownership checks (PRD-CONN-02)."""

from __future__ import annotations

from tenants.models import Company, Connector
from tenants.shopify import normalize_shop_domain

OWNING_STATUSES = ("connected", "degraded")
PLATFORM_SHOPIFY = "shopify"
PLATFORM_MANAGO = "manago_ai"
ERROR_CODE = "account_already_connected"

_SHOPIFY_DETAIL = (
    "This Shopify account is already connected in Klints. "
    "Disconnect it from the other workspace, or connect a different store."
)
_MANAGO_DETAIL = (
    "This Manago account is already connected in Klints. "
    "Disconnect it from the other workspace, or connect a different account."
)


class AccountAlreadyConnectedError(Exception):
    """Raised when an external account is owned by another company."""

    code = ERROR_CODE

    def __init__(self, *, platform: str, external_key: str) -> None:
        self.platform = platform
        self.external_key = external_key
        if platform == PLATFORM_SHOPIFY:
            self.detail = _SHOPIFY_DETAIL
        elif platform == PLATFORM_MANAGO:
            self.detail = _MANAGO_DETAIL
        else:
            self.detail = (
                "This account is already connected in Klints. "
                "Disconnect it from the other workspace, or connect a different account."
            )
        super().__init__(self.detail)


def resolve_shopify_external_account_key(shop_domain: str) -> str:
    """Canonical external key for a Shopify shop (PRD-CONN-02 §7.1)."""
    return normalize_shop_domain(shop_domain)


def resolve_manago_external_account_key(workspace_id: str) -> str:
    """Canonical external key for a Manago account (PRD-CONN-02 §7.1)."""
    return (workspace_id or "").strip()


def account_already_connected_warning_payload(
    exc: AccountAlreadyConnectedError,
) -> dict[str, str]:
    """Soft-warning body for verify endpoints (PRD-CONN-02 §4.1)."""
    return {
        "detail": exc.detail,
        "code": exc.code,
        "platform": exc.platform,
        "external_key": exc.external_key,
    }


def get_manago_account_warning(
    *,
    external_key: str,
    company: Company,
) -> dict[str, str] | None:
    """
    Return a soft-warning payload when Manago credentials verify but the account
    is already connected elsewhere. Hard block remains on create.
    """
    normalized_key = resolve_manago_external_account_key(external_key)
    if not normalized_key:
        return None
    try:
        assert_external_account_available(
            platform=PLATFORM_MANAGO,
            external_key=normalized_key,
            company=company,
        )
    except AccountAlreadyConnectedError as exc:
        return account_already_connected_warning_payload(exc)
    return None


def _normalize_shop_id(shop_id) -> str | None:
    if shop_id is None or shop_id == "":
        return None
    return str(shop_id)


def _resolve_shopify_identity(connector: Connector) -> dict[str, str | None]:
    snapshot = connector.snapshots.first()
    if snapshot is not None:
        data = snapshot.snapshot_data or {}
        shop_domain = data.get("shop_domain")
        shop_id = data.get("shop_id")
        if shop_domain or shop_id is not None:
            normalized_domain = None
            if isinstance(shop_domain, str) and shop_domain.strip():
                normalized_domain = normalize_shop_domain(shop_domain)
            return {
                "shop_domain": normalized_domain,
                "shop_id": _normalize_shop_id(shop_id),
            }

    config = connector.config or {}
    shop_domain = config.get("shop_domain")
    shop_id = config.get("shop_id")
    normalized_domain = None
    if isinstance(shop_domain, str) and shop_domain.strip():
        normalized_domain = normalize_shop_domain(shop_domain)
    return {
        "shop_domain": normalized_domain,
        "shop_id": _normalize_shop_id(shop_id),
    }


def _resolve_manago_identity(connector: Connector) -> dict[str, str | None]:
    snapshot = connector.snapshots.first()
    if snapshot is not None:
        data = snapshot.snapshot_data or {}
        workspace_id = data.get("workspace_id")
        client_id = data.get("client_id")
        if isinstance(workspace_id, str) and workspace_id.strip():
            return {"workspace_id": workspace_id.strip(), "client_id": None}
        if isinstance(client_id, str) and client_id.strip():
            return {"workspace_id": client_id.strip(), "client_id": client_id.strip()}

    config = connector.config or {}
    workspace_id = config.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return {"workspace_id": workspace_id.strip(), "client_id": None}
    client_id = config.get("client_id")
    if isinstance(client_id, str) and client_id.strip():
        return {"workspace_id": client_id.strip(), "client_id": client_id.strip()}
    return {"workspace_id": None, "client_id": None}


def _shopify_identity_matches(
    *,
    identity: dict[str, str | None],
    shop_domain: str,
    shop_id,
) -> bool:
    if identity.get("shop_domain") == shop_domain:
        return True
    normalized_shop_id = _normalize_shop_id(shop_id)
    if normalized_shop_id is None:
        return False
    return identity.get("shop_id") == normalized_shop_id


def find_shopify_owner(*, shop_domain: str, shop_id=None) -> Connector | None:
    """Return a blocking Shopify connector owner, if any."""
    normalized_domain = normalize_shop_domain(shop_domain)
    direct_owner = Connector.objects.filter(
        name=PLATFORM_SHOPIFY,
        status__in=OWNING_STATUSES,
        external_account_key=normalized_domain,
    ).first()
    if direct_owner is not None:
        return direct_owner

    candidates = Connector.objects.filter(
        name=PLATFORM_SHOPIFY,
        status__in=OWNING_STATUSES,
    ).prefetch_related("snapshots")

    for connector in candidates:
        identity = _resolve_shopify_identity(connector)
        if _shopify_identity_matches(
            identity=identity,
            shop_domain=normalized_domain,
            shop_id=shop_id,
        ):
            return connector
    return None


def find_manago_owner(*, workspace_id: str) -> Connector | None:
    """Return a blocking Manago connector owner, if any."""
    normalized_workspace_id = resolve_manago_external_account_key(workspace_id)
    if not normalized_workspace_id:
        return None

    direct_owner = Connector.objects.filter(
        name=PLATFORM_MANAGO,
        status__in=OWNING_STATUSES,
        external_account_key=normalized_workspace_id,
    ).first()
    if direct_owner is not None:
        return direct_owner

    candidates = Connector.objects.filter(
        name=PLATFORM_MANAGO,
        status__in=OWNING_STATUSES,
    ).prefetch_related("snapshots")

    for connector in candidates:
        identity = _resolve_manago_identity(connector)
        if identity.get("workspace_id") == normalized_workspace_id:
            return connector
    return None


def assert_external_account_available(
    *,
    platform: str,
    external_key: str,
    company: Company,
    shop_id=None,
) -> None:
    """Raise AccountAlreadyConnectedError if owned by another company."""
    if platform == PLATFORM_SHOPIFY:
        normalized_key = normalize_shop_domain(external_key)
        owner = find_shopify_owner(shop_domain=normalized_key, shop_id=shop_id)
        response_key = normalized_key
    elif platform == PLATFORM_MANAGO:
        normalized_key = resolve_manago_external_account_key(external_key)
        owner = find_manago_owner(workspace_id=normalized_key)
        response_key = normalized_key
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    if owner is None or owner.company_id == company.id:
        return

    raise AccountAlreadyConnectedError(platform=platform, external_key=response_key)
