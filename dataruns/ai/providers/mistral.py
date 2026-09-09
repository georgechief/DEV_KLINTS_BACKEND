"""Mistral Small 4 adapter (PRD-AI-01 §8.1). Zero tools. JSON-only."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from django.conf import settings

from dataruns.ai.exceptions import AiProviderError
from dataruns.ai.providers.base import AiProvider, ProviderResult

logger = logging.getLogger(__name__)

# One SDK client per API key — avoid leaking httpx sessions on every request.
_SDK_CLIENTS: dict[str, Any] = {}
_CLIENT_LOCK = threading.Lock()
# chat.complete is not safe to overlap on the shared client (corrupt JSON / 429).
_COMPLETE_LOCK = threading.Lock()


def _build_mistral_sdk(*, api_key: str, timeout_seconds: float) -> Any:
    try:
        from mistralai.client import Mistral
    except ImportError:
        try:
            from mistralai import Mistral
        except ImportError as exc:
            raise AiProviderError(
                "mistralai package is not installed.",
                code="provider_not_configured",
            ) from exc
    timeout_ms = max(1000, int(float(timeout_seconds) * 1000))
    try:
        return Mistral(api_key=api_key, timeout_ms=timeout_ms)
    except TypeError:
        return Mistral(api_key=api_key)


def _shared_sdk_client(*, api_key: str, timeout_seconds: float) -> Any:
    cached = _SDK_CLIENTS.get(api_key)
    if cached is not None:
        return cached
    with _CLIENT_LOCK:
        cached = _SDK_CLIENTS.get(api_key)
        if cached is not None:
            return cached
        client = _build_mistral_sdk(api_key=api_key, timeout_seconds=timeout_seconds)
        _SDK_CLIENTS[api_key] = client
        return client


class MistralAiProvider(AiProvider):
    name = "mistral"

    def __init__(self, *, api_key: str | None = None, client: Any | None = None):
        self._api_key = (api_key if api_key is not None else str(
            getattr(settings, "MISTRAL_API_KEY", "") or ""
        )).strip()
        self._client = client

    def _require_client(self, *, timeout_seconds: float) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise AiProviderError(
                "Mistral API key is not configured.",
                code="provider_not_configured",
            )
        return _shared_sdk_client(api_key=self._api_key, timeout_seconds=timeout_seconds)

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
        client = self._require_client(timeout_seconds=timeout_seconds)
        timeout_ms = max(1000, int(float(timeout_seconds) * 1000))
        try:
            with _COMPLETE_LOCK:
                response = client.chat.complete(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    tool_choice="none",
                    timeout_ms=timeout_ms,
                )
        except AiProviderError:
            raise
        except Exception as exc:
            logger.warning("mistral_complete_failed error=%s", type(exc).__name__)
            raise AiProviderError(
                "Mistral provider unavailable.",
                code="provider_error",
            ) from exc

        text = _message_text(response)
        if not text.strip():
            raise AiProviderError("Mistral returned an empty response.", code="provider_error")

        usage = getattr(response, "usage", None)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ProviderResult(
            text=text,
            model=str(getattr(response, "model", None) or model),
            provider=self.name,
            latency_ms=max(elapsed_ms, 1),
            input_tokens=_usage_int(usage, "prompt_tokens", "input_tokens"),
            output_tokens=_usage_int(usage, "completion_tokens", "output_tokens"),
            raw={"mock": False},
        )


def _message_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _usage_int(usage: Any, *names: str) -> int | None:
    if usage is None:
        return None
    for name in names:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None
