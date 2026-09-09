"""Hard-test evaluators for build packages (PRD-QA-01 §5).

Pure functions over package JSON (+ optional blueprint body). No live Manago.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.use_cases.qa_normalize import (
    branch_exists_after_entries,
    consent_condition_nodes,
    data_gates_blocking_checks,
    find_entry_node_ids,
    gate_check_rows,
    is_terminal_node,
    node_id,
    node_type,
    nodes_missing_terminal,
    normalize_gates_snapshot,
    orphan_node_ids,
    resolve_audience_consent,
    resolve_collision_policy,
    resolve_primary_metric,
    resolve_rollback_strategy,
    resolve_workflow_nodes,
)

HARD_TEST_IDS = (
    "data_gates_pass",
    "consent_branching",
    "terminal_reachable",
    "no_orphan_nodes",
    "collision_policy",
    "measurement_wired",
    "rollback_defined",
)

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"


@dataclass
class HardTestResult:
    """One hard_test row + evidence entries for the QA payload."""

    test_id: str
    status: str
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_hard_test_row(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "status": self.status,
            "evidence_ids": [e["id"] for e in self.evidence if e.get("id")],
        }


def _observed_at(now: datetime | None = None) -> str:
    dt = now or timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt.isoformat()


def _evidence(
    *,
    test_id: str,
    index: int,
    locator: str,
    value: Any,
    source: str = "build_package",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Schema evidence entry with stable id for hard_tests.evidence_ids."""
    return {
        "id": f"ev-{test_id}-{index}",
        "source": source,
        "locator": locator,
        "value": value,
        "observed_at": _observed_at(now),
    }


def _result(
    test_id: str,
    status: str,
    evidence: list[dict[str, Any]],
) -> HardTestResult:
    return HardTestResult(test_id=test_id, status=status, evidence=evidence)


def evaluate_data_gates_pass(
    package_payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> HardTestResult:
    test_id = "data_gates_pass"
    payload = package_payload if isinstance(package_payload, dict) else {}
    snap = payload.get("gates_snapshot")
    normalized = normalize_gates_snapshot(snap)
    checks = normalized.get("checks") or {}

    if not checks:
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="gates_snapshot.checks",
                value="missing_or_empty",
                now=now,
            )
        ]
        return _result(test_id, STATUS_FAIL, evidence)

    blocking = data_gates_blocking_checks(snap)
    if not blocking:
        evidence = [
            _evidence(
                test_id=test_id,
                index=i,
                locator=row["locator"],
                value=row["status"],
                now=now,
            )
            for i, row in enumerate(gate_check_rows(normalized))
        ]
        if not evidence:
            evidence = [
                _evidence(
                    test_id=test_id,
                    index=0,
                    locator="gates_snapshot.checks",
                    value="PASS",
                    now=now,
                )
            ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=i,
            locator=row["locator"],
            value=row["status"],
            now=now,
        )
        for i, row in enumerate(blocking)
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_consent_branching(
    package_payload: dict[str, Any],
    *,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> HardTestResult:
    """
    PASS when:
    - ≥1 CONDITION (or equivalent) references consent / opt-in / suppression, OR
    - audience.consent is non-empty AND a branch exists after trigger.
    """
    test_id = "consent_branching"
    payload = package_payload if isinstance(package_payload, dict) else {}
    nodes = resolve_workflow_nodes(payload, blueprint_body=blueprint_body)
    consent_nodes = consent_condition_nodes(nodes)

    if consent_nodes:
        node = consent_nodes[0]
        nid = node_id(node) or "unknown"
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator=f"agent_spec.nodes.{nid}",
                value={
                    "node_id": nid,
                    "node_type": node_type(node),
                    "matched": "consent_condition",
                },
                now=now,
            )
        ]
        return _result(test_id, STATUS_PASS, evidence)

    audience_consent = resolve_audience_consent(
        payload,
        blueprint_body=blueprint_body,
    )
    entries = find_entry_node_ids(nodes)
    # Require a real branch/CONDITION after entry — not merely "trigger has a next".
    branch_after_trigger = branch_exists_after_entries(nodes, entry_ids=entries)

    if audience_consent and branch_after_trigger:
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.audience.consent",
                value=audience_consent,
                now=now,
            ),
            _evidence(
                test_id=test_id,
                index=1,
                locator="agent_spec.nodes.trigger.next",
                value=entries,
                now=now,
            ),
        ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=0,
            locator="agent_spec.nodes",
            value={
                "consent_condition_nodes": [],
                "audience_consent": audience_consent,
                "branch_after_trigger": branch_after_trigger,
            },
            now=now,
        )
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_terminal_reachable(
    package_payload: dict[str, Any],
    *,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> HardTestResult:
    test_id = "terminal_reachable"
    payload = package_payload if isinstance(package_payload, dict) else {}
    nodes = resolve_workflow_nodes(payload, blueprint_body=blueprint_body)
    if not nodes:
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.nodes",
                value="empty",
                now=now,
            )
        ]
        return _result(test_id, STATUS_FAIL, evidence)

    missing = nodes_missing_terminal(nodes)
    if not missing:
        terminals = [node_id(n) for n in nodes if is_terminal_node(n) and node_id(n)]
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.nodes.terminals",
                value=terminals,
                now=now,
            )
        ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=0,
            locator="agent_spec.nodes.missing_terminal",
            value=missing,
            now=now,
        )
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_no_orphan_nodes(
    package_payload: dict[str, Any],
    *,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> HardTestResult:
    test_id = "no_orphan_nodes"
    payload = package_payload if isinstance(package_payload, dict) else {}
    nodes = resolve_workflow_nodes(payload, blueprint_body=blueprint_body)
    if not nodes:
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.nodes",
                value="empty",
                now=now,
            )
        ]
        return _result(test_id, STATUS_FAIL, evidence)

    orphans = orphan_node_ids(nodes)
    if not orphans:
        entries = find_entry_node_ids(nodes)
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.nodes.entry",
                value=entries,
                now=now,
            )
        ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=0,
            locator="agent_spec.nodes.orphans",
            value=orphans,
            now=now,
        )
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_collision_policy(
    package_payload: dict[str, Any],
    *,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> HardTestResult:
    test_id = "collision_policy"
    payload = package_payload if isinstance(package_payload, dict) else {}
    policy = resolve_collision_policy(
        payload,
        blueprint_body=blueprint_body,
    )
    if policy is not None:
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.collision_policy",
                value=policy if not isinstance(policy, (dict, list)) else "present",
                now=now,
            )
        ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=0,
            locator="agent_spec.collision_policy",
            value="missing",
            now=now,
        )
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_measurement_wired(
    package_payload: dict[str, Any],
    *,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> HardTestResult:
    test_id = "measurement_wired"
    payload = package_payload if isinstance(package_payload, dict) else {}
    metric = resolve_primary_metric(
        payload,
        blueprint_body=blueprint_body,
    )
    if metric:
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="agent_spec.measurement.primary_metric",
                value=metric,
                now=now,
            )
        ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=0,
            locator="agent_spec.measurement.primary_metric",
            value="missing",
            now=now,
        )
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_rollback_defined(
    package_payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> HardTestResult:
    test_id = "rollback_defined"
    payload = package_payload if isinstance(package_payload, dict) else {}
    strategy = resolve_rollback_strategy(payload)
    if strategy:
        snippet = strategy if len(strategy) <= 160 else strategy[:157] + "..."
        evidence = [
            _evidence(
                test_id=test_id,
                index=0,
                locator="rollback.strategy",
                value=snippet,
                now=now,
            )
        ]
        return _result(test_id, STATUS_PASS, evidence)

    evidence = [
        _evidence(
            test_id=test_id,
            index=0,
            locator="rollback.strategy",
            value="missing",
            now=now,
        )
    ]
    return _result(test_id, STATUS_FAIL, evidence)


def evaluate_unknown_test(
    test_id: str,
    *,
    now: datetime | None = None,
) -> HardTestResult:
    evidence = [
        _evidence(
            test_id=test_id or "unknown",
            index=0,
            locator="qa_requirements.hard_tests",
            value="unknown_test",
            now=now,
        )
    ]
    return _result(test_id or "unknown", STATUS_FAIL, evidence)


_EVALUATORS = {
    "data_gates_pass": evaluate_data_gates_pass,
    "consent_branching": evaluate_consent_branching,
    "terminal_reachable": evaluate_terminal_reachable,
    "no_orphan_nodes": evaluate_no_orphan_nodes,
    "collision_policy": evaluate_collision_policy,
    "measurement_wired": evaluate_measurement_wired,
    "rollback_defined": evaluate_rollback_defined,
}


def evaluate_hard_test(
    test_id: str,
    package_payload: dict[str, Any],
    *,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> HardTestResult:
    """Dispatch one hard test; unknown test_id → FAIL (fail closed)."""
    key = (test_id or "").strip()
    payload = package_payload if isinstance(package_payload, dict) else {}
    fn = _EVALUATORS.get(key)
    if fn is None:
        return evaluate_unknown_test(key or "unknown", now=now)

    if key in {
        "consent_branching",
        "terminal_reachable",
        "no_orphan_nodes",
        "collision_policy",
        "measurement_wired",
    }:
        return fn(payload, blueprint_body=blueprint_body, now=now)
    return fn(payload, now=now)


def evaluate_hard_tests(
    package_payload: dict[str, Any],
    *,
    hard_test_ids: list[str] | None = None,
    blueprint_body: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[HardTestResult]:
    """
    Evaluate all required hard tests in order.

    If hard_test_ids is None, read from package qa_requirements.hard_tests.
    Explicit empty list stays empty (score 0 / FAIL). Pack default of 7 is
    used only when the hard_tests key is absent.
    """
    payload = package_payload if isinstance(package_payload, dict) else {}
    if hard_test_ids is None:
        qa_req = payload.get("qa_requirements")
        if isinstance(qa_req, dict) and "hard_tests" in qa_req:
            raw = qa_req.get("hard_tests")
            if isinstance(raw, list):
                hard_test_ids = [str(t).strip() for t in raw if str(t).strip()]
            else:
                hard_test_ids = []
        else:
            hard_test_ids = list(HARD_TEST_IDS)

    results: list[HardTestResult] = []
    for test_id in hard_test_ids:
        results.append(
            evaluate_hard_test(
                test_id,
                payload,
                blueprint_body=blueprint_body,
                now=now,
            )
        )
    return results


def strip_evidence_ids_for_schema(
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Pack evidence schema allows source/locator/value/observed_at only.
    Keep id internally for hard_tests.evidence_ids; strip when embedding
    into schema evidence[] if additionalProperties is false.
    """
    cleaned: list[dict[str, Any]] = []
    for row in evidence:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "source": row.get("source", "build_package"),
                "locator": row.get("locator", ""),
                "value": row.get("value"),
                "observed_at": row.get("observed_at") or _observed_at(),
            }
        )
    return cleaned


def collect_evidence_for_payload(
    results: list[HardTestResult],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns (hard_tests rows with evidence_ids, evidence[] for schema).

    evidence entries keep ``id`` until serialized; schema strip is applied
    by the run orchestrator (Step 4) via strip_evidence_ids_for_schema.
    """
    hard_rows = [r.as_hard_test_row() for r in results]
    evidence: list[dict[str, Any]] = []
    for result in results:
        for item in result.evidence:
            evidence.append(deepcopy(item))
    return hard_rows, evidence
