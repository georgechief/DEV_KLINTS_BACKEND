"""Deterministic mock provider for tests and local (no API keys)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from dataruns.ai.providers.base import AiProvider, ProviderResult


def _systems_list(context: dict[str, Any]) -> list[str]:
    raw = str(context.get("systems_compared") or "").strip()
    if not raw:
        return []
    parts = [item.strip()[:64] for item in re.split(r"\s*[·/,|&]\s*", raw) if item.strip()]
    out: list[str] = []
    for item in parts:
        if item and item not in out:
            out.append(item)
        if len(out) >= 8:
            break
    return out


def _fix_suggestion_payload(context: dict[str, Any]) -> dict[str, Any]:
    check_id = str(context.get("check_id") or "XX-00").upper()
    check_name = str(context.get("check_name") or check_id)
    systems = str(context.get("systems_compared") or "connected platforms")
    suggested = str(context.get("suggested_fix") or "Follow the CheckMaster remediation.")
    fix_type = str(context.get("fix_type") or "Configuration")
    fix_owner = str(context.get("fix_owner") or "Data lead")
    finding = context.get("finding_summary") if isinstance(context.get("finding_summary"), dict) else {}
    detail = str(finding.get("detail") or "").strip()
    whats_wrong = detail if detail else f"{check_name} is failing between {systems}."
    return {
        "task_type": "fix_suggestion",
        "check_id": check_id,
        "headline": f"{check_name} needs attention",
        "whats_wrong": whats_wrong[:800],
        "why_it_matters": (
            "Unresolved data inconsistencies can send the wrong message "
            "or skip the right customer journey."
        ),
        "suggestions": [
            {
                "step": 1,
                "title": "Review The Suggested Fix",
                "detail": suggested[:800],
            },
            {
                "step": 2,
                "title": "Align Ownership And Type",
                "detail": (
                    f"Remediation type is {fix_type}; owner is {fix_owner}. "
                    "Keep changes consistent with that ownership."
                )[:800],
            },
            {
                "step": 3,
                "title": "Validate In A Safe Window",
                "detail": "Confirm the fix on a small sample before any bulk change.",
            },
        ],
        "cautions": [
            "Do not bulk-overwrite native fields without a sandbox proof.",
        ],
        "confidence": "medium",
    }


def _explain_finding_payload(context: dict[str, Any]) -> dict[str, Any]:
    check_id = str(context.get("check_id") or "XX-00").upper()
    check_name = str(context.get("check_name") or check_id)
    systems = str(context.get("systems_compared") or "connected platforms")
    finding = context.get("finding_summary") if isinstance(context.get("finding_summary"), dict) else {}
    detail = str(finding.get("detail") or "").strip()
    explanation = (
        f"{check_name} is out of sync across {systems}. "
        + (f"{detail} " if detail else "")
        + "Use the suggested fix as the source of truth; do not invent a new mapping."
    )
    return {
        "task_type": "explain_finding",
        "check_id": check_id,
        "headline": f"{check_name} is inconsistent",
        "explanation": explanation[:1200],
        "systems": _systems_list(context),
    }


def _report_narrative_payload(context: dict[str, Any]) -> dict[str, Any]:
    company = str(context.get("company_display_name") or "This company")
    score = context.get("headline_score")
    score_bit = (
        f"The latest consistency score is {score}."
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else "A consistency score is available on this run."
    )
    top_checks = context.get("top_checks") if isinstance(context.get("top_checks"), list) else []
    themes: list[str] = []
    for row in top_checks[:5]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("check_name") or row.get("check_id") or "").strip()
        if name and name not in themes:
            themes.append(name[:120])
    if not themes:
        themes = ["Open FAIL and WARN checks"]
    plan_ids = context.get("plan_check_ids") if isinstance(context.get("plan_check_ids"), list) else []
    ids = [str(item).strip().upper() for item in plan_ids if str(item).strip()][:4]
    focus = (
        f"Start with the current plan items {', '.join(ids)}."
        if ids
        else "Follow the current ranked plan; do not invent a new order."
    )
    revenue = context.get("revenue_impact_total")
    revenue_bit = ""
    if isinstance(revenue, (int, float)) and not isinstance(revenue, bool) and revenue > 0:
        currency = str(context.get("currency") or "").strip().upper()
        revenue_bit = (
            f" Restated at-stake impact is {currency} {revenue}."
            if currency
            else f" Restated at-stake impact is {revenue}."
        )
    exec_summary = (
        f"{company} has open data-consistency gaps on the latest scored run. "
        f"{score_bit} "
        f"The main themes are {', '.join(themes[:3])}."
        f"{revenue_bit} "
        "Fix the listed checks in the existing plan order."
    )
    return {
        "task_type": "report_narrative",
        "exec_summary": exec_summary[:2000],
        "top_themes": themes[:8],
        "recommended_focus": focus[:800],
    }


def _nba_blurb_payload(context: dict[str, Any]) -> dict[str, Any]:
    check_id = str(context.get("check_id") or "XX-00").upper()
    check_name = str(context.get("check_name") or check_id)
    rank = context.get("plan_rank")
    rank_bit = f"It is plan item {rank}. " if isinstance(rank, int) and rank > 0 else ""
    return {
        "task_type": "nba_blurb",
        "check_id": check_id,
        "blurb": (
            f"{rank_bit}{check_name} is next because it is already on the ranked plan."
        )[:280],
    }


class MockAiProvider(AiProvider):
    """Returns valid task JSON from allowlisted context."""

    name = "mock"

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
        model: str,
        temperature: float,
        timeout_seconds: float,
    ) -> ProviderResult:
        started = time.perf_counter()
        task_type = str(context.get("task_type") or "fix_suggestion").strip()
        if task_type == "explain_finding":
            payload = _explain_finding_payload(context)
        elif task_type == "report_narrative":
            payload = _report_narrative_payload(context)
        elif task_type == "nba_blurb":
            payload = _nba_blurb_payload(context)
        else:
            payload = _fix_suggestion_payload(context)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ProviderResult(
            text=json.dumps(payload),
            model=model,
            provider=self.name,
            latency_ms=max(elapsed_ms, 1),
            input_tokens=80,
            output_tokens=120,
            langsmith_run_id=None,
            raw={"mock": True},
        )
