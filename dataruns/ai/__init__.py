"""Klints AI narrative layer (PRD-AI-01) — PrivacyGate + contracts + Fix service."""

from dataruns.ai.allowlist import project, project_fix_suggestion_context
from dataruns.ai.constants import (
    DEFAULT_MODEL_ID,
    DEFAULT_PROVIDER,
    POLICY_VERSION,
    PROMPT_FIX_SUGGESTION_V1,
    PROMPT_SYSTEM_V1,
    TASK_FIX_SUGGESTION,
)
from dataruns.ai.fingerprints import compute_fingerprint, fingerprint_prefix
from dataruns.ai.persistence import (
    build_envelope,
    create_ai_call,
    extract_headline,
    get_cached_suggestion,
    upsert_ai_suggestion,
)
from dataruns.ai.privacy_gate import GateResult, ensure_safe_context
from dataruns.ai.schemas import FixSuggestionOutput, parse_task_output
from dataruns.ai.service import get_or_create_fix_suggestion, serialize_fix_suggestion_result

__all__ = [
    "DEFAULT_MODEL_ID",
    "DEFAULT_PROVIDER",
    "POLICY_VERSION",
    "PROMPT_FIX_SUGGESTION_V1",
    "PROMPT_SYSTEM_V1",
    "TASK_FIX_SUGGESTION",
    "FixSuggestionOutput",
    "GateResult",
    "build_envelope",
    "compute_fingerprint",
    "create_ai_call",
    "ensure_safe_context",
    "extract_headline",
    "fingerprint_prefix",
    "get_cached_suggestion",
    "get_or_create_fix_suggestion",
    "parse_task_output",
    "project",
    "project_fix_suggestion_context",
    "serialize_fix_suggestion_result",
    "upsert_ai_suggestion",
]
