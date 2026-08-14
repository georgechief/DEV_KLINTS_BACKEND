"""Shopify Admin API HTTP client for connector import."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone

from tenants.shopify import ShopifyOAuthError, normalize_shop_domain

_SHOPIFY_PAGE_LIMIT = 250
_LINK_REL_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class ShopifyClientError(ShopifyOAuthError):
    """Raised when a Shopify Admin API request fails."""


@dataclass(frozen=True)
class FetchWindow:
    window_start: datetime
    window_end: datetime


class ShopifyClient:
    """HTTP-only Shopify connector client."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.last_rate_budget: dict[str, Any] | None = None

    def fetch(
        self,
        window: FetchWindow,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """
        Fetch raw Shopify customers, orders, products, and abandoned checkouts.

        Returns platform payloads only (PRD §6 step 7, §9 raw shape).
        Captures ``X-Shopify-Shop-Api-Call-Limit`` into ``last_rate_budget``.
        Checkouts require ``read_orders`` (already in SHOPIFY_SCOPES); soft-fail
        if Protected Customer Data / API denies access.
        """
        from dataruns.dcs.rate_budget import merge_shopify_call_limit

        shop, access_token, api_version = _resolve_credentials(self._config)
        rate_budget: dict[str, Any] | None = None
        customers, rate_budget = _fetch_paginated_resource(
            shop=shop,
            access_token=access_token,
            api_version=api_version,
            resource="customers",
            collection_key="customers",
            query_params={
                "updated_at_min": _format_shopify_datetime(window.window_start),
            },
            timeout=timeout,
            rate_budget=rate_budget,
            merge_budget=merge_shopify_call_limit,
        )
        orders, rate_budget = _fetch_paginated_resource(
            shop=shop,
            access_token=access_token,
            api_version=api_version,
            resource="orders",
            collection_key="orders",
            query_params={
                "status": "any",
                "created_at_min": _format_shopify_datetime(window.window_start),
            },
            timeout=timeout,
            rate_budget=rate_budget,
            merge_budget=merge_shopify_call_limit,
        )
        # Excel PT-03: active Shopify products (read_products). Soft-fail if scope missing.
        products: list[dict[str, Any]] = []
        products_error: str | None = None
        try:
            products, rate_budget = _fetch_paginated_resource(
                shop=shop,
                access_token=access_token,
                api_version=api_version,
                resource="products",
                collection_key="products",
                query_params={"status": "active"},
                timeout=timeout,
                rate_budget=rate_budget,
                merge_budget=merge_shopify_call_limit,
            )
        except ShopifyClientError as exc:
            products_error = str(exc)
            products = []

        # Excel LE-08: abandoned checkouts (read_orders). Soft-fail on PCD / API errors.
        checkouts, checkouts_error, rate_budget = _fetch_abandoned_checkouts(
            shop=shop,
            access_token=access_token,
            api_version=api_version,
            window=window,
            timeout=timeout,
            rate_budget=rate_budget,
            merge_budget=merge_shopify_call_limit,
        )

        # Excel BR-02: inventory_levels.updated_at (read_inventory / locations).
        inventory_levels, inventory_error, rate_budget = _fetch_inventory_levels(
            shop=shop,
            access_token=access_token,
            api_version=api_version,
            timeout=timeout,
            rate_budget=rate_budget,
            merge_budget=merge_shopify_call_limit,
        )

        # Excel SP-03: sample customer metafields for source comparison (capped).
        customer_metafields: list[dict[str, Any]] = []
        for customer in customers[:15]:
            cid = customer.get("id")
            if cid is None:
                continue
            try:
                mf_page, rate_budget = _fetch_paginated_resource(
                    shop=shop,
                    access_token=access_token,
                    api_version=api_version,
                    resource=f"customers/{cid}/metafields",
                    collection_key="metafields",
                    query_params={},
                    timeout=timeout,
                    rate_budget=rate_budget,
                    merge_budget=merge_shopify_call_limit,
                )
                for mf in mf_page:
                    customer_metafields.append(
                        {
                            "customer_id": str(cid),
                            "namespace": mf.get("namespace"),
                            "key": mf.get("key"),
                            "type": mf.get("type"),
                            "value": mf.get("value"),
                        }
                    )
            except ShopifyClientError:
                break
        if rate_budget is not None:
            rate_budget = {**rate_budget, "source": "import"}
            if products_error:
                rate_budget = {**rate_budget, "products_fetch_error": products_error}
            if checkouts_error:
                rate_budget = {
                    **rate_budget,
                    "checkouts_fetch_error": checkouts_error,
                }
            if inventory_error:
                rate_budget = {
                    **rate_budget,
                    "inventory_levels_fetch_error": inventory_error,
                }
            rate_budget = {
                **rate_budget,
                "checkouts_fetched": len(checkouts),
                "inventory_levels_fetched": len(inventory_levels),
            }
        self.last_rate_budget = rate_budget
        return {
            "customers": customers,
            "orders": orders,
            "products": products,
            "checkouts": checkouts,
            "abandoned_checkouts": checkouts,
            "inventory_levels": inventory_levels,
            "customer_metafields": customer_metafields,
            "transactions": [],
            "products_fetch_error": products_error,
            "checkouts_fetch_error": checkouts_error,
            "inventory_levels_fetch_error": inventory_error,
        }


def _resolve_credentials(config: dict[str, Any]) -> tuple[str, str, str]:
    shop_domain = config.get("shop_domain")
    if not isinstance(shop_domain, str) or not shop_domain.strip():
        raise ShopifyClientError("Shopify connector is missing shop_domain.")

    access_token = config.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ShopifyClientError("Shopify connector is missing access_token.")

    api_version = config.get("api_version") or settings.SHOPIFY_API_VERSION
    if not isinstance(api_version, str) or not api_version.strip():
        api_version = settings.SHOPIFY_API_VERSION

    return normalize_shop_domain(shop_domain), access_token, api_version


def _fetch_abandoned_checkouts(
    *,
    shop: str,
    access_token: str,
    api_version: str,
    window: FetchWindow,
    timeout: float,
    rate_budget: dict[str, Any] | None,
    merge_budget,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """
    GET /checkouts.json — Shopify abandoned checkouts (open + closed).

    Soft-fails on HTTP errors (PCD approval, deprecated endpoints, etc.).
    """
    created_min = _format_shopify_datetime(window.window_start)
    by_id: dict[str, dict[str, Any]] = {}
    error: str | None = None
    for status in ("open", "closed"):
        try:
            page, rate_budget = _fetch_paginated_resource(
                shop=shop,
                access_token=access_token,
                api_version=api_version,
                resource="checkouts",
                collection_key="checkouts",
                query_params={
                    "status": status,
                    "created_at_min": created_min,
                },
                timeout=timeout,
                rate_budget=rate_budget,
                merge_budget=merge_budget,
            )
            for row in page:
                cid = row.get("id")
                key = str(cid) if cid is not None else str(row.get("token") or "")
                if not key:
                    continue
                by_id[key] = row
        except ShopifyClientError as exc:
            error = str(exc)
            # Keep any rows already collected from the other status.
            break
    return list(by_id.values()), error, rate_budget


def _fetch_inventory_levels(
    *,
    shop: str,
    access_token: str,
    api_version: str,
    timeout: float,
    rate_budget: dict[str, Any] | None,
    merge_budget,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """
    Excel BR-02: GET inventory_levels.json (needs locations + read_inventory).

    Soft-fails when scope/location access is missing.
    """
    try:
        locations, rate_budget = _fetch_paginated_resource(
            shop=shop,
            access_token=access_token,
            api_version=api_version,
            resource="locations",
            collection_key="locations",
            query_params={},
            timeout=timeout,
            rate_budget=rate_budget,
            merge_budget=merge_budget,
        )
    except ShopifyClientError as exc:
        return [], str(exc), rate_budget

    location_ids = [str(loc.get("id")) for loc in locations if loc.get("id") is not None]
    if not location_ids:
        return [], "no_locations", rate_budget

    collected: list[dict[str, Any]] = []
    # Shopify allows comma-separated location_ids; chunk to keep URLs short.
    chunk_size = 10
    for i in range(0, len(location_ids), chunk_size):
        chunk = location_ids[i : i + chunk_size]
        try:
            page, rate_budget = _fetch_paginated_resource(
                shop=shop,
                access_token=access_token,
                api_version=api_version,
                resource="inventory_levels",
                collection_key="inventory_levels",
                query_params={"location_ids": ",".join(chunk)},
                timeout=timeout,
                rate_budget=rate_budget,
                merge_budget=merge_budget,
            )
        except ShopifyClientError as exc:
            return collected, str(exc), rate_budget
        collected.extend(page)
    return collected, None, rate_budget


def _fetch_paginated_resource(
    *,
    shop: str,
    access_token: str,
    api_version: str,
    resource: str,
    collection_key: str,
    query_params: dict[str, str],
    timeout: float,
    rate_budget: dict[str, Any] | None = None,
    merge_budget=None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    from dataruns.dcs.rate_budget import shopify_call_limit_from_headers

    params = {**query_params, "limit": str(_SHOPIFY_PAGE_LIMIT)}
    url = (
        f"https://{shop}/admin/api/{api_version}/{resource}.json"
        f"?{urlencode(params)}"
    )
    collected: list[dict[str, Any]] = []

    while url:
        page_items, url, headers = _get_resource_page(
            url=url,
            access_token=access_token,
            collection_key=collection_key,
            timeout=timeout,
        )
        collected.extend(page_items)
        if merge_budget is not None:
            rate_budget = merge_budget(
                rate_budget,
                shopify_call_limit_from_headers(headers),
            )

    return collected, rate_budget


def _get_resource_page(
    *,
    url: str,
    access_token: str,
    collection_key: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], str | None, dict[str, str]]:
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
        raise ShopifyClientError(
            f"Shopify {collection_key} response did not include '{collection_key}'."
        )
    if not isinstance(items, list):
        raise ShopifyClientError(
            f"Shopify {collection_key} field was not a JSON array."
        )
    page_items = [item for item in items if isinstance(item, dict)]
    next_url = _parse_next_link(response_headers.get("Link"))
    return page_items, next_url, response_headers


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
        raise ShopifyClientError(
            f"Shopify returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ShopifyClientError(f"Could not reach Shopify: {reason}") from exc
    except TimeoutError as exc:
        raise ShopifyClientError("Shopify request timed out.") from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ShopifyClientError("Shopify returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ShopifyClientError("Shopify response was not a JSON object.")
    return data, headers


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
        if raw:
            return raw[:500]
    except Exception:  # noqa: BLE001
        pass
    return exc.reason or "no response body"
