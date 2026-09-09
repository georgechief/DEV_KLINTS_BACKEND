"""Serialize use-case catalogue payloads (PRD-UC-01 §9)."""

from __future__ import annotations

from typing import Any

from dataruns.use_cases.models import UseCasePilot


def _gates_summary(body: dict[str, Any]) -> dict[str, Any]:
    gates = body.get("gates") if isinstance(body.get("gates"), dict) else {}
    return {
        "min_dcs": gates.get("min_dcs"),
        "gating_check_ids": list(gates.get("gating_check_ids") or []),
        "architecture_modes": list(gates.get("architecture_modes") or []),
    }


def _execution_meta(pilot: UseCasePilot) -> dict[str, Any]:
    return {
        "mcp_dependency": pilot.mcp_dependency,
        "fallback": pilot.fallback or "HUMAN.WORKFLOW.BUILD",
        "build_available": False,
        "note": "Human build guide only until MCP discovery.",
    }


def _node_field_chips(node: dict[str, Any]) -> list[str]:
    """Frontend_design step chips: config + who configures/executes."""
    fields: list[str] = []
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    for key, value in config.items():
        if key in {"description", "label", "name"} or value in (None, ""):
            continue
        if isinstance(value, (dict, list)):
            continue
        fields.append(f"{key} = {value}")
    configured = node.get("configured_by")
    executed = node.get("executed_by")
    if configured:
        fields.append(f"configured_by = {configured}")
    if executed:
        fields.append(f"executed_by = {executed}")
    return fields


def serialize_pilot_catalogue_row(pilot: UseCasePilot) -> dict[str, Any]:
    """Lightweight row for GET /use-cases/ — no full workflow nodes."""
    blueprint = getattr(pilot, "blueprint", None)
    raw_body = blueprint.body if blueprint is not None else {}
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
    gates = _gates_summary(body)
    stage_ids = list(
        pilot.stage_maps.filter(is_primary=True)
        .order_by("stage_id")
        .values_list("stage_id", flat=True)
    )
    node_count = 0
    workflow = body.get("workflow")
    if isinstance(workflow, dict):
        nodes = workflow.get("nodes")
        if isinstance(nodes, list):
            node_count = len(nodes)

    return {
        "use_case_id": pilot.use_case_id,
        "pilot_rank": pilot.pilot_rank,
        "title": pilot.title,
        "release": pilot.release,
        "manifest_status": pilot.manifest_status,
        "business_objective": body.get("business_objective"),
        "solution_type": body.get("solution_type"),
        "gates": gates,
        "primary_stage_ids": stage_ids,
        "node_count": node_count,
        "execution": _execution_meta(pilot),
        "blueprint_id": blueprint.blueprint_id if blueprint else None,
    }


def serialize_pilot_detail(pilot: UseCasePilot) -> dict[str, Any]:
    """Pilot + blueprint summary for GET /use-cases/{id}/."""
    row = serialize_pilot_catalogue_row(pilot)
    blueprint = getattr(pilot, "blueprint", None)
    raw_body = blueprint.body if blueprint is not None else {}
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}

    trigger = body.get("trigger") if isinstance(body.get("trigger"), dict) else {}
    audience = body.get("audience") if isinstance(body.get("audience"), dict) else {}
    measurement = (
        body.get("measurement") if isinstance(body.get("measurement"), dict) else {}
    )
    workflow = body.get("workflow") if isinstance(body.get("workflow"), dict) else {}
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []

    simplified_nodes = []
    for node in nodes[:50]:
        if not isinstance(node, dict):
            continue
        simplified_nodes.append(
            {
                "node_id": node.get("node_id"),
                "node_type": node.get("node_type"),
                "label": (
                    node.get("label")
                    or node.get("name")
                    or node.get("platform_primitive")
                ),
                "platform_primitive": node.get("platform_primitive"),
                "description": (
                    (node.get("config") or {}).get("description")
                    if isinstance(node.get("config"), dict)
                    else None
                ),
                "configured_by": node.get("configured_by"),
                "executed_by": node.get("executed_by"),
                "fields": _node_field_chips(node),
            }
        )

    data_contract = (
        body.get("data_contract") if isinstance(body.get("data_contract"), dict) else {}
    )
    approval = body.get("approval") if isinstance(body.get("approval"), dict) else {}
    suppressions_raw = body.get("suppressions")
    suppressions = (
        [str(item) for item in suppressions_raw if str(item).strip()]
        if isinstance(suppressions_raw, list)
        else []
    )
    target_platform = body.get("target_platform")
    platforms = (
        list(target_platform)
        if isinstance(target_platform, list)
        else []
    )

    row.update(
        {
            "schema_version": blueprint.schema_version if blueprint else None,
            "content_hash": blueprint.content_hash if blueprint else None,
            "loaded_at": blueprint.loaded_at.isoformat() if blueprint else None,
            "variant_id": body.get("variant_id"),
            "target_platform": platforms,
            "trigger": {
                "description": trigger.get("description"),
                "timezone": trigger.get("timezone"),
            },
            "audience": {
                "definition": audience.get("definition"),
                "consent": audience.get("consent"),
            },
            "measurement": {
                "primary_kpi": measurement.get("primary_kpi")
                or measurement.get("primary_metric"),
                "success_criteria": measurement.get("success_criteria"),
            },
            "data_contract": {
                "required_fields": list(data_contract.get("required_fields") or []),
                "required_entities": list(data_contract.get("required_entities") or []),
            },
            "approval": {
                "roles": list(approval.get("roles") or []),
            },
            "suppressions": suppressions,
            "workflow_summary": {
                "node_count": len(nodes),
                "nodes": simplified_nodes,
                "truncated": len(nodes) > len(simplified_nodes),
            },
        }
    )
    return row


def list_catalogue_payload() -> dict[str, Any]:
    pilots = (
        UseCasePilot.objects.select_related("blueprint")
        .prefetch_related("stage_maps")
        .order_by("pilot_rank")
    )
    results = [serialize_pilot_catalogue_row(p) for p in pilots]
    return {
        "pilot_count": len(results),
        "pilots": results,
    }
