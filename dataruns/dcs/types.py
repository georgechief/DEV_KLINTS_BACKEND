"""DCS check-result and run payload types (PRD-DCS-00)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CheckStatus = Literal[
    "PASS",
    "WARN",
    "FAIL",
    "NOT_APPLICABLE",
    "NOT_CONNECTED",
    "UNKNOWN",
]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
RunState = Literal[
    "READY",
    "CONDITIONALLY_READY",
    "REMEDIATE",
    "BLOCKED",
    "INCOMPLETE",
]

SCORE_FACTORS: dict[str, float | None] = {
    "PASS": 1.0,
    "WARN": 0.5,
    "FAIL": 0.0,
    "NOT_APPLICABLE": None,
    "NOT_CONNECTED": None,
    "UNKNOWN": None,
}

CONFIDENCE_FACTORS: dict[str, float] = {
    "HIGH": 1.0,
    "MEDIUM": 0.7,
    "LOW": 0.4,
}

ELIGIBLE_STATUSES = frozenset({"PASS", "WARN", "FAIL"})
EXCLUDED_STATUSES = frozenset({"NOT_APPLICABLE", "NOT_CONNECTED", "UNKNOWN"})


@dataclass
class Evidence:
    source: str
    observed_at: str
    locator: str | None = None
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"source": self.source, "observed_at": self.observed_at}
        if self.locator is not None:
            payload["locator"] = self.locator
        if self.value is not None:
            payload["value"] = self.value
        return payload


@dataclass
class CheckResult:
    check_id: str
    status: CheckStatus
    confidence: Confidence = "HIGH"
    evidence: list[Evidence] = field(default_factory=list)
    reason_code: str | None = None
    score_factor: float | None = None
    numeric_weight: float | None = None
    confidence_factor: float | None = None
    schema_version: str = "1.0.0"
    tenant_id: str = ""
    run_id: str = ""
    scoring_model_version: str = "DCS-1.0.0"
    evaluated_at: str | None = None
    provenance: dict[str, Any] | None = None
    # Sheet 02/03 finding enrichment (especially on FAIL)
    severity: str | None = None
    root_cause_ids: list[str] = field(default_factory=list)
    root_causes: list[dict[str, str]] = field(default_factory=list)
    message: str | None = None
    suggested_fix: str | None = None
    detection_logic: str | None = None
    # Excel sheet 02 Fix Type / Fix Owner (enriched from CheckMaster)
    fix_type: str | None = None
    fix_owner: str | None = None
    fix_in_klints: bool | None = None

    def normalized_score_factor(self) -> float | None:
        if self.score_factor is not None:
            return self.score_factor
        return SCORE_FACTORS[self.status]

    def normalized_confidence_factor(self) -> float:
        if self.confidence_factor is not None:
            return float(self.confidence_factor)
        return CONFIDENCE_FACTORS[self.confidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "check_id": self.check_id,
            "status": self.status,
            "score_factor": self.normalized_score_factor(),
            "numeric_weight": self.numeric_weight,
            "confidence": self.confidence,
            "confidence_factor": self.normalized_confidence_factor(),
            "reason_code": self.reason_code,
            "severity": self.severity,
            "root_cause_ids": list(self.root_cause_ids),
            "root_causes": list(self.root_causes),
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "detection_logic": self.detection_logic,
            "fix_type": self.fix_type,
            "fix_owner": self.fix_owner,
            "fix_in_klints": self.fix_in_klints,
            "evidence": [e.to_dict() for e in self.evidence],
            "scoring_model_version": self.scoring_model_version,
            "evaluated_at": self.evaluated_at,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckResult:
        evidence_raw = data.get("evidence") or []
        evidence = [
            Evidence(
                source=item.get("source", ""),
                observed_at=item.get("observed_at", ""),
                locator=item.get("locator"),
                value=item.get("value"),
            )
            for item in evidence_raw
            if isinstance(item, dict)
        ]
        return cls(
            check_id=data["check_id"],
            status=data["status"],
            confidence=data.get("confidence") or "HIGH",
            evidence=evidence,
            reason_code=data.get("reason_code"),
            score_factor=data.get("score_factor"),
            numeric_weight=data.get("numeric_weight"),
            confidence_factor=data.get("confidence_factor"),
            schema_version=data.get("schema_version", "1.0.0"),
            tenant_id=data.get("tenant_id", ""),
            run_id=data.get("run_id", ""),
            scoring_model_version=data.get("scoring_model_version", "DCS-1.0.0"),
            evaluated_at=data.get("evaluated_at"),
            provenance=data.get("provenance"),
            severity=data.get("severity"),
            root_cause_ids=list(data.get("root_cause_ids") or []),
            root_causes=list(data.get("root_causes") or []),
            message=data.get("message"),
            suggested_fix=data.get("suggested_fix"),
            detection_logic=data.get("detection_logic"),
            fix_type=data.get("fix_type"),
            fix_owner=data.get("fix_owner"),
            fix_in_klints=data.get("fix_in_klints"),
        )


@dataclass
class DimensionScore:
    score: float | None
    coverage: float
    confidence: float
    weight_percent: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DcsRun:
    schema_version: str
    tenant_id: str
    run_id: str
    run_state: RunState
    scope_model_version: str
    scoring_model_version: str
    headline_score: float | None
    dimension_scores: dict[str, float | None]
    dimensions: dict[str, DimensionScore]
    coverage: float
    confidence: float
    check_result_refs: list[str]
    blocking_gates_failed: int
    missing_required_inputs: list[str]
    started_at: str
    completed_at: str | None
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "run_state": self.run_state,
            "scope_model_version": self.scope_model_version,
            "scoring_model_version": self.scoring_model_version,
            "blocking_gates_failed": self.blocking_gates_failed,
            "headline_score": self.headline_score,
            "dimension_scores": self.dimension_scores,
            "dimensions": {
                key: value.to_dict() for key, value in self.dimensions.items()
            },
            "coverage": self.coverage,
            "confidence": self.confidence,
            "check_result_refs": list(self.check_result_refs),
            "missing_required_inputs": list(self.missing_required_inputs),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "provenance": self.provenance,
        }
