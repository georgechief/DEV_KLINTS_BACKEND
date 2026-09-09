"""Provider factory (mock / mistral)."""

from __future__ import annotations

from django.conf import settings

from dataruns.ai.exceptions import AiProviderError
from dataruns.ai.providers.base import AiProvider
from dataruns.ai.providers.mock import MockAiProvider
from dataruns.ai.providers.mistral import MistralAiProvider


def get_ai_provider(*, name: str | None = None) -> AiProvider:
    provider_name = (name or getattr(settings, "AI_PROVIDER", "mock") or "mock").strip().lower()
    if provider_name == "mock":
        return MockAiProvider()
    if provider_name == "mistral":
        api_key = str(getattr(settings, "MISTRAL_API_KEY", "") or "").strip()
        if not api_key:
            raise AiProviderError(
                "Mistral API key is not configured. Set MISTRAL_API_KEY or use AI_PROVIDER=mock.",
                code="provider_not_configured",
            )
        return MistralAiProvider(api_key=api_key)
    raise AiProviderError(
        f"Unknown AI provider: {provider_name}",
        code="unknown_provider",
    )
