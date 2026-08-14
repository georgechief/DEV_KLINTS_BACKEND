"""Deterministic mock provider for Phase C (no API keys)."""

from __future__ import annotations

import json
import time
from typing import Any

from dataruns.ai.providers.base import AiProvider, ProviderResult


class MockAiProvider(AiProvider):
    """Returns valid fix_suggestion JSON from allowlisted context."""

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
        check_id = str(context.get("check_id") or "XX-00").upper()
        check_name = str(context.get("check_name") or check_id)
        systems = str(context.get("systems_compared") or "connected platforms")
        suggested = str(context.get("suggested_fix") or "Follow the CheckMaster remediation.")
        fix_type = str(context.get("fix_type") or "Configuration")
        fix_owner = str(context.get("fix_owner") or "Data lead")
        finding = context.get("finding_summary") if isinstance(context.get("finding_summary"), dict) else {}
        detail = str(finding.get("detail") or "").strip()
        whats_wrong = (
            detail
            if detail
            else f"{check_name} is failing between {systems}."
        )
        payload = {
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
                    "detail": (
                        "Confirm the fix on a small sample before any bulk change."
                    ),
                },
            ],
            "cautions": [
                "Do not bulk-overwrite native fields without a sandbox proof.",
            ],
            "confidence": "medium",
        }
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
