"""PrivacyGate — ensure* before every model call (PRD-AI-01 §4).

Fail closed: if PII / secrets remain after sanitize → deny (no model call).
Gate results log metadata only — never the rejected payload body.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from dataruns.ai.constants import MAX_MISMATCH_ROWS, MAX_STRING_CHARS, POLICY_VERSION

logger = logging.getLogger(__name__)

# --- Patterns (never send matches to the model) ---

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
# E.164-ish / common phone forms
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?!\w)"
)
# Contact-like UUIDs (standard UUID v1–v5)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")
_AUTH_HEADER_RE = re.compile(
    r"(?i)\bAuthorization\s*[:=]\s*Bearer\s+[A-Za-z0-9._\-]+"
)
_SECRET_KV_RE = re.compile(
    r"(?i)\b("
    r"access_token|refresh_token|api_key|api_secret|password|authorization|"
    r"client_secret|webhook_secret|oauth"
    r")\s*[:=]\s*([^\s,;]+)"
)
_SHOPIFY_TOKEN_RE = re.compile(r"\b(shpat_|shprt_|shpss_)[A-Za-z0-9]+")

# Keys that must never appear (case-insensitive) on mismatch / evidence objects
_FORBIDDEN_VALUE_KEYS = frozenset(
    {
        "value",
        "raw",
        "sample",
        "email",
        "phone",
        "name",
        "address",
        "externalid",
        "contactid",
        "smclient",
        "authorization",
        "password",
        "token",
        "apikey",
        "api_key",
    }
)

_REASON_PASS = "pass"
_REASON_PII_REMAINING = "pii_remaining"
_REASON_SECRET_REMAINING = "secret_remaining"
_REASON_EMPTY = "empty_context"
_REASON_INVALID = "invalid_context"


@dataclass(frozen=True)
class GateResult:
    """Outcome of ensure_safe_context — never include rejected payload in logs."""

    ok: bool
    reason_code: str
    policy_version: str = POLICY_VERSION
    context: dict[str, Any] | None = None

    @property
    def gate(self) -> str:
        return "pass" if self.ok else "deny"


def _cap_str(value: str, *, limit: int = MAX_STRING_CHARS) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def scrub_text(value: str) -> str:
    """Regex-scrub emails, phones, UUIDs, Bearer tokens, secret kv pairs."""
    text = value
    # Authorization: Bearer … before generic authorization= kv scrub
    text = _AUTH_HEADER_RE.sub("Authorization=****", text)
    text = _BEARER_RE.sub("Bearer ****", text)
    text = _SECRET_KV_RE.sub(r"\1=****", text)
    text = _SHOPIFY_TOKEN_RE.sub(r"\1****", text)
    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _UUID_RE.sub("[redacted-id]", text)
    # Phones last — looser pattern; avoid destroying pure numeric aggregates
    # by only scrubbing when separators or leading + are present, or length>=10 digits.
    text = _PHONE_RE.sub(_phone_replacer, text)
    return text


def _phone_replacer(match: re.Match[str]) -> str:
    token = match.group(0)
    digits = re.sub(r"\D", "", token)
    if len(digits) < 10 and "+" not in token and not re.search(r"[\s().-]", token):
        return token
    if len(digits) < 7:
        return token
    return "[redacted-phone]"


def text_still_has_pii(value: str) -> bool:
    if _EMAIL_RE.search(value):
        return True
    if _BEARER_RE.search(value):
        return True
    if _SECRET_KV_RE.search(value):
        return True
    if _SHOPIFY_TOKEN_RE.search(value):
        return True
    if _UUID_RE.search(value):
        return True
    # Phone: require enough digits to avoid false positives on scores like "69.28"
    for match in _PHONE_RE.finditer(value):
        token = match.group(0)
        digits = re.sub(r"\D", "", token)
        if len(digits) >= 10 or (token.startswith("+") and len(digits) >= 8):
            return True
    return False


def sanitize_mismatch_row(row: Any) -> dict[str, str] | None:
    """Emit {path, kind, side} only — drop value/raw/sample (PRD §4.3.1)."""
    if not isinstance(row, dict):
        return None
    path = row.get("path") or row.get("field") or row.get("key") or ""
    kind = row.get("kind") or row.get("type") or row.get("mismatch_kind") or ""
    side = row.get("side") or row.get("system") or row.get("source") or ""
    if not isinstance(path, str):
        path = str(path) if path is not None else ""
    if not isinstance(kind, str):
        kind = str(kind) if kind is not None else ""
    if not isinstance(side, str):
        side = str(side) if side is not None else ""
    path = _cap_str(scrub_text(path), limit=200)
    kind = _cap_str(scrub_text(kind), limit=64)
    side = _cap_str(scrub_text(side), limit=64)
    if not path and not kind:
        return None
    return {"path": path or "unknown", "kind": kind or "unknown", "side": side or ""}


def sanitize_mismatch_list(rows: Any, *, limit: int = MAX_MISMATCH_ROWS) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        # Explicitly reject objects that still carry forbidden value keys
        # before projecting — those values must never reach the model.
        if isinstance(row, dict):
            lowered = {str(k).lower().replace("-", "_") for k in row}
            # If value/raw/sample present we still project path/kind/side only
            # (drop values) — that is the sanitizer job, not a deny by itself.
            _ = lowered & _FORBIDDEN_VALUE_KEYS
        cleaned = sanitize_mismatch_row(row)
        if cleaned is None:
            continue
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def strip_domain_to_hostname(domain: str | None) -> str | None:
    """Optional: registrable hostname only — no path/query (PRD §4.2)."""
    token = (domain or "").strip()
    if not token:
        return None
    lower = token.lower()
    if lower in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return None
    if "://" not in token:
        token = "https://" + token
    try:
        host = urlparse(token).hostname
    except Exception:
        return None
    if not host or host.lower() in {"localhost", "127.0.0.1"}:
        return None
    return host.lower()


def _walk_scrub_strings(obj: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return None
    if isinstance(obj, str):
        return _cap_str(scrub_text(obj))
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, list):
        return [_walk_scrub_strings(item, depth=depth + 1) for item in obj[:50]]
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            key_l = str(key).lower().replace("-", "_")
            if key_l in _FORBIDDEN_VALUE_KEYS or key_l in {
                "value",
                "raw",
                "sample",
                "email",
                "phone",
                "authorization",
            }:
                continue
            out[str(key)] = _walk_scrub_strings(value, depth=depth + 1)
        return out
    return _cap_str(scrub_text(str(obj)))


def _scan_for_leaks(obj: Any, *, depth: int = 0) -> str | None:
    """Return reason_code if PII/secrets remain, else None."""
    if depth > 8:
        return None
    if isinstance(obj, str):
        if text_still_has_pii(obj):
            if _BEARER_RE.search(obj) or _SECRET_KV_RE.search(obj) or _SHOPIFY_TOKEN_RE.search(obj):
                return _REASON_SECRET_REMAINING
            return _REASON_PII_REMAINING
        return None
    if isinstance(obj, list):
        for item in obj:
            hit = _scan_for_leaks(item, depth=depth + 1)
            if hit:
                return hit
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_l = str(key).lower().replace("-", "_")
            if key_l in {"value", "raw", "sample"}:
                return _REASON_PII_REMAINING
            hit = _scan_for_leaks(value, depth=depth + 1)
            if hit:
                return hit
        return None
    return None


def _policy_version_from_context(raw_context: dict[str, Any] | None) -> str:
    if isinstance(raw_context, dict):
        token = str(raw_context.get("policy_version") or "").strip()
        if token:
            return token
    return POLICY_VERSION


def ensure_safe_context(raw_context: dict[str, Any] | None) -> GateResult:
    """
    Sanitize + re-scan. FAIL CLOSED if leaks remain.

    Callers must only pass allowlisted shapes; this gate is the last line of defense.
    """
    policy_version = _policy_version_from_context(
        raw_context if isinstance(raw_context, dict) else None
    )
    if raw_context is None:
        _log_gate(ok=False, reason=_REASON_EMPTY, policy_version=policy_version)
        return GateResult(ok=False, reason_code=_REASON_EMPTY, policy_version=policy_version)
    if not isinstance(raw_context, dict):
        _log_gate(ok=False, reason=_REASON_INVALID, policy_version=policy_version)
        return GateResult(ok=False, reason_code=_REASON_INVALID, policy_version=policy_version)
    if not raw_context:
        _log_gate(ok=False, reason=_REASON_EMPTY, policy_version=policy_version)
        return GateResult(ok=False, reason_code=_REASON_EMPTY, policy_version=policy_version)

    # Project mismatches first so values never survive into the scrub walk.
    working = dict(raw_context)
    if "mismatches" in working:
        working["mismatches"] = sanitize_mismatch_list(working.get("mismatches"))
    if "evidence" in working:
        # Evidence may be a list of mismatch-like rows — same projection.
        working["evidence"] = sanitize_mismatch_list(working.get("evidence"))
    if "finding_summary" in working and isinstance(working["finding_summary"], dict):
        summary = dict(working["finding_summary"])
        if "mismatches" in summary:
            summary["mismatches"] = sanitize_mismatch_list(summary.get("mismatches"))
        working["finding_summary"] = summary

    cleaned = _walk_scrub_strings(working)
    if not isinstance(cleaned, dict):
        _log_gate(ok=False, reason=_REASON_INVALID, policy_version=policy_version)
        return GateResult(
            ok=False, reason_code=_REASON_INVALID, policy_version=policy_version
        )

    leak = _scan_for_leaks(cleaned)
    if leak:
        _log_gate(ok=False, reason=leak, policy_version=policy_version)
        return GateResult(ok=False, reason_code=leak, policy_version=policy_version)

    _log_gate(ok=True, reason=_REASON_PASS, policy_version=policy_version)
    return GateResult(
        ok=True,
        reason_code=_REASON_PASS,
        policy_version=policy_version,
        context=cleaned,
    )


def _log_gate(*, ok: bool, reason: str, policy_version: str = POLICY_VERSION) -> None:
    # Metadata only — never log payload body (PRD §4.3.5).
    logger.info(
        "ai_privacy_gate gate=%s reason=%s policy=%s",
        "pass" if ok else "deny",
        reason,
        policy_version,
    )
