"""Shopify Admin API list helpers for connector fetch (customers, orders)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone as dt_timezone
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone

from tenants.crypto import decrypt_api_key
from tenants.shopify import ShopifyOAuthError, normalize_shop_domain

_SHOPIFY_PAGE_LIMIT = 250
_LINK_REL_NEXT_RE = re.compile(r"""<([^>]+)>;\s*rel="next""")


class ShopifyFetchError(ShopifyOAuthError):
    """Raised when a Shopify Admin API list request fails."""


def resolve_shopify_credentials(config: dict[str, Any]) -> tuple[str, str, str]:
    """
    Extract shop domain, access token, and API version from a Connector config.

    ``access_token`` is stored encrypted (see ``tenants.crypto.encrypt_config``).
    """
    shop_domain = config.get("shop_domain")
    if not isinstance(shop_domain, str) or not shop_domain.strip():
        raise ShopifyFetchError("Shopify connector is missing shop_domain.")

    encrypted_token = config.get("access_token")
    if not isinstance(encrypted_token, str) or not encrypted_token:
        raise ShopifyFetchError("Shopify connector is missing access_token.")

    try:
        access_token = decrypt_api_key(encrypted_token)
    except Exception as exc:  # noqa: BLE001 — Fernet InvalidToken, etc.
        raise ShopifyFetchError(
            "Could not decrypt Shopify access token."
        ) from exc

    api_version = config.get("api_version") or settings.SHOPIFY_API_VERSION
    if not isinstance(api_version, str) or not api_version.strip():
        api_version = settings.SHOPIFY_API_VERSION

    return normalize_shop_domain(shop_domain), access_token, api_version


def fetch_customers(
    *,
    config: dict[str, Any],
    updated_at_min: datetime,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """
    Fetch all customers updated on or after ``updated_at_min``.

    Wraps ``GET customers.json?updated_at_min=…`` with cursor pagination.
    """
    shop, access_token, api_version = resolve_shopify_credentials(config)
    return _fetch_paginated_resource(
        shop=shop,
        access_token=access_token,
        api_version=api_version,
        resource="customers",
        collection_key="customers",
        query_params={"updated_at_min": _format_shopify_datetime(updated_at_min)},
        timeout=timeout,
    )


def fetch_orders(
    *,
    config: dict[str, Any],
    created_at_min: datetime,
    status: str = "any",
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """
    Fetch all orders created on or after ``created_at_min``.

    Wraps ``GET orders.json?status=any&created_at_min=…`` with cursor pagination.
    """
    shop, access_token, api_version = resolve_shopify_credentials(config)
    return _fetch_paginated_resource(
        shop=shop,
        access_token=access_token,
        api_version=api_version,
        resource="orders",
        collection_key="orders",
        query_params={
            "status": status,
            "created_at_min": _format_shopify_datetime(created_at_min),
        },
        timeout=timeout,
    )


def _fetch_paginated_resource(
    *,
    shop: str,
    access_token: str,
    api_version: str,
    resource: str,
    collection_key: str,
    query_params: dict[str, str],
    timeout: float,
) -> list[dict[str, Any]]:
    params = {**query_params, "limit": str(_SHOPIFY_PAGE_LIMIT)}
    url = (
        f"https://{shop}/admin/api/{api_version}/{resource}.json"
        f"?{urlencode(params)}"
    )
    collected: list[dict[str, Any]] = []

    while url:
        page_items, url = _get_resource_page(
            url=url,
            access_token=access_token,
            collection_key=collection_key,
            timeout=timeout,
        )
        collected.extend(page_items)

    return collected


def _get_resource_page(
    *,
    url: str,
    access_token: str,
    collection_key: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], str | None]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "X-Shopify-Access-Token": access_token,
            "Accept": "application/json",
        },
    )
    data, response_headers = _read_json_with_headers(request, timeout=timeout)
    items = data.get(collection_key)
    if items is None:
        raise ShopifyFetchError(
            f"Shopify {collection_key} response did not include '{collection_key}'."
        )
    if not isinstance(items, list):
        raise ShopifyFetchError(
            f"Shopify {collection_key} field was not a JSON array."
        )
    page_items = [item for item in items if isinstance(item, dict)]
    next_url = _parse_next_link(response_headers.get("Link"))
    return page_items, next_url


def _parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        match = _LINK_REL_NEXT_RE.search(part.strip())
        if match:
            return match.group(1)
    return None


def _format_shopify_datetime(value: datetime) -> str:
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json_with_headers(
    request: urllib.request.Request,
    *,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            headers = {
                key: value
                for key, value in response.headers.items()
            }
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc)
        raise ShopifyFetchError(
            f"Shopify returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ShopifyFetchError(f"Could not reach Shopify: {reason}") from exc
    except TimeoutError as exc:
        raise ShopifyFetchError("Shopify request timed out.") from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ShopifyFetchError("Shopify returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ShopifyFetchError("Shopify response was not a JSON object.")
    return data, headers


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
        if raw:
            return raw[:500]
    except Exception:  # noqa: BLE001
        pass
    return exc.reason or "no response body"
