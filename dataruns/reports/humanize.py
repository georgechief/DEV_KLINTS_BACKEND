"""Human-readable copy helpers for assessment PDF (PRD-RPT-01B).

Named humanize.py (not copy.py) so we do not shadow Python's stdlib copy module.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

_PRESERVED_TITLE = {
    "manago.ai": "Manago.ai",
    "manago": "Manago",
    "shopify": "Shopify",
    "vip": "VIP",
    "utm": "UTM",
    "api": "API",
    "erp": "ERP",
    "sms": "SMS",
    "dcs": "DCS",
    "id": "ID",
}

_CHECK_ID_RE = re.compile(r"^[A-Z]{2}-\d{2}$", re.I)
_LOCALHOST_RE = re.compile(r"^(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$", re.I)

_PCT_RE = re.compile(
    r"(?P<label>[A-Za-z0-9_ ]+?)[=:](?P<pct>\d+(?:\.\d+)?)\s*%",
    re.I,
)
_RATE_RE = re.compile(
    r"(?P<label>[A-Za-z0-9_ ]*?rate)\s*=\s*(?P<pct>\d+(?:\.\d+)?)\s*%",
    re.I,
)
_SHARE_RE = re.compile(
    r"(?P<label>[A-Za-z0-9_ ]*?share)\s*=\s*(?P<pct>\d+(?:\.\d+)?)\s*%",
    re.I,
)
_CLUSTERS_RE = re.compile(r"clusters?\s*=\s*(?P<n>\d+)", re.I)
_GAPS_RE = re.compile(r"gaps\s*=\s*\[(?P<body>[^\]]*)\]", re.I)
_CLUSTER_TRUE_RE = re.compile(r"\bcluster\s*=\s*True\b", re.I)
_PROVENANCE_RE = re.compile(
    r"provenance_share\s*=\s*(?P<pct>\d+(?:\.\d+)?)\s*%"
    r".*?weak_or_missing\s*=\s*(?P<weak>\d+)\s*/\s*(?P<total>\d+)",
    re.I | re.S,
)
_EQ_KV_RE = re.compile(r"\b([a-z][a-z0-9_]*)\s*=\s*([^\s,;]+)", re.I)


def _title_case_token(word: str) -> str:
    bare = re.sub(r"[.,;:]+$", "", word)
    suffix = word[len(bare) :]
    lower = bare.lower()
    if lower in _PRESERVED_TITLE:
        return _PRESERVED_TITLE[lower] + suffix
    if _CHECK_ID_RE.match(bare):
        return bare.upper() + suffix
    if "-" in bare:
        return "-".join(_title_case_token(part) for part in bare.split("-")) + suffix
    if not bare:
        return word
    return bare[:1].upper() + bare[1:].lower() + suffix


def format_customer_title(raw: str | None) -> str:
    """FE-09 spirit: Title Case short names; never leave fully lowercase."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return "Data consistency issue"
    words = [w for w in trimmed.split() if w]
    is_all_lower = trimmed == trimmed.lower() and re.search(r"[a-z]", trimmed)
    if not is_all_lower:
        first = trimmed[0]
        if first == first.lower() and first.isalpha():
            return first.upper() + trimmed[1:]
        return trimmed
    if len(words) <= 8:
        return " ".join(_title_case_token(w) for w in words)
    head, *tail = words
    return " ".join([_title_case_token(head), *[w.lower() for w in tail]])


def format_systems_label(raw: str | None) -> str:
    token = (raw or "").strip()
    if not token:
        return ""
    parts = re.split(r"\s*(?:·|/|,|&|\+|vs\.?)\s*", token, flags=re.I)
    friendly: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        lower = cleaned.lower().replace(" ", "")
        if "manago" in lower:
            friendly.append("Manago.ai")
        elif "shopify" in lower:
            friendly.append("Shopify")
        elif "erp" in lower:
            friendly.append("ERP")
        else:
            friendly.append(format_customer_title(cleaned))
    # Preserve order, unique
    seen: set[str] = set()
    out: list[str] = []
    for item in friendly:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return " · ".join(out)


def _fmt_pct(value: float) -> str:
    if abs(value - 50.0) < 0.6:
        return "half"
    if abs(value - round(value)) < 0.05:
        return f"{int(round(value))}%"
    return f"~{value:.0f}%"


def _pct_phrase(value: float) -> str:
    if abs(value - 50.0) < 0.6:
        return "About half"
    return f"About {_fmt_pct(value)}"


def _gap_words(body: str) -> str:
    tokens = [t.strip(" '\"") for t in body.split(",") if t.strip(" '\"")]
    if not tokens:
        return "more data"
    labels = []
    for token in tokens:
        if token.lower() == "history":
            labels.append("history")
        else:
            labels.append(token.replace("_", " "))
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def humanize_check_detail(raw: str | None) -> str:
    """
    Turn executor-style detail into plain client copy.
    Heuristic only — no LLM.
    """
    text = (raw or "").strip()
    if not text:
        return ""

    # Provenance / consent unevidenced
    prov = _PROVENANCE_RE.search(text)
    if prov or "Unevidenced opt-ins" in text or "provenance_share" in text.lower():
        pct = float(prov.group("pct")) if prov else 0.0
        weak = prov.group("weak") if prov else None
        total = prov.group("total") if prov else None
        if weak and total:
            return (
                f"Consent provenance is weak: {_fmt_pct(pct)} evidenced; "
                f"{weak} of {total} opt-ins lack solid evidence."
            )
        return "Consent provenance is weak or missing for opt-ins."

    # Duplicate purchase
    if "Duplicate PURCHASE" in text or (
        "duplicate" in text.lower() and "purchase" in text.lower()
    ):
        rate = _RATE_RE.search(text) or _PCT_RE.search(text)
        clusters = _CLUSTERS_RE.search(text)
        pct = float(rate.group("pct")) if rate else None
        n = clusters.group("n") if clusters else None
        if pct is not None and n:
            return f"{_pct_phrase(pct)} of purchases look duplicated ({n} clusters)."
        if pct is not None:
            return f"{_pct_phrase(pct)} of purchases look duplicated."
        return "Purchase events look duplicated across orders."

    # Deliverability (before dead-state — messages often include dead_share)
    if "deliverability" in text.lower():
        rate = _RATE_RE.search(text) or _SHARE_RE.search(text) or _PCT_RE.search(text)
        pct = float(rate.group("pct")) if rate else None
        if pct is not None:
            shown = "half" if abs(pct - 50.0) < 0.6 else _fmt_pct(pct)
            if shown == "half":
                return "Email deliverability looks damaged (about half dead or damaged)."
            return f"Email deliverability looks damaged ({shown} dead or damaged)."
        return "Email deliverability posture looks damaged."

    # Dead-state / cluster
    if "dead-state" in text.lower() or "dead_share" in text.lower() or _CLUSTER_TRUE_RE.search(text):
        share = _SHARE_RE.search(text) or _PCT_RE.search(text)
        pct = float(share.group("pct")) if share else None
        if _CLUSTER_TRUE_RE.search(text) and pct is not None:
            return (
                f"Dead-state contacts are elevated ({_fmt_pct(pct)}) and spike on one day."
            )
        if pct is not None:
            return f"Dead-state contact share is elevated ({_fmt_pct(pct)})."
        if _CLUSTER_TRUE_RE.search(text):
            return "Dead-state contacts spike on one day."

    # Baseline / gaps
    gaps = _GAPS_RE.search(text)
    if gaps or "Baseline not computable" in text:
        need = _gap_words(gaps.group("body")) if gaps else "more history"
        if need == "history":
            need = "more history"
        return f"Baseline needs {need}."

    # Generic: scrub Python-ish key=value and list reprs
    cleaned = text
    cleaned = _GAPS_RE.sub(
        lambda m: f"gaps: {_gap_words(m.group('body'))}", cleaned
    )
    cleaned = _CLUSTER_TRUE_RE.sub("clustered on one day", cleaned)
    cleaned = _RATE_RE.sub(
        lambda m: f"{m.group('label').replace('_', ' ').strip()} {_fmt_pct(float(m.group('pct')))}",
        cleaned,
    )
    cleaned = _SHARE_RE.sub(
        lambda m: f"{m.group('label').replace('_', ' ').strip()} {_fmt_pct(float(m.group('pct')))}",
        cleaned,
    )
    cleaned = _PCT_RE.sub(
        lambda m: f"{m.group('label').strip().replace('_', ' ')} {_fmt_pct(float(m.group('pct')))}",
        cleaned,
    )
    cleaned = _EQ_KV_RE.sub(
        lambda m: f"{m.group(1).replace('_', ' ')} {m.group(2)}", cleaned
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;")
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned and not cleaned.endswith("."):
        cleaned += "."
    return cleaned


def format_display_domain(domain: str | None) -> str | None:
    token = (domain or "").strip()
    if not token or _LOCALHOST_RE.match(token):
        return None
    return token


def format_generated_at(raw: str | None) -> str:
    """`12 Aug 2026, 14:19 UTC` — not full ISO with microseconds."""
    if not raw or not isinstance(raw, str):
        return ""
    parsed = parse_datetime(raw.strip())
    if parsed is None:
        return raw.strip()
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    else:
        parsed = parsed.astimezone(dt_timezone.utc)
    return parsed.strftime("%d %b %Y, %H:%M UTC")


def format_impact_cell(
    amount: Any,
    currency: Any,
    *,
    empty: str = "-",
) -> str:
    if amount is None:
        return empty
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return empty
    if value == 0:
        return empty
    code = str(currency).strip().upper() if currency else ""
    if value.is_integer():
        amount_s = str(int(value))
    else:
        amount_s = f"{value:.2f}"
    if code and re.fullmatch(r"[A-Z]{3}", code):
        return f"{code} {amount_s}"
    return amount_s


def connector_strip_labels(connectors: list[dict[str, str]]) -> str:
    """
    Build `Manago connected · Shopify connected · ERP unknown`.
    Each item: {"key": "manago"|"shopify"|"erp", "status": "connected"|"disconnected"|"unknown"}
    """
    order = ("manago", "shopify", "erp")
    names = {"manago": "Manago", "shopify": "Shopify", "erp": "ERP"}
    by_key = {row.get("key"): row for row in connectors if isinstance(row, dict)}
    parts: list[str] = []
    for key in order:
        row = by_key.get(key) or {"status": "unknown"}
        status = str(row.get("status") or "unknown").lower()
        label = names[key]
        if status in {"connected", "degraded"}:
            parts.append(f"{label} connected")
        elif status in {"disconnected", "error", "revoked"}:
            parts.append(f"{label} not connected")
        else:
            parts.append(f"{label} unknown")
    return " · ".join(parts)


def incomplete_assessment_copy(
    *,
    score: Any,
    coverage: Any,
    unknown: int,
    not_connected: int,
) -> str:
    score_s = "n/a"
    if isinstance(score, (int, float)):
        score_s = str(int(score)) if float(score).is_integer() else f"{float(score):.2f}"
    cov_pct = 0
    if isinstance(coverage, (int, float)):
        cov_pct = int(round(float(coverage) * 100)) if float(coverage) <= 1 else int(round(float(coverage)))
    pending = unknown + not_connected
    return (
        f"Incomplete assessment — score {score_s} with {cov_pct}% coverage. "
        f"{pending} checks UNKNOWN / NOT_CONNECTED. "
        "Treat this score as directional until connectors and history are complete."
    )


def architecture_incomplete_copy(*, mode: Any, weighted_score: Any) -> str | None:
    mode_s = str(mode or "").upper()
    if mode_s == "INCOMPLETE" or weighted_score is None:
        return (
            "Architecture assessment is incomplete or inventory is insufficient "
            "for a reliable weighted score."
        )
    return None
