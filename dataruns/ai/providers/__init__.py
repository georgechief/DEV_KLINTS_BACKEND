"""Provider factory (mock now; mistral in Phase E)."""

from __future__ import annotations

from django.conf import settings

from dataruns.ai.exceptions import AiProviderError
from dataruns.ai.providers.base import AiProvider
from dataruns.ai.providers.mock import MockAiProvider


def get_ai_provider(*, name: str | None = None) -> AiProvider:
    provider_name = (name or getattr(settings, "AI_PROVIDER", "mock") or "mock").strip().lower()
    if provider_name == "mock":
        return MockAiProvider()
    if provider_name == "mistral":
        # Phase E wires the real adapter. Until then fail closed.
        raise AiProviderError(
            "Mistral provider is not configured yet. Use AI_PROVIDER=mock.",
            code="provider_not_configured",
        )
    raise AiProviderError(
        f"Unknown AI provider: {provider_name}",
        code="unknown_provider",
    )
