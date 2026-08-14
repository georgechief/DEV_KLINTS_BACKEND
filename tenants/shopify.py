"""Shopify OAuth client helpers (single store per company)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils.dateparse import parse_datetime

_SHOP_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$")
_SHOP_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")

TOKEN_MODE_EXPIRING = "offline_expiring"
TOKEN_MODE_NON_EXPIRING = "offline_non_expiring"

_REFRESH_RETRY_ATTEMPTS = 3
_REFRESH_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})

SHOPIFY_SECRET_CONFIG_KEYS = frozenset({"access_token", "refresh_token"})


class ShopifyOAuthError(Exception):
    """Raised when any step of the Shopify OAuth flow fails."""


@dataclass(frozen=True)
class ShopifyTokenBundle:
    access_token: str
    scope: str
    token_mode: str = TOKEN_MODE_NON_EXPIRING
    access_token_expires_at: str | None = None
    refresh_token: str | None = None
    refresh_token_expires_at: str | None = None


# Backward-compatible alias used by existing tests and call sites.
ShopifyToken = ShopifyTokenBundle


def normalize_shop_domain(shop: str) -> str:
    """
    Normalize user input to a `*.myshopify.com` domain.

    Accepts either the bare store handle ("acme") or the full domain
    ("acme.myshopify.com", optionally with an https:// prefix).
    Raises ShopifyOAuthError for anything else.
    """
    value = (shop or "").strip().lower()
    value = value.removeprefix("https://").removeprefix("http://").rstrip("/")
    if _SHOP_NAME_RE.match(value):
        value = f"{value}.myshopify.com"
    if not _SHOP_DOMAIN_RE.match(value):
        raise ShopifyOAuthError(
            "Enter a valid Shopify store domain, e.g. your-store.myshopify.com."
        )
    return value


def build_authorize_url(*, shop: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.SHOPIFY_API_KEY,
            "scope": settings.SHOPIFY_SCOPES,
            "redirect_uri": settings.SHOPIFY_OAUTH_REDIRECT_URI,
            "state": state,
        }
    )
    return f"https://{shop}/admin/oauth/authorize?{query}"


def verify_callback_hmac(params: dict[str, str]) -> bool:
    """
    Verify the `hmac` query parameter Shopify appends to the callback.

    Per Shopify docs: remove `hmac`, sort the remaining parameters, join as
    `key=value` pairs with `&`, and compare against HMAC-SHA256 of that
    string keyed with the app secret.
    """
    received = params.get("hmac", "")
    if not received:
        return False
    message = "&".join(
        f"{key}={value}"
        for key, value in sorted(params.items())
        if key != "hmac"
    )
    expected = hmac.new(
        settings.SHOPIFY_API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def isoformat_utc(moment: datetime | None = None) -> str:
    current = moment or datetime.now(dt_timezone.utc)
    return current.astimezone(dt_timezone.utc).isoformat()


def parse_iso_utc(value: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ShopifyOAuthError("Invalid token expiry timestamp.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def token_bundle_from_oauth_response(
    data: dict[str, Any],
    *,
    issued_at: datetime | None = None,
) -> ShopifyTokenBundle:
    """Parse Shopify access_token response into a token bundle (PRD-CONN-03 §5.1)."""
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ShopifyOAuthError("Shopify did not return an access token.")

    scope = str(data.get("scope") or "")
    expires_in = data.get("expires_in")
    refresh_token = data.get("refresh_token")
    refresh_token_expires_in = data.get("refresh_token_expires_in")

    if expires_in is not None and refresh_token:
        issued = issued_at or datetime.now(dt_timezone.utc)
        access_expires_at = issued + timedelta(seconds=int(expires_in))
        refresh_expires_at = None
        if refresh_token_expires_in is not None:
            refresh_expires_at = issued + timedelta(
                seconds=int(refresh_token_expires_in)
            )
        return ShopifyTokenBundle(
            access_token=access_token,
            scope=scope,
            token_mode=TOKEN_MODE_EXPIRING,
            access_token_expires_at=isoformat_utc(access_expires_at),
            refresh_token=str(refresh_token),
            refresh_token_expires_at=(
                isoformat_utc(refresh_expires_at) if refresh_expires_at else None
            ),
        )

    return ShopifyTokenBundle(
        access_token=access_token,
        scope=scope,
        token_mode=TOKEN_MODE_NON_EXPIRING,
    )


def token_bundle_to_config_fields(bundle: ShopifyTokenBundle) -> dict[str, Any]:
    """Map a token bundle onto connector config keys (PRD-CONN-03 §4)."""
    fields: dict[str, Any] = {
        "access_token": bundle.access_token,
        "scopes": bundle.scope,
        "token_mode": bundle.token_mode,
    }
    if bundle.access_token_expires_at:
        fields["access_token_expires_at"] = bundle.access_token_expires_at
    if bundle.refresh_token:
        fields["refresh_token"] = bundle.refresh_token
    if bundle.refresh_token_expires_at:
        fields["refresh_token_expires_at"] = bundle.refresh_token_expires_at
    return fields


def apply_token_bundle_to_config(
    config: dict[str, Any],
    bundle: ShopifyTokenBundle,
) -> dict[str, Any]:
    """Merge token bundle fields into an existing plain config dict."""
    return {
        **config,
        **token_bundle_to_config_fields(bundle),
    }


def snapshot_safe_shopify_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return snapshot-safe Shopify metadata (no secrets)."""
    return {
        key: value
        for key, value in config.items()
        if key not in SHOPIFY_SECRET_CONFIG_KEYS
    }


def resolve_token_mode(config: dict[str, Any]) -> str:
    """Resolve token mode for legacy connectors (PRD-CONN-03 §4)."""
    token_mode = config.get("token_mode")
    if token_mode in (TOKEN_MODE_EXPIRING, TOKEN_MODE_NON_EXPIRING):
        return token_mode
    if config.get("refresh_token") and config.get("access_token_expires_at"):
        return TOKEN_MODE_EXPIRING
    return TOKEN_MODE_NON_EXPIRING


def exchange_code_for_token(
    *,
    shop: str,
    code: str,
    timeout: float = 15.0,
) -> ShopifyTokenBundle:
    """POST https://{shop}/admin/oauth/access_token to redeem the grant code."""
    payload = {
        "client_id": settings.SHOPIFY_API_KEY,
        "client_secret": settings.SHOPIFY_API_SECRET,
        "code": code,
        "expiring": "1",
    }
    data = _post_form(
        f"https://{shop}/admin/oauth/access_token",
        payload=payload,
        timeout=timeout,
    )
    return token_bundle_from_oauth_response(data)


def refresh_offline_access_token(
    *,
    shop: str,
    refresh_token: str,
    timeout: float = 15.0,
) -> ShopifyTokenBundle:
    """
    POST grant_type=refresh_token (PRD-CONN-03 §6).

    https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens
    """
    payload = {
        "client_id": settings.SHOPIFY_API_KEY,
        "client_secret": settings.SHOPIFY_API_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    data = _post_form_with_retry(
        f"https://{shop}/admin/oauth/access_token",
        payload=payload,
        timeout=timeout,
    )
    return token_bundle_from_oauth_response(data)


def fetch_shop(
    *,
    shop: str,
    access_token: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """
    GET shop.json with the new token.

    Serves both as token verification and as the source of shop metadata
    (id, name) stored on the connector.
    """
    url = (
        f"https://{shop}/admin/api/"
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
    data = _read_json(request, timeout=timeout)
    shop_info = data.get("shop")
    if not isinstance(shop_info, dict):
        raise ShopifyOAuthError("Shopify shop lookup returned no shop object.")
    return shop_info


def _post_json(
    url: str,
    *,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    return _read_json(request, timeout=timeout)


def _post_form(
    url: str,
    *,
    payload: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urlencode(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    return _read_json(request, timeout=timeout, raise_retryable=False)


def _post_form_with_retry(
    url: str,
    *,
    payload: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    last_error: ShopifyOAuthError | None = None
    for attempt in range(_REFRESH_RETRY_ATTEMPTS):
        try:
            return _post_form(url, payload=payload, timeout=timeout)
        except ShopifyOAuthError as exc:
            last_error = exc
            if not _is_retryable_shopify_error(exc):
                raise
            if attempt + 1 >= _REFRESH_RETRY_ATTEMPTS:
                raise
            time.sleep(0.2 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise ShopifyOAuthError("Shopify refresh failed.")


def _is_retryable_shopify_error(exc: ShopifyOAuthError) -> bool:
    message = str(exc)
    if message.startswith("Shopify returned HTTP "):
        try:
            code = int(message.removeprefix("Shopify returned HTTP ").split(".", 1)[0])
        except ValueError:
            return False
        return code in _REFRESH_RETRYABLE_HTTP_CODES
    return (
        "Could not reach Shopify" in message
        or "timed out" in message.lower()
    )


def _read_json(
    request: urllib.request.Request,
    *,
    timeout: float,
    raise_retryable: bool = True,
) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            body = ""
        if exc.code == 401:
            if _is_inactive_refresh_token_response(body):
                raise ShopifyOAuthError(
                    "Shopify refresh token is inactive; reconnect required."
                ) from exc
            raise ShopifyOAuthError("Shopify returned HTTP 401.") from exc
        if raise_retryable and exc.code in _REFRESH_RETRYABLE_HTTP_CODES:
            raise ShopifyOAuthError(
                f"Shopify returned HTTP {exc.code}."
            ) from exc
        raise ShopifyOAuthError(
            f"Shopify returned HTTP {exc.code}."
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        raise ShopifyOAuthError(f"Could not reach Shopify: {reason}") from exc
    except TimeoutError as exc:
        raise ShopifyOAuthError("Shopify request timed out.") from exc

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ShopifyOAuthError("Shopify returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ShopifyOAuthError("Shopify response was not a JSON object.")
    return data


def _is_inactive_refresh_token_response(body: str) -> bool:
    if not body:
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return (
        data.get("error") == "invalid_request"
        and "refresh_token" in str(data.get("error_description", "")).lower()
    )
