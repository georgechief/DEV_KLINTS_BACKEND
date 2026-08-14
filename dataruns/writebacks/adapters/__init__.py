"""Adapter registry by target system."""

from __future__ import annotations

from dataruns.writebacks.adapters.manago import ManagoWriteAdapter
from dataruns.writebacks.adapters.shopify import ShopifyWriteAdapter

_ADAPTERS = {
    "manago": ManagoWriteAdapter(),
    "manago_ai": ManagoWriteAdapter(),
    "shopify": ShopifyWriteAdapter(),
}


def get_adapter(target_system: str):
    return _ADAPTERS.get(target_system)
