"""Data Consistency Score (DCS) library — master, assemble, executors."""

from dataruns.dcs.assemble import AssembleValidationError, assemble_dcs_score
from dataruns.dcs.enqueue import (
    DAILY_BEAT_TRIGGER,
    DcsAlreadyRunningError,
    enqueue_dcs_score,
)
from dataruns.dcs.executors import (
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_foundation_gates,
)
from dataruns.dcs.master import load_check_master
from dataruns.dcs.orchestrate import run_dcs_pipeline
from dataruns.dcs.types import CheckResult, DcsRun

__all__ = [
    "AssembleValidationError",
    "CheckResult",
    "ConnectorGateInput",
    "DAILY_BEAT_TRIGGER",
    "DcsAlreadyRunningError",
    "DcsRun",
    "FoundationGateContext",
    "assemble_dcs_score",
    "enqueue_dcs_score",
    "evaluate_foundation_gates",
    "load_check_master",
    "run_dcs_pipeline",
]
