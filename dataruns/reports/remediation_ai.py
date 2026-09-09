"""Fail-open AI fix_suggestion for Overview Export brief only."""

from __future__ import annotations

import logging
import re
from typing import Any

from dataruns.ai.exceptions import (
    AiDisabledError,
    AiGateDeniedError,
    AiJsonRetryExhaustedError,
    AiNotFoundError,
    AiProviderError,
)
from dataruns.ai.runner import ai_enabled
from dataruns.ai.service import get_or_create_fix_suggestion
from tenants.models import Company

logger = logging.getLogger(__name__)

_MAX_AI_FIX_CHECKS = 25
_PDF_STEP_RE = re.compile(r"\.\s+(?=\d+[\).]\s)")
_BOILERPLATE_STEP = re.compile(
    r"^\d+[\).]\s*Review the .+ issue in the Data Consistency Center\.?\s*$",
    re.I,
)


def format_fix_suggestion_for_pdf(payload: dict[str, Any]) -> str:
    """Short, complete PDF copy — headline + step titles, no mid-sentence cuts."""
    headline = str(payload.get("headline") or "").strip().rstrip(".")
    steps = payload.get("suggestions") if isinstance(payload.get("suggestions"), list) else []
    lines: list[str] = []
    if headline:
        lines.append(headline)
    for index, step in enumerate(steps[:3], start=1):
        if not isinstance(step, dict):
            continue
        title = str(step.get("title") or "").strip()
        if title:
            lines.append(f"{index}. {title}")
            continue
        detail = str(step.get("detail") or "").strip()
        if detail:
            lines.append(f"{index}. {detail}")
    if not lines:
        return ""
    return "<br/>".join(lines)


def compact_suggested_fix_for_pdf(text: str, *, max_steps: int = 3) -> str:
    """Normalize long multi-step fix strings already stored on legacy payloads."""
    token = str(text or "").strip()
    if not token:
        return ""
    if "<br/>" in token:
        return token
    if len(token) <= 180 and not _PDF_STEP_RE.search(token):
        return token

    lines: list[str] = []
    step_match = re.search(r"\s1[\).]\s", token)
    if step_match:
        headline = token[: step_match.start()].strip().rstrip(".")
        if headline:
            lines.append(headline)
        remainder = token[step_match.start() :].strip()
    else:
        remainder = token

    for part in _PDF_STEP_RE.split(remainder):
        part = part.strip().rstrip(".")
        if not part or _BOILERPLATE_STEP.match(part):
            continue
        if " — " in part:
            part = part.split(" — ", 1)[0].strip()
        elif len(part) > 96:
            part = part[:96].rsplit(" ", 1)[0]
        lines.append(part)
        if len(lines) >= max_steps + (1 if step_match else 0):
            break

    return "<br/>".join(lines) if lines else token


def format_fix_suggestion_payload(payload: dict[str, Any]) -> str:
    return format_fix_suggestion_for_pdf(payload)


def collect_fix_suggestions_for_report(
    *,
    company: Company,
    dcs_run_id: int | None,
    open_issues: list[dict[str, Any]],
    max_checks: int = _MAX_AI_FIX_CHECKS,
) -> dict[str, str]:
    if not ai_enabled():
        return {}

    out: dict[str, str] = {}
    seen: set[str] = set()
    for issue in open_issues:
        if len(out) >= max_checks:
            break
        check_id = str(issue.get("check_id") or "").strip().upper()
        if not check_id or check_id in seen:
            continue
        seen.add(check_id)
        try:
            result = get_or_create_fix_suggestion(
                company=company,
                check_id=check_id,
                dcs_run_id=dcs_run_id,
            )
            payload = result.suggestion.payload_json
            if not isinstance(payload, dict):
                continue
            text = format_fix_suggestion_payload(payload)
            if text:
                out[check_id] = text
        except (
            AiDisabledError,
            AiGateDeniedError,
            AiJsonRetryExhaustedError,
            AiNotFoundError,
            AiProviderError,
        ) as exc:
            logger.info(
                "overview_fix_suggestion_skipped check_id=%s code=%s",
                check_id,
                getattr(exc, "code", type(exc).__name__),
            )
        except Exception:
            logger.exception(
                "overview_fix_suggestion_failed check_id=%s dcs_run_id=%s",
                check_id,
                dcs_run_id,
            )
    return out
