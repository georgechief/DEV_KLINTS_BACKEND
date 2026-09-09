"""QA package normalizers (PRD-QA-01 Step 2).

Normalize WF-01 package JSON so hard-test evaluators (Step 3) do not fork
on shape differences. Package-only — no live Manago/DCS calls.
"""

from __future__ import annotations

from typing import Any

from dataruns.use_cases.recommend import is_supplemental_gate

# Pack + WF-01 node types that end a path (UC-02 uses FINISH).
TERMINAL_NODE_TYPES = frozenset(
    {
        "EXIT",
        "END",
        "STOP",
        "FINISH",
        "TERMINAL",
    }
)

# Labels that are not a hard FAIL for data_gates_pass (PRD-QA-01 §5).
# v1 lock: WARN does NOT block hard gates; FAIL and not_evaluated on hard gates do.
# UNKNOWN is evaluated-but-uncertain — never equate it to not_evaluated.
GATE_PASS_LABELS = frozenset({"PASS"})
GATE_WARN_LABELS = frozenset({"WARN", "WARNING"})
GATE_UNEVALUATED_LABELS = frozenset({"NOT_EVALUATED", ""})


def normalize_gate_label(raw: Any) -> str:
    """Uppercase gate result label; empty/None → NOT_EVALUATED.

    UNKNOWN stays UNKNOWN (evaluated but uncertain) — do not collapse to
    NOT_EVALUATED (never evaluated).
    """
    if raw is None:
        return "NOT_EVALUATED"
    label = str(raw).strip().upper()
    if not label:
        return "NOT_EVALUATED"
    if label == "WARNING":
        return "WARN"
    return label


def is_hard_gate(check_id: str | None) -> bool:
    """True when check is a hard (42-scoped) gate — not supplemental (WF-01 §3.2)."""
    normalized = (check_id or "").strip().upper()
    if not normalized:
        return False
    return not is_supplemental_gate(normalized)


def normalize_gates_snapshot(gates_snapshot: Any) -> dict[str, Any]:
    """
    Normalize package ``gates_snapshot`` to a stable shape.

    WF-01 actual shape::
        {
          "min_dcs": 70,
          "checks": {"CC-03": "PASS", "CC-06": "not_evaluated", ...},
          "provisional_supplemental": true|false,
          "headline_score": ...,
          "architecture_mode": ...,
        }

    Also accepts a flat ``{check_id: status}`` map (defensive).
    """
    if not isinstance(gates_snapshot, dict):
        return {
            "min_dcs": None,
            "checks": {},
            "provisional_supplemental": False,
            "headline_score": None,
            "architecture_mode": None,
        }

    checks_raw = gates_snapshot.get("checks")
    checks: dict[str, str] = {}
    if isinstance(checks_raw, dict):
        for check_id, status in checks_raw.items():
            cid = str(check_id).strip().upper()
            if not cid:
                continue
            checks[cid] = normalize_gate_label(status)
    else:
        # Flat map fallback: keys that look like check ids (contain '-').
        for key, value in gates_snapshot.items():
            key_s = str(key).strip()
            if key_s in {
                "min_dcs",
                "provisional_supplemental",
                "headline_score",
                "architecture_mode",
                "checks",
            }:
                continue
            if "-" not in key_s:
                continue
            checks[key_s.upper()] = normalize_gate_label(value)

    provisional = bool(gates_snapshot.get("provisional_supplemental"))
    return {
        "min_dcs": gates_snapshot.get("min_dcs"),
        "checks": checks,
        "provisional_supplemental": provisional,
        "headline_score": gates_snapshot.get("headline_score"),
        "architecture_mode": gates_snapshot.get("architecture_mode"),
    }


def gate_check_rows(normalized_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for each check in a normalized snapshot."""
    checks = normalized_snapshot.get("checks") or {}
    rows: list[dict[str, Any]] = []
    if not isinstance(checks, dict):
        return rows
    for check_id, status in checks.items():
        cid = str(check_id).strip().upper()
        label = normalize_gate_label(status)
        supplemental = is_supplemental_gate(cid)
        rows.append(
            {
                "check_id": cid,
                "status": label,
                "is_supplemental": supplemental,
                "is_hard": not supplemental,
                "locator": f"gates_snapshot.checks.{cid}",
            }
        )
    return rows


def hard_gate_blocks_data_gates_pass(status: str) -> bool:
    """
    PRD-QA-01 §5 data_gates_pass — hard gate block rule.

    FAIL blocks; WARN does not; not_evaluated / unknown blocks.
    """
    label = normalize_gate_label(status)
    if label in GATE_PASS_LABELS:
        return False
    if label in GATE_WARN_LABELS:
        return False
    return True


def supplemental_gate_blocks_data_gates_pass(
    status: str,
    *,
    provisional_supplemental: bool,
) -> bool:
    """
    Supplemental gate block rule for data_gates_pass (DCS-09 / WF-01 §3.2).

    - PASS → no block
    - not_evaluated → allowed only when provisional_supplemental
    - FAIL / UNKNOWN / NOT_CONNECTED / WARN / anything else → blocks

    Aligns with recommend: stored supplemental ≠ PASS → blocked_checks.
    (Hard-gate WARN exemption does not apply to supplemental.)
    """
    label = normalize_gate_label(status)
    if label in GATE_PASS_LABELS:
        return False
    if label in GATE_UNEVALUATED_LABELS:
        return not provisional_supplemental
    return True


def data_gates_blocking_checks(
    gates_snapshot: Any,
) -> list[dict[str, Any]]:
    """
    Return check rows that cause data_gates_pass to FAIL.

    Empty list ⇒ data_gates_pass should PASS (given snapshot is present).
    """
    normalized = normalize_gates_snapshot(gates_snapshot)
    provisional = bool(normalized.get("provisional_supplemental"))
    blocking: list[dict[str, Any]] = []
    for row in gate_check_rows(normalized):
        if row["is_hard"]:
            if hard_gate_blocks_data_gates_pass(row["status"]):
                blocking.append(row)
        else:
            if supplemental_gate_blocks_data_gates_pass(
                row["status"],
                provisional_supplemental=provisional,
            ):
                blocking.append(row)
    return blocking


def _as_node_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [n for n in raw if isinstance(n, dict)]


def resolve_workflow_nodes(
    package_payload: dict[str, Any] | None,
    *,
    blueprint_body: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Resolve workflow graph nodes for graph hard tests.

    Prefer ``agent_spec.nodes`` (WF-01 stores nodes here, not
    ``agent_spec.workflow.nodes``). Fallback: blueprint ``workflow.nodes``.
    """
    payload = package_payload if isinstance(package_payload, dict) else {}
    agent_spec = payload.get("agent_spec")
    if isinstance(agent_spec, dict):
        nodes = _as_node_list(agent_spec.get("nodes"))
        if nodes:
            return nodes
        # Defensive: PRD wording mentioned agent_spec.workflow.nodes
        workflow = agent_spec.get("workflow")
        if isinstance(workflow, dict):
            nested = _as_node_list(workflow.get("nodes"))
            if nested:
                return nested

    body = blueprint_body if isinstance(blueprint_body, dict) else {}
    workflow = body.get("workflow")
    if isinstance(workflow, dict):
        return _as_node_list(workflow.get("nodes"))
    return []


def node_id(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or "").strip()


def node_type(node: dict[str, Any]) -> str:
    return str(node.get("node_type") or "").strip().upper()


def node_next_ids(node: dict[str, Any]) -> list[str]:
    raw = node.get("next")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        nid = str(item).strip()
        if nid:
            out.append(nid)
    return out


def is_terminal_node(node: dict[str, Any]) -> bool:
    """True when node ends a path (empty next[] or explicit terminal type)."""
    ntype = node_type(node)
    if ntype in TERMINAL_NODE_TYPES:
        return True
    return len(node_next_ids(node)) == 0


def index_nodes_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for node in nodes:
        nid = node_id(node)
        if nid:
            indexed[nid] = node
    return indexed


def find_entry_node_ids(nodes: list[dict[str, Any]]) -> list[str]:
    """TRIGGER nodes, or sole node if no TRIGGER (PRD-QA-01 §5)."""
    triggers = [node_id(n) for n in nodes if node_type(n) == "TRIGGER" and node_id(n)]
    if triggers:
        return triggers
    if len(nodes) == 1 and node_id(nodes[0]):
        return [node_id(nodes[0])]
    # Fallback: nodes never referenced as next[] targets
    referenced: set[str] = set()
    for node in nodes:
        referenced.update(node_next_ids(node))
    entries = [node_id(n) for n in nodes if node_id(n) and node_id(n) not in referenced]
    return entries


def reachable_node_ids(
    nodes: list[dict[str, Any]],
    *,
    start_ids: list[str] | None = None,
) -> set[str]:
    """BFS from entry nodes along next[]."""
    by_id = index_nodes_by_id(nodes)
    starts = start_ids if start_ids is not None else find_entry_node_ids(nodes)
    seen: set[str] = set()
    queue: list[str] = [s for s in starts if s in by_id]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        node = by_id.get(current)
        if node is None:
            continue
        for nxt in node_next_ids(node):
            if nxt not in seen and nxt in by_id:
                queue.append(nxt)
    return seen


def orphan_node_ids(nodes: list[dict[str, Any]]) -> list[str]:
    """Nodes not reachable from TRIGGER/entry — for no_orphan_nodes."""
    all_ids = [node_id(n) for n in nodes if node_id(n)]
    reachable = reachable_node_ids(nodes)
    return [nid for nid in all_ids if nid not in reachable]


def node_reaches_terminal(
    nodes: list[dict[str, Any]],
    start_id: str,
) -> bool:
    """
    True if every path from start_id reaches a terminal node.

    Detects cycles: visiting a node already on the current path without
    finding a terminal ⇒ fails for that branch.
    Dangling next pointers (unknown child ids) fail — every branch must exit.
    """
    by_id = index_nodes_by_id(nodes)
    if start_id not in by_id:
        return False

    def walk(nid: str, path: set[str]) -> bool:
        if nid in path:
            return False  # cycle without terminal
        node = by_id.get(nid)
        if node is None:
            return False
        if is_terminal_node(node):
            return True
        nxt = node_next_ids(node)
        if not nxt:
            # Empty next without terminal type still counts as terminal
            return True
        path.add(nid)
        # ALL outgoing edges must resolve and reach a terminal (not any()).
        ok = all(child in by_id and walk(child, path) for child in nxt)
        path.discard(nid)
        return ok

    return walk(start_id, set())


def nodes_missing_terminal(nodes: list[dict[str, Any]]) -> list[str]:
    """Node ids that cannot reach a terminal — for terminal_reachable FAIL."""
    missing: list[str] = []
    for node in nodes:
        nid = node_id(node)
        if not nid:
            continue
        if not node_reaches_terminal(nodes, nid):
            missing.append(nid)
    return missing


def _field_present(value: Any) -> bool:
    """Non-empty for collision_policy / measurement / consent strings."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return len(value) > 0
    return True


def resolve_agent_spec_field(
    package_payload: dict[str, Any] | None,
    field: str,
    *,
    blueprint_body: dict[str, Any] | None = None,
) -> Any:
    """Prefer agent_spec[field]; fallback to blueprint root field."""
    payload = package_payload if isinstance(package_payload, dict) else {}
    agent_spec = payload.get("agent_spec")
    if isinstance(agent_spec, dict):
        value = agent_spec.get(field)
        if _field_present(value):
            return value

    body = blueprint_body if isinstance(blueprint_body, dict) else {}
    value = body.get(field)
    if _field_present(value):
        return value
    return None


def resolve_collision_policy(
    package_payload: dict[str, Any] | None,
    *,
    blueprint_body: dict[str, Any] | None = None,
) -> Any:
    return resolve_agent_spec_field(
        package_payload,
        "collision_policy",
        blueprint_body=blueprint_body,
    )


def resolve_measurement(
    package_payload: dict[str, Any] | None,
    *,
    blueprint_body: dict[str, Any] | None = None,
) -> Any:
    return resolve_agent_spec_field(
        package_payload,
        "measurement",
        blueprint_body=blueprint_body,
    )


def resolve_primary_metric(
    package_payload: dict[str, Any] | None,
    *,
    blueprint_body: dict[str, Any] | None = None,
) -> str | None:
    measurement = resolve_measurement(
        package_payload,
        blueprint_body=blueprint_body,
    )
    if not isinstance(measurement, dict):
        return None
    metric = measurement.get("primary_metric")
    if metric is None:
        return None
    text = str(metric).strip()
    return text or None


def resolve_rollback_strategy(package_payload: dict[str, Any] | None) -> str | None:
    payload = package_payload if isinstance(package_payload, dict) else {}
    rollback = payload.get("rollback")
    if not isinstance(rollback, dict):
        return None
    strategy = rollback.get("strategy")
    if strategy is None:
        return None
    text = str(strategy).strip()
    return text or None


def resolve_audience_consent(
    package_payload: dict[str, Any] | None,
    *,
    blueprint_body: dict[str, Any] | None = None,
) -> str | None:
    payload = package_payload if isinstance(package_payload, dict) else {}
    agent_spec = payload.get("agent_spec")
    if isinstance(agent_spec, dict):
        audience = agent_spec.get("audience")
        if isinstance(audience, dict):
            consent = audience.get("consent")
            if consent is not None and str(consent).strip():
                return str(consent).strip()
    body = blueprint_body if isinstance(blueprint_body, dict) else {}
    audience = body.get("audience")
    if isinstance(audience, dict):
        consent = audience.get("consent")
        if consent is not None and str(consent).strip():
            return str(consent).strip()
    return None


def node_text_blob(node: dict[str, Any]) -> str:
    """Lowercased text from node for consent keyword matching."""
    parts: list[str] = []
    for key in ("node_type", "platform_primitive", "label", "name"):
        val = node.get(key)
        if val is not None:
            parts.append(str(val))
    config = node.get("config")
    if isinstance(config, dict):
        for key in ("description", "condition", "expression", "field"):
            val = config.get(key)
            if val is not None:
                parts.append(str(val))
    return " ".join(parts).lower()


CONSENT_KEYWORDS = frozenset(
    {
        "consent",
        "opt-in",
        "opt in",
        "optin",
        "unsubscribe",
        "suppression",
        "doi",
        "double opt",
    }
)

# PRD-QA-01 §5 consent_branching — CONDITION or equivalent.
CONDITION_LIKE_NODE_TYPES = frozenset(
    {
        "CONDITION",
        "BRANCH",
        "DECISION",
        "FILTER",
        "GATE",
        "IF",
        "SWITCH",
    }
)


def node_references_consent(node: dict[str, Any]) -> bool:
    blob = node_text_blob(node)
    return any(keyword in blob for keyword in CONSENT_KEYWORDS)


def is_condition_like_node(node: dict[str, Any]) -> bool:
    """True for CONDITION / BRANCH / DECISION-style nodes."""
    return node_type(node) in CONDITION_LIKE_NODE_TYPES


def consent_condition_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nodes that satisfy consent_branching keyword path (CONDITION + consent text)."""
    return [
        n
        for n in nodes
        if is_condition_like_node(n) and node_references_consent(n)
    ]


def branch_exists_after_entries(
    nodes: list[dict[str, Any]],
    *,
    entry_ids: list[str] | None = None,
) -> bool:
    """
    True when the reachable graph after entry has a real branch decision.

    PRD-QA-01 §5 audience path requires \"a branch exists after trigger\".
    A single outgoing edge from TRIGGER (linear MESSAGE→FINISH) is NOT a branch.
    Count as branch when reachable subgraph has:
    - a CONDITION-like node, or
    - any node with ≥2 outgoing next[] edges (true fork).
    """
    starts = entry_ids if entry_ids is not None else find_entry_node_ids(nodes)
    if not starts:
        return False
    by_id = index_nodes_by_id(nodes)
    reachable = reachable_node_ids(nodes, start_ids=starts)
    for nid in reachable:
        node = by_id.get(nid)
        if node is None:
            continue
        # Entry TRIGGER alone with one next is not enough; CONDITION/fork is.
        if nid not in starts and is_condition_like_node(node):
            return True
        if is_condition_like_node(node) and nid in starts:
            return True
        if len(node_next_ids(node)) >= 2:
            return True
    return False
