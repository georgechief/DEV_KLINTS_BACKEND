"""AI-01 service / API errors (map to HTTP in views)."""

from __future__ import annotations


class AiServiceError(Exception):
    """Base AI service error."""

    def __init__(self, message: str, *, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


class AiDisabledError(AiServiceError):
    def __init__(self, message: str = "AI suggestions are disabled."):
        super().__init__(message, code="ai_disabled")


class AiNotFoundError(AiServiceError):
    def __init__(self, message: str = "Worklist issue not found."):
        super().__init__(message, code="not_found")


class AiGateDeniedError(AiServiceError):
    def __init__(self, message: str = "AI context failed privacy gate.", *, reason: str):
        super().__init__(message, code="gate_denied")
        self.reason = reason


class AiProviderError(AiServiceError):
    def __init__(self, message: str = "AI provider unavailable.", *, code: str = "provider_error"):
        super().__init__(message, code=code)


class AiJsonRetryExhaustedError(AiProviderError):
    def __init__(self, message: str = "AI returned invalid JSON after retries."):
        super().__init__(message, code="json_retry_exhausted")
