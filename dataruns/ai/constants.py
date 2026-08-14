"""AI-01 constants — policy / prompt versions and sanitizer caps."""

from __future__ import annotations

POLICY_VERSION = "privacy_gate.v1"
ALLOWLIST_VERSION = "ai_context.v1"
SCHEMA_VERSION = 1

PROMPT_SYSTEM_V1 = "ai01.system.v1"
PROMPT_FIX_SUGGESTION_V1 = "ai01.fix_suggestion.v1"
PROMPT_EXPLAIN_FINDING_V1 = "ai01.explain_finding.v1"
PROMPT_REPORT_NARRATIVE_V1 = "ai01.report_narrative.v1"
PROMPT_NBA_BLURB_V1 = "ai01.nba_blurb.v1"

DEFAULT_MODEL_ID = "mistral-small-latest"
DEFAULT_PROVIDER = "mistral"

# PRD-AI-01 §4.3
MAX_MISMATCH_ROWS = 12
MAX_STRING_CHARS = 800

TASK_FIX_SUGGESTION = "fix_suggestion"
TASK_EXPLAIN_FINDING = "explain_finding"
TASK_REPORT_NARRATIVE = "report_narrative"
TASK_NBA_BLURB = "nba_blurb"

TASK_TYPES_V1 = frozenset(
    {
        TASK_FIX_SUGGESTION,
        TASK_EXPLAIN_FINDING,
        TASK_REPORT_NARRATIVE,
        TASK_NBA_BLURB,
    }
)

CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})
