"""Company website HTML scrape + SalesManago / Manago tracker markers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 12
MAX_HTML_BYTES = 2 * 1024 * 1024
USER_AGENT = "KlintsDCS/1.0 (+https://klints.ai; FD-07 website tracker check)"

# Marker keys returned by find_salesmanago_markers (PRD tracker table).
PRIMARY_MARKERS: tuple[str, ...] = (
    "www.salesmanago.pl",
    "salesmanago.pl/static/sm.js",
    "www.salesmanago.com",
    "app.salesmanago.com",
    "app.manago.ai",
    "www.manago.ai",
    "manago.ai/static",
    "_smid",
    "SalesmanagoObject",
    "ManagoObject",
)


@dataclass(frozen=True)
class WebsiteScrapeResult:
    ok: bool
    final_url: str | None = None
    status_code: int | None = None
    html: str | None = None
    error: str | None = None


def normalize_company_domain(raw: str | None) -> str | None:
    """Lowercase host; strip scheme and trailing slash. Reject empty/localhost."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        return None
    return host


def website_url_for_domain(host: str) -> str:
    return f"https://{host}"


def find_salesmanago_markers(html: str) -> list[str]:
    """Case-insensitive substring scan; return matched marker keys."""
    if not html:
        return []
    lowered = html.lower()
    matched: list[str] = []
    for marker in PRIMARY_MARKERS:
        if marker.lower() in lowered:
            matched.append(marker)
    # Combined rule: sm.js + salesmanago / manago somewhere in document
    if "sm.js" in lowered and ("salesmanago" in lowered or "manago.ai" in lowered):
        if "sm.js+salesmanago" not in matched:
            matched.append("sm.js+salesmanago")
    return matched


def snippet_around_markers(html: str, markers: list[str], *, limit: int = 280) -> str:
    if not html or not markers:
        return ""
    lowered = html.lower()
    positions = []
    for marker in markers:
        idx = lowered.find(marker.lower().split("+")[0])
        if idx >= 0:
            positions.append(idx)
    if not positions:
        return html[:limit]
    start = max(0, min(positions) - 40)
    excerpt = html[start : start + limit]
    return re.sub(r"\s+", " ", excerpt).strip()


def is_storefront_password_wall(
    *,
    final_url: str | None,
    html: str | None,
) -> bool:
    """True when Shopify (or similar) password gate hides the real theme/scripts."""
    url = (final_url or "").lower()
    if "/password" in url:
        return True
    text = (html or "").lower()
    if not text:
        return False
    if "storefront_password" in text:
        return True
    if 'name="password"' in text and ("shopify" in text or "myshopify" in text):
        return True
    return False


def scrape_company_website(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Any | None = None,
) -> WebsiteScrapeResult:
    """
    HTTP GET homepage HTML (no JS execution).

    ``opener`` is an optional callable(Request, timeout=...) -> response
    for tests (defaults to urllib.request.urlopen).
    """
    open_fn = opener or urlopen
    request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with open_fn(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            final = getattr(response, "geturl", lambda: url)()
            raw = response.read(MAX_HTML_BYTES + 1)
            if len(raw) > MAX_HTML_BYTES:
                return WebsiteScrapeResult(
                    ok=False,
                    final_url=final,
                    status_code=int(status) if status else None,
                    error="response_too_large",
                )
            charset = "utf-8"
            content_type = ""
            if hasattr(response, "headers") and response.headers:
                content_type = response.headers.get_content_charset() or ""
                charset = content_type or "utf-8"
            html = raw.decode(charset, errors="replace")
            return WebsiteScrapeResult(
                ok=True,
                final_url=final,
                status_code=int(status) if status else 200,
                html=html,
            )
    except HTTPError as exc:
        body = b""
        try:
            body = exc.read(MAX_HTML_BYTES)
        except Exception:  # noqa: BLE001
            pass
        html = body.decode("utf-8", errors="replace") if body else None
        return WebsiteScrapeResult(
            ok=False,
            final_url=url,
            status_code=int(exc.code),
            html=html,
            error=f"http_{exc.code}",
        )
    except (URLError, TimeoutError, OSError) as exc:
        return WebsiteScrapeResult(
            ok=False,
            final_url=url,
            error=str(exc) or "unreachable",
        )


def scrape_with_http_fallback(
    host: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Any | None = None,
) -> WebsiteScrapeResult:
    """Prefer https; on connection failure retry http once."""
    https_url = website_url_for_domain(host)
    result = scrape_company_website(https_url, timeout=timeout, opener=opener)
    if result.ok or (result.status_code is not None and result.status_code < 500):
        return result
    if result.error and result.status_code is None:
        http_url = f"http://{host}"
        return scrape_company_website(http_url, timeout=timeout, opener=opener)
    return result
