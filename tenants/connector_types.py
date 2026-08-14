"""Canonical connector `type` values (platform name → type slug)."""

from __future__ import annotations

CONNECTOR_TYPE_CDP = "cdp"
CONNECTOR_TYPE_ECOMMERCE = "ecommerce"

CONNECTOR_TYPES = frozenset({CONNECTOR_TYPE_CDP, CONNECTOR_TYPE_ECOMMERCE})

_PLATFORM_TYPE_BY_NAME: dict[str, str] = {
    "manago_ai": CONNECTOR_TYPE_CDP,
    "shopify": CONNECTOR_TYPE_ECOMMERCE,
}


def resolve_connector_type(connector_name: str) -> str:
    """Return the canonical type for a connector platform name."""
    try:
        return _PLATFORM_TYPE_BY_NAME[connector_name]
    except KeyError as exc:
        raise ValueError(f"Unknown connector name: {connector_name!r}") from exc
