"""FD-04 rate-limit headroom — measure safe request budgets per connector."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_shopify_call_limit(header_value: str | None) -> dict[str, int] | None:
    """
    Parse ``X-Shopify-Shop-Api-Call-Limit`` / ``X-Shopify-Api-Call-Limit``.

    Shopify format: ``used/limit`` e.g. ``32/40``.
    """
    if not isinstance(header_value, str) or "/" not in header_value:
        return None
    left, _, right = header_value.strip().partition("/")
    try:
        used = int(left.strip())
        limit = int(right.strip())
    except ValueError:
        return None
    if limit <= 0 or used < 0:
        return None
    remaining = max(limit - used, 0)
    return {"used": used, "limit": limit, "remaining": remaining}


def shopify_call_limit_from_headers(headers: dict[str, str]) -> dict[str, int] | None:
    if not headers:
        return None
    # Header names are case-insensitive; urllib may preserve mixed case.
    lowered = {str(k).lower(): v for k, v in headers.items()}
    for key in (
        "x-shopify-shop-api-call-limit",
        "x-shopify-api-call-limit",
        "x-shopify-call-limit",
    ):
        parsed = parse_shopify_call_limit(lowered.get(key))
        if parsed is not None:
            return parsed
    return None


def merge_shopify_call_limit(
    current: dict[str, Any] | None,
    observed: dict[str, int] | None,
) -> dict[str, Any] | None:
    """Keep the observation with the least remaining headroom."""
    if observed is None:
        return current
    candidate = {
        "platform": "shopify",
        "used": observed["used"],
        "limit": observed["limit"],
        "remaining": observed["remaining"],
        "hit_rate_limit": observed["remaining"] <= 0,
        "headroom_ok": observed["remaining"] > 0,
        "source": "header",
        "measured_at": _utcnow_iso(),
    }
    if current is None:
        return candidate
    cur_remaining = current.get("remaining")
    if not isinstance(cur_remaining, int) or observed["remaining"] < cur_remaining:
        return candidate
    return current


def build_manago_rate_budget(
    *,
    requests_sampled: int,
    requests_ok: int,
    hit_rate_limit: bool,
    source: str = "import",
) -> dict[str, Any]:
    """Manago has no public call-limit header — budget from controlled samples."""
    headroom_ok = (not hit_rate_limit) and requests_ok > 0
    return {
        "platform": "manago_ai",
        "requests_sampled": max(requests_sampled, 0),
        "requests_ok": max(requests_ok, 0),
        "safe_request_budget": max(requests_ok, 0),
        "hit_rate_limit": bool(hit_rate_limit),
        "headroom_ok": headroom_ok,
        "used": None,
        "limit": None,
        "remaining": None,
        "source": source,
        "measured_at": _utcnow_iso(),
    }


def budget_has_headroom(budget: dict[str, Any] | None) -> bool:
    if not isinstance(budget, dict) or not budget:
        return False
    if budget.get("hit_rate_limit") is True:
        return False
    if "headroom_ok" in budget:
        return bool(budget.get("headroom_ok"))
    remaining = budget.get("remaining")
    if isinstance(remaining, int):
        return remaining > 0
    return False


def measure_shopify_rate_budget(
    *,
    shop: str,
    access_token: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Controlled single-read probe; capture Shopify call-limit header."""
    import urllib.error
    import urllib.request

    from django.conf import settings

    from tenants.shopify import normalize_shop_domain

    shop_domain = normalize_shop_domain(shop)
    url = (
        f"https://{shop_domain}/admin/api/"
        f"{settings.SHOPIFY_API_VERSION}/shop.json"
    )
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "X-Shopify-Access-Token": access_token,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            headers = {k: v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return {
                "platform": "shopify",
                "used": None,
                "limit": None,
                "remaining": 0,
                "hit_rate_limit": True,
                "headroom_ok": False,
                "source": "probe",
                "measured_at": _utcnow_iso(),
                "error": f"HTTP 429: {exc.reason}",
            }
        raise

    observed = shopify_call_limit_from_headers(headers)
    if observed is None:
        # Probe succeeded but header missing — still evidence of headroom.
        return {
            "platform": "shopify",
            "used": None,
            "limit": None,
            "remaining": None,
            "requests_sampled": 1,
            "requests_ok": 1,
            "safe_request_budget": 1,
            "hit_rate_limit": False,
            "headroom_ok": True,
            "source": "probe",
            "measured_at": _utcnow_iso(),
        }
    budget = merge_shopify_call_limit(None, observed)
    assert budget is not None
    budget["source"] = "probe"
    return budget


def measure_manago_rate_budget(
    *,
    client_id: str,
    api_secret: str,
    endpoint: str | None = None,
    burst: int = 3,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """
    Controlled burst against ``listByClient`` (Excel: measure throttle responses).
    """
    from tenants.manago import list_users_by_client, resolve_manago_api_base_url

    api_base = resolve_manago_api_base_url(
        {"base_url": endpoint} if endpoint else None
    )
    sampled = 0
    ok = 0
    hit = False
    last_error: str | None = None
    for _ in range(max(burst, 1)):
        sampled += 1
        try:
            data = list_users_by_client(
                client_id=client_id,
                api_secret=api_secret,
                endpoint=api_base,
                timeout=timeout,
            )
            if data.get("success") is False:
                last_error = str(data.get("message") or "Manago rejected credentials")
                break
            ok += 1
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "429" in message or "rate limit" in message.lower():
                hit = True
                last_error = message
                break
            last_error = message
            break

    budget = build_manago_rate_budget(
        requests_sampled=sampled,
        requests_ok=ok,
        hit_rate_limit=hit,
        source="probe",
    )
    if last_error and not hit and ok == 0:
        budget["error"] = last_error
        budget["headroom_ok"] = False
    return budget


def rate_budget_from_health(health_report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(health_report, dict):
        return None
    fetch = health_report.get("fetch")
    if not isinstance(fetch, dict):
        return None
    budget = fetch.get("rate_budget")
    return budget if isinstance(budget, dict) and budget else None
