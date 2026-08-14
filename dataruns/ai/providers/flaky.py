"""Broken-then-ok provider for retry unit tests."""

from __future__ import annotations

from typing import Any

from dataruns.ai.providers.base import AiProvider, ProviderResult
from dataruns.ai.providers.mock import MockAiProvider


class FlakyJsonProvider(AiProvider):
    """Returns invalid JSON for the first N calls, then delegates to mock."""

    name = "flaky"

    def __init__(self, *, fail_times: int = 2):
        self.fail_times = fail_times
        self.attempts = 0
        self._mock = MockAiProvider()

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
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return ProviderResult(
                text="not-json{{{",
                model=model,
                provider=self.name,
                latency_ms=1,
            )
        return self._mock.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context=context,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
