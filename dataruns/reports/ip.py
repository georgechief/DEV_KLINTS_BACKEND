"""Client IP extraction for report download audit (PRD-RPT-01 §5.1)."""

from __future__ import annotations

import ipaddress
from typing import Any


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    token = value.strip()
    if not token:
        return None
    if token.startswith("[") and "]" in token:
        token = token[1 : token.index("]")]
    elif token.count(":") == 1 and token.rsplit(":", 1)[-1].isdigit():
        token = token.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(token)
    except ValueError:
        return None


def _is_public_ip(parsed: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def extract_client_ip(request: Any) -> tuple[str | None, str]:
    """
    Return (ip_address, ip_resolution).

    Prefer first public X-Forwarded-For hop, else REMOTE_ADDR.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    forwarded_candidates: list[str] = []
    if isinstance(forwarded, str) and forwarded.strip():
        forwarded_candidates = [part.strip() for part in forwarded.split(",") if part.strip()]
        for token in forwarded_candidates:
            parsed = _parse_ip(token)
            if parsed is not None and _is_public_ip(parsed):
                return str(parsed), "x_forwarded_for"

    remote = request.META.get("REMOTE_ADDR")
    if isinstance(remote, str) and remote.strip():
        parsed = _parse_ip(remote)
        if parsed is not None:
            return str(parsed), "remote_addr"
        return remote.strip(), "remote_addr"

    if forwarded_candidates:
        parsed = _parse_ip(forwarded_candidates[0])
        if parsed is not None:
            return str(parsed), "x_forwarded_for"

    return None, "unknown"
