"""Pydantic JSON contracts for AI-01 task types (PRD-AI-01 §6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Confidence = Literal["low", "medium", "high"]


class FixSuggestionStep(BaseModel):
    step: int = Field(ge=1, le=5)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=800)


class FixSuggestionOutput(BaseModel):
    """§6.1 fix_suggestion — Fix screen AI box."""

    task_type: Literal["fix_suggestion"] = "fix_suggestion"
    check_id: str = Field(min_length=1, max_length=32)
    headline: str = Field(min_length=1, max_length=240)
    whats_wrong: str = Field(min_length=1, max_length=800)
    why_it_matters: str = Field(min_length=1, max_length=800)
    suggestions: list[FixSuggestionStep] = Field(min_length=2, max_length=5)
    cautions: list[str] = Field(default_factory=list, max_length=8)
    confidence: Confidence = "medium"

    @field_validator("check_id")
    @classmethod
    def _upper_check_id(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("cautions")
    @classmethod
    def _cap_cautions(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()][
            :8
        ]

    @model_validator(mode="after")
    def _steps_sequential(self) -> FixSuggestionOutput:
        return self.model_copy(
            update={
                "suggestions": [
                    row.model_copy(update={"step": index})
                    for index, row in enumerate(self.suggestions, start=1)
                ]
            }
        )


class ExplainFindingOutput(BaseModel):
    """§6.2 explain_finding — stub for Phase F."""

    task_type: Literal["explain_finding"] = "explain_finding"
    check_id: str = Field(min_length=1, max_length=32)
    headline: str = Field(min_length=1, max_length=240)
    explanation: str = Field(min_length=1, max_length=1200)
    systems: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("check_id")
    @classmethod
    def _upper_check_id(cls, value: str) -> str:
        return value.strip().upper()


class ReportNarrativeOutput(BaseModel):
    """§6.3 report_narrative — stub for Phase F."""

    task_type: Literal["report_narrative"] = "report_narrative"
    exec_summary: str = Field(min_length=1, max_length=2000)
    top_themes: list[str] = Field(min_length=1, max_length=8)
    recommended_focus: str = Field(min_length=1, max_length=800)


class AiCallEnvelope(BaseModel):
    """§6.4 envelope metadata stored alongside validated output."""

    schema_version: int = 1
    prompt_version: str
    policy_version: str
    model: str
    provider: str
    fingerprint: str
    output: dict

    model_config = {"extra": "forbid"}


TASK_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "fix_suggestion": FixSuggestionOutput,
    "explain_finding": ExplainFindingOutput,
    "report_narrative": ReportNarrativeOutput,
}


def parse_task_output(task_type: str, payload: dict) -> BaseModel:
    """Validate model JSON against the task schema. Raises ValidationError."""
    model = TASK_OUTPUT_MODELS.get(task_type)
    if model is None:
        raise ValueError(f"Unsupported task_type: {task_type}")
    return model.model_validate(payload)
