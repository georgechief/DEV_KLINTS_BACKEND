"""Check executor registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dataruns.dcs.executors.foundation import (
    FOUNDATION_EXECUTORS,
    FoundationGateContext,
    evaluate_foundation_gates,
)
from dataruns.dcs.executors.business import BUSINESS_EXECUTORS
from dataruns.dcs.executors.consent import CONSENT_EXECUTORS
from dataruns.dcs.executors.drift import DRIFT_EXECUTORS
from dataruns.dcs.executors.identity import IDENTITY_EXECUTORS
from dataruns.dcs.executors.lifecycle import LIFECYCLE_EXECUTORS
from dataruns.dcs.executors.measurement import MEASUREMENT_EXECUTORS
from dataruns.dcs.executors.product import PRODUCT_EXECUTORS
from dataruns.dcs.executors.segment import SEGMENT_EXECUTORS
from dataruns.dcs.types import CheckResult

Executor = Callable[..., CheckResult]

_REGISTRY: dict[str, Executor] = {}


def register_executor(check_id: str, executor: Executor) -> None:
    _REGISTRY[check_id] = executor


def get_executor(check_id: str) -> Executor | None:
    return _REGISTRY.get(check_id)


def registered_check_ids() -> set[str]:
    return set(_REGISTRY)


def _register_defaults() -> None:
    for check_id, executor in FOUNDATION_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in IDENTITY_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in LIFECYCLE_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in CONSENT_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in PRODUCT_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in SEGMENT_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in MEASUREMENT_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in BUSINESS_EXECUTORS.items():
        register_executor(check_id, executor)
    for check_id, executor in DRIFT_EXECUTORS.items():
        register_executor(check_id, executor)


_register_defaults()


def run_registered(
    check_id: str,
    *,
    context: Any,
) -> CheckResult:
    executor = get_executor(check_id)
    if executor is None:
        raise KeyError(f"No executor registered for {check_id}")
    return executor(context)


__all__ = [
    "FoundationGateContext",
    "evaluate_foundation_gates",
    "get_executor",
    "register_executor",
    "registered_check_ids",
    "run_registered",
]
