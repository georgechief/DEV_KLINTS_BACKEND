"""SSRF hardening for user-supplied Manago verify / connector endpoints (Gate B P1)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings

# Official Manago API v2 app hosts accepted for server-side credential verify.
# Hostname from MANAGO_API_BASE_URL is always included at runtime.
_DEFAULT_MANAGO_API_HOSTS = frozenset(
    {
        "app.manago.ai",
        "app2.manago.ai",
        "app3.manago.ai",
        "app4.manago.ai",
        "app5.manago.ai",
    }
)


class ManagoEndpointError(ValueError):
    """User-facing endpoint rejection (HTTPS / host allowlist / private IP / redirect)."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse to follow redirects — Location could point at an internal host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ManagoEndpointError(
            "Manago endpoint returned a redirect; redirects are not allowed."
        )


def allowed_manago_api_hosts() -> frozenset[str]:
    hosts = set(_DEFAULT_MANAGO_API_HOSTS)
    configured = getattr(settings, "MANAGO_API_BASE_URL", "") or ""
    parsed = urlparse(
        configured
        if "://" in configured
        else f"https://{configured.strip()}"
    )
    if parsed.hostname:
        hosts.add(parsed.hostname.lower())
    extra = getattr(settings, "MANAGO_ALLOWED_API_HOSTS", None) or ()
    for item in extra:
        if isinstance(item, str) and item.strip():
            hosts.add(item.strip().lower())
    return frozenset(hosts)


def _is_blocked_ip(parsed: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _assert_hostname_resolves_public(hostname: str) -> None:
    try:
        infos = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ManagoEndpointError(
            "Could not resolve Manago endpoint host."
        ) from exc
    if not infos:
        raise ManagoEndpointError("Could not resolve Manago endpoint host.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_blocked_ip(ip):
            raise ManagoEndpointError(
                "Endpoint resolves to a private or internal address."
            )


def normalize_and_validate_manago_endpoint(endpoint: str) -> str:
    """
    Return canonical ``https://<allowed-host>`` or raise ManagoEndpointError.

    Rules (Gate B / Gate C P1):
    - HTTPS only
    - Hostname must be an exact allowlisted Manago API host
    - No userinfo, non-default ports, or IP-literal hosts
    - DNS must resolve only to public addresses
    """
    raw = (endpoint or "").strip()
    if not raw:
        raise ManagoEndpointError("Endpoint is required.")

    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)

    if parsed.scheme.lower() != "https":
        raise ManagoEndpointError("Endpoint must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ManagoEndpointError("Endpoint must not include credentials.")
    if parsed.port is not None and parsed.port != 443:
        raise ManagoEndpointError("Endpoint must use the default HTTPS port.")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ManagoEndpointError("Endpoint host is required.")

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ManagoEndpointError(
            "Endpoint must be an official Manago hostname, not an IP address."
        )

    if host not in allowed_manago_api_hosts():
        raise ManagoEndpointError(
            "Endpoint must be an official Manago host "
            "(e.g. app.manago.ai or app2.manago.ai)."
        )

    _assert_hostname_resolves_public(host)
    return f"https://{host}"


def manago_urlopen(request: Request, *, timeout: float):
    """urlopen that never follows redirects."""
    opener = build_opener(_NoRedirectHandler)
    return opener.open(request, timeout=timeout)
