"""Workflow build package generator (PRD-WF-01 / BL-016)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.audit import append_audit_event, stable_json
from dataruns.capabilities.contract import (
    DEFAULT_HUMAN_FALLBACK_CAPABILITY,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
)
from dataruns.capabilities.resolver import resolve_blueprint_capabilities
from dataruns.use_cases.constants import HANDOFF_PACKAGE_SPEC
from dataruns.use_cases.models import UseCaseBlueprint, UseCasePilot, WorkflowBuildPackage
from dataruns.use_cases.recommend import (
    STATUS_BLOCKED_CHECKS,
    STATUS_BLOCKED_DCS,
    STATUS_BLOCKED_MODE,
    STATUS_UNAVAILABLE,
    _gates_from_blueprint,
    build_gates_snapshot,
    evaluate_pilot,
    is_buildable_status,
    resolve_recommendation_context,
)
from dataruns.use_cases.serialize import _node_field_chips
from tenants.models import Company, User


class BuildPackageError(Exception):
    """Pilot cannot generate a build package."""

    def __init__(
        self,
        *,
        code: str,
        detail: str,
        status: int = 409,
        blockers: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.status = status
        self.blockers = blockers or []
        super().__init__(detail)


@dataclass
class BuildPackageResult:
    package: WorkflowBuildPackage
    payload: dict[str, Any]


def _package_content_hash(payload: dict[str, Any]) -> str:
    """Hash package body excluding volatile provenance timestamps."""
    clone = dict(payload)
    provenance = dict(clone.get("provenance") or {})
    provenance.pop("generated_at", None)
    provenance.pop("generated_by_email", None)
    clone["provenance"] = provenance
    return hashlib.sha256(stable_json(clone).encode("utf-8")).hexdigest()


def _resolve_capabilities(
    body: dict[str, Any],
    *,
    fallback: str,
) -> list[dict[str, Any]]:
    """
    CAP-01: Matrix-backed capability_resolution via registry resolver.

    Prefer ``resolve_blueprint_capabilities`` for route + rows together.
    """
    outcome = resolve_blueprint_capabilities(
        body,
        default_fallback=fallback or DEFAULT_HUMAN_FALLBACK_CAPABILITY,
    )
    return outcome.capability_resolution


def _human_guide_from_blueprint(body: dict[str, Any]) -> dict[str, Any]:
    content = body.get("content") if isinstance(body.get("content"), dict) else {}
    nodes = []
    workflow = body.get("workflow") if isinstance(body.get("workflow"), dict) else {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        nodes.append(
            {
                "node_id": node.get("node_id"),
                "node_type": node.get("node_type"),
                "title": (
                    node.get("label")
                    or node.get("name")
                    or node.get("platform_primitive")
                    or config.get("description")
                ),
                "description": config.get("description"),
                "configured_by": node.get("configured_by"),
                "executed_by": node.get("executed_by"),
                "fields": _node_field_chips(node),
            }
        )
    return {
        "steps": nodes,
        "brand_dna_required": content.get("brand_dna_required"),
        "localisation_required": content.get("localisation_required"),
        "human_signoff": content.get("human_signoff"),
    }


def _agent_spec_from_blueprint(body: dict[str, Any]) -> dict[str, Any]:
    workflow = body.get("workflow") if isinstance(body.get("workflow"), dict) else {}
    return {
        "audience": body.get("audience"),
        "trigger": body.get("trigger"),
        "nodes": workflow.get("nodes") or [],
        "measurement": body.get("measurement"),
        "suppressions": body.get("suppressions"),
        "frequency_policy": body.get("frequency_policy"),
        "collision_policy": body.get("collision_policy"),
    }


def _handoff_stub_from_blueprint(body: dict[str, Any]) -> dict[str, Any]:
    """Build handoff stub for BL-016 package JSON.

    GAP-01 Slice D (W7-03 / W9-02): always emit ``HANDOFF_PACKAGE_SPEC``.
    Pack blueprints may still say ``MCP_ACTION_OBJECT_AND_A2A_TASK_SPEC``;
    that is format-string theater until Track B ships a real MCP runtime.
    """
    handoff = body.get("handoff") if isinstance(body.get("handoff"), dict) else {}
    return {
        "format": HANDOFF_PACKAGE_SPEC,
        "idempotency_key_template": handoff.get("idempotency_key_template"),
        "activation_state": handoff.get("activation_state", "STAGED_NOT_LIVE"),
    }


def normalize_handoff_stub_format(payload: dict[str, Any]) -> dict[str, Any]:
    """GAP-01 Slice D: force honest handoff stub format on API responses.

    Returns a shallow-copied payload. Does **not** rewrite stored DB rows or
    recompute ``package_content_hash`` (immutable generate semantics).

    Until Track B ships a real MCP runtime (D0.1), always emit
    ``HANDOFF_PACKAGE_SPEC`` whenever ``handoff_stub`` is a dict — including
    empty/missing/case-variant theater labels.
    """
    out = dict(payload)
    stub = out.get("handoff_stub")
    if not isinstance(stub, dict):
        return out
    stub_out = dict(stub)
    stub_out["format"] = HANDOFF_PACKAGE_SPEC
    out["handoff_stub"] = stub_out
    return out


def assemble_build_package_payload(
    *,
    package_id: str,
    pilot: UseCasePilot,
    blueprint: UseCaseBlueprint,
    company: Company,
    ctx_snapshot: dict[str, Any],
    gates: dict[str, Any],
    gates_snapshot: dict[str, Any],
    provisional_supplemental: bool,
    generated_by: User | None,
) -> dict[str, Any]:
    """Build the BL-016 package JSON (PRD §7.2).

    CAP-01: ``route`` + ``capability_resolution`` come from
    ``resolve_blueprint_capabilities`` (Matrix registry). Existing stored
    packages are not rewritten here — see ``serialize_build_package`` (§5.2).
    """
    body = blueprint.body if isinstance(blueprint.body, dict) else {}
    content = body.get("content") if isinstance(body.get("content"), dict) else {}
    qa = body.get("qa") if isinstance(body.get("qa"), dict) else {}
    approval = body.get("approval") if isinstance(body.get("approval"), dict) else {}
    rollback = body.get("rollback") if isinstance(body.get("rollback"), dict) else {}
    provenance_src = (
        body.get("provenance") if isinstance(body.get("provenance"), dict) else {}
    )
    fallback = pilot.fallback or DEFAULT_HUMAN_FALLBACK_CAPABILITY
    resolved = resolve_blueprint_capabilities(
        body,
        default_fallback=fallback,
    )
    capability_resolution = resolved.capability_resolution
    route = resolved.route or PACKAGE_ROUTE_HUMAN_FALLBACK

    payload: dict[str, Any] = {
        "package_id": package_id,
        "use_case_id": pilot.use_case_id,
        "blueprint_id": blueprint.blueprint_id,
        "variant_id": body.get("variant_id"),
        "schema_version": blueprint.schema_version,
        "pilot_rank": pilot.pilot_rank,
        "title": pilot.title,
        "route": route,
        "provisional_supplemental": provisional_supplemental,
        "capability_resolution": capability_resolution,
        "human_guide": _human_guide_from_blueprint(body),
        "agent_spec": _agent_spec_from_blueprint(body),
        "data_contract": body.get("data_contract") or {},
        "gates_snapshot": gates_snapshot,
        "qa_requirements": {
            "minimum_score": qa.get("minimum_score", 80),
            "hard_tests": list(qa.get("hard_tests") or []),
        },
        "approval_requirements": {
            "required_before_write": approval.get("required_before_write"),
            "required_before_activation": approval.get("required_before_activation"),
            "roles": list(approval.get("roles") or []),
            "token_binds": list(approval.get("token_binds") or []),
        },
        "rollback": {
            "strategy": rollback.get("strategy"),
            "max_partial_write_minutes": rollback.get("max_partial_write_minutes"),
        },
        "handoff_stub": _handoff_stub_from_blueprint(body),
        "content_state": {
            "agent_output_state": content.get("agent_output_state", "DRAFT"),
        },
        "connected_instances": [],
        "hashes": {
            "blueprint_content_hash": blueprint.content_hash,
            "package_content_hash": "",
        },
        "provenance": {
            **provenance_src,
            "company_id": str(company.id),
            "dcs_data_run_id": ctx_snapshot.get("dcs_data_run_id"),
            "af_assessment_id": ctx_snapshot.get("af_assessment_id"),
            "af_mode": ctx_snapshot.get("af_mode"),
            "headline_score": ctx_snapshot.get("headline_score"),
            "generated_at": timezone.now().isoformat(),
            "generated_by_user_id": str(generated_by.id) if generated_by else None,
            "generated_by_email": generated_by.email if generated_by else None,
        },
    }
    payload["hashes"]["package_content_hash"] = _package_content_hash(payload)
    return payload


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


@transaction.atomic
def generate_build_package(
    *,
    company: Company,
    use_case_id: str,
    generated_by: User | None,
) -> BuildPackageResult:
    """
    Generate and persist a workflow build package for a buildable pilot.

    Raises BuildPackageError when pilot is hard-blocked or missing.
    """
    pilot = (
        UseCasePilot.objects.select_related("blueprint")
        .prefetch_related("stage_maps")
        .filter(use_case_id=use_case_id.upper())
        .first()
    )
    if pilot is None:
        raise BuildPackageError(
            code="not_found",
            detail="Use case not found.",
            status=404,
        )

    blueprint = getattr(pilot, "blueprint", None)
    if blueprint is None:
        raise BuildPackageError(
            code="blueprint_missing",
            detail="Blueprint not seeded for this pilot.",
            status=409,
        )

    ctx = resolve_recommendation_context(company=company)
    evaluation = evaluate_pilot(pilot, ctx)
    status = evaluation.get("status") or STATUS_UNAVAILABLE
    if not is_buildable_status(status):
        raise BuildPackageError(
            code={
                STATUS_BLOCKED_CHECKS: "blocked_checks",
                STATUS_BLOCKED_DCS: "blocked_dcs_score",
                STATUS_BLOCKED_MODE: "blocked_mode",
                STATUS_UNAVAILABLE: "unavailable",
            }.get(status, "not_buildable"),
            detail=f"Pilot is {status}.",
            status=409,
            blockers=evaluation.get("blockers") or [],
        )

    body = blueprint.body if isinstance(blueprint.body, dict) else {}
    gates = _gates_from_blueprint(body)
    provisional = bool(evaluation.get("provisional_supplemental"))
    gates_snapshot = build_gates_snapshot(
        gates=gates,
        ctx=ctx,
        provisional_supplemental=provisional,
    )

    package_id = str(uuid.uuid4())
    ctx_snapshot = {
        "dcs_data_run_id": ctx.dcs_data_run_id,
        "af_assessment_id": ctx.af_assessment_id,
        "af_mode": ctx.af_mode,
        "headline_score": ctx.headline_score,
    }
    payload = assemble_build_package_payload(
        package_id=package_id,
        pilot=pilot,
        blueprint=blueprint,
        company=company,
        ctx_snapshot=ctx_snapshot,
        gates=gates,
        gates_snapshot=gates_snapshot,
        provisional_supplemental=provisional,
        generated_by=generated_by,
    )

    record = WorkflowBuildPackage.objects.create(
        id=uuid.UUID(package_id),
        company=company,
        pilot=pilot,
        payload=payload,
        provisional_supplemental=provisional,
        blueprint_content_hash=blueprint.content_hash,
        package_content_hash=payload["hashes"]["package_content_hash"],
        dcs_data_run_id=ctx.dcs_data_run_id,
        af_assessment_id=_parse_uuid(ctx.af_assessment_id),
        generated_by=generated_by,
    )

    append_audit_event(
        company=company,
        action="workflow.build_package_generated",
        summary=f"Build package generated for {pilot.use_case_id}",
        performed_by=generated_by.email if generated_by else "system",
        actor_user_id=str(generated_by.id) if generated_by else None,
        metadata={
            "package_id": package_id,
            "use_case_id": pilot.use_case_id,
            "blueprint_id": blueprint.blueprint_id,
            "provisional_supplemental": provisional,
            "route": payload.get("route"),
            "package_content_hash": payload["hashes"]["package_content_hash"],
        },
    )

    return BuildPackageResult(package=record, payload=payload)


def serialize_build_package(record: WorkflowBuildPackage) -> dict[str, Any]:
    """GET /build-packages/{id}/ response body.

    PRD-CAP-01 §5.2 — already-generated packages are immutable in storage: this
    function does not rewrite the DB row. New generates run the Matrix resolver.

    GAP-01 Slice D — API honesty: ``handoff_stub.format`` theater
    (``MCP_ACTION_OBJECT_AND_A2A_TASK_SPEC``) is normalized to
    ``HANDOFF_PACKAGE_SPEC`` on read so Download JSON / GET never claim a live
    MCP action object. Stored payload + ``package_content_hash`` stay as generated.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    honest = normalize_handoff_stub_format(payload)
    return {
        **honest,
        "created_at": record.created_at.isoformat(),
        "use_case_id": record.use_case_id,
        "provisional_supplemental": record.provisional_supplemental,
    }
