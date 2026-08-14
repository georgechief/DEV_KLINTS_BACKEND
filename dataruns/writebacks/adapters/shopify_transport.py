"""Shopify Admin REST transport for writeback execute."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dataruns.connectors.base import decrypt_connector_config, get_connector
from dataruns.connectors.shopify.client import ShopifyClientError, _resolve_credentials
from tenants.models import Company


@dataclass(frozen=True)
class ShopifyWriteContext:
    shop: str
    access_token: str
    api_version: str


def resolve_shopify_write_context(company: Company) -> ShopifyWriteContext:
    connector = get_connector(company=company, platform="shopify")
    config = decrypt_connector_config(connector.config)
    shop, access_token, api_version = _resolve_credentials(config)
    return ShopifyWriteContext(
        shop=shop,
        access_token=access_token,
        api_version=api_version,
    )


def update_customer(
    ctx: ShopifyWriteContext,
    *,
    customer_id: str,
    payload: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    body = json.dumps({"customer": payload}).encode("utf-8")
    url = (
        f"https://{ctx.shop}/admin/api/{ctx.api_version}/customers/"
        f"{customer_id}.json"
    )
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "X-Shopify-Access-Token": ctx.access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ShopifyClientError(f"Shopify customer update failed: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ShopifyClientError(f"Shopify customer update failed: {exc}") from exc

    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        raise ShopifyClientError("Shopify customer update returned invalid JSON")
    return data
