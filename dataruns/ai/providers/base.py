"""Provider port — JSON-only completions, zero tools (PRD-AI-01 §8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResult:
    """Raw provider response before schema validation."""

    text: str
    model: str
    provider: str
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    langsmith_run_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class AiProvider(ABC):
    """Adapter interface. No tools / function calling in v1."""

    name: str = "base"

    @abstractmethod
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
        """Return a single JSON object as text. Raise on transport failure."""
