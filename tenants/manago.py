"""SalesManago / Manago.ai API v2 client helpers."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from django.conf import settings


@dataclass(frozen=True)
class ManagoVerifyResult:
    valid: bool
    message: str


def build_auth_payload(*, client_id: str, api_secret: str) -> dict[str, Any]:
    """
    Build Manago API v2 auth fields.

    sha = lowercase hex of SHA1(apiKey + clientId + apiSecret)
    requestTime = unix timestamp in milliseconds
    """
    api_key = secrets.token_urlsafe(24)
    request_time = int(time.time() * 1000)
    sha = hashlib.sha1(
        f"{api_key}{client_id}{api_secret}".encode("utf-8")
    ).hexdigest()
    return {
        "clientId": client_id,
        "apiKey": api_key,
        "requestTime": request_time,
        "sha": sha,
    }


def _normalize_endpoint(endpoint: str) -> str:
    return endpoint.strip().rstrip("/")


def resolve_manago_api_base_url(config: dict[str, Any] | None = None) -> str:
    """
    Return the Manago API base URL.

    Uses stored connector ``base_url`` / ``endpoint`` when present (legacy
    connectors), otherwise ``settings.MANAGO_API_BASE_URL``.
    """
    if config:
        for key in ("base_url", "endpoint"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_endpoint(value)
    return _normalize_endpoint(settings.MANAGO_API_BASE_URL)


def list_users_by_client(
    *,
    client_id: str,
    api_secret: str,
    endpoint: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """
    POST {endpoint}/api/user/listByClient with Manago v2 auth.

    Returns the parsed JSON body. Raises urllib.error.URLError / TimeoutError /
    ValueError on transport or parse failures.
    """
    base = _normalize_endpoint(endpoint)
    url = urljoin(f"{base}/", "api/user/listByClient")
    payload = build_auth_payload(client_id=client_id, api_secret=api_secret)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Manago response was not a JSON object.")
    return data


def verify_credentials(
    *,
    client_id: str,
    api_secret: str,
    endpoint: str | None = None,
) -> ManagoVerifyResult:
    """
    Verify Manago credentials without persisting anything.

    Treats Manago ``success: true`` as valid.
    Uses ``settings.MANAGO_API_BASE_URL`` unless ``endpoint`` is passed explicitly.
    """
    api_base_url = resolve_manago_api_base_url(
        {"base_url": endpoint} if endpoint else None
    )
    try:
        data = list_users_by_client(
            client_id=client_id,
            api_secret=api_secret,
            endpoint=api_base_url,
        )
    except urllib.error.HTTPError as exc:
        detail = _http_error_message(exc)
        return ManagoVerifyResult(valid=False, message=detail)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        return ManagoVerifyResult(
            valid=False,
            message=f"Could not reach Manago endpoint: {reason}",
        )
    except TimeoutError:
        return ManagoVerifyResult(
            valid=False,
            message="Manago request timed out.",
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return ManagoVerifyResult(
            valid=False,
            message=f"Invalid Manago response: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — surface unexpected client errors
        return ManagoVerifyResult(
            valid=False,
            message=f"Manago verification failed: {exc}",
        )

    if data.get("success") is True:
        return ManagoVerifyResult(
            valid=True,
            message="Credentials verified",
        )

    message = _manago_error_message(data)
    return ManagoVerifyResult(valid=False, message=message)


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        if isinstance(data, dict):
            return _manago_error_message(data)
    except Exception:  # noqa: BLE001
        pass
    return f"Manago returned HTTP {exc.code}."


def _manago_error_message(data: dict[str, Any]) -> str:
    message = data.get("message")
    if isinstance(message, list) and message:
        parts = [str(item) for item in message if item is not None]
        if parts:
            return "; ".join(parts)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "Manago rejected the credentials."
