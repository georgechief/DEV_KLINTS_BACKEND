"""Load versioned prompt text files for AI-01."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dataruns.ai.constants import (
    PROMPT_EXPLAIN_FINDING_V1,
    PROMPT_FIX_SUGGESTION_V1,
    PROMPT_NBA_BLURB_V1,
    PROMPT_REPORT_NARRATIVE_V1,
    PROMPT_SYSTEM_V1,
)

_PROMPT_FILES = {
    PROMPT_SYSTEM_V1: "system_v1.txt",
    PROMPT_FIX_SUGGESTION_V1: "fix_suggestion_v1.txt",
    # Stubs — files added in Phase F; loader returns empty until then.
    PROMPT_EXPLAIN_FINDING_V1: "explain_finding_v1.txt",
    PROMPT_REPORT_NARRATIVE_V1: "report_narrative_v1.txt",
    PROMPT_NBA_BLURB_V1: "nba_blurb_v1.txt",
}


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_prompt(prompt_id: str) -> str:
    """
    Return prompt body for a prompt_id (e.g. ai01.fix_suggestion.v1).

    Strips leading comment lines that start with '#'.
    """
    filename = _PROMPT_FILES.get(prompt_id)
    if not filename:
        raise KeyError(f"Unknown prompt_id: {prompt_id}")
    path = _prompts_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file missing for {prompt_id}: {filename}")
    lines = path.read_text(encoding="utf-8").splitlines()
    body_lines = [line for line in lines if not line.strip().startswith("#")]
    return "\n".join(body_lines).strip() + "\n"


def system_prompt_v1() -> str:
    return load_prompt(PROMPT_SYSTEM_V1)


def fix_suggestion_prompt_v1() -> str:
    return load_prompt(PROMPT_FIX_SUGGESTION_V1)
