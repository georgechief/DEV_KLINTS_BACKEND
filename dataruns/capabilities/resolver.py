"""Capability Matrix package-route resolver (PRD-CAP-01 Step 4).

Uses registry seed (file-only). Does not enable MCP Send / publish (HO-02).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from dataruns.capabilities.contract import (
    CAP_ID_MCP_WORKFLOW_UPSERT,
    CAP_MODE_WRITE,
    CAP_MODE_WRITE_ARTIFACT,
    CAP_STATUS_CONFIRMED_LIMITED,
    CAP_STATUS_CONFIRMED_LIVE,
    CAP_STATUS_DISCOVERY_REQUIRED,
    CAP_STATUS_NOT_SUPPORTED,
    CAP_STATUS_REQUIRED_BUILD,
    DEFAULT_HUMAN_FALLBACK_CAPABILITY,
    PACKAGE_ROUTE_HUMAN_FALLBACK,
    PACKAGE_ROUTE_MCP,
    RESOLVED_HUMAN_FALLBACK,
    RESOLVED_MCP,
    RESOLVED_NOT_CONFIRMED,
    is_human_operator_channel,
    is_manago_mcp_write_channel,
    upsert_is_execute_eligible,
)
from dataruns.capabilities.registry import get_capability

_NOT_LIVE_STATUSES = frozenset(
    {
        CAP_STATUS_DISCOVERY_REQUIRED,
        CAP_STATUS_REQUIRED_BUILD,
        CAP_STATUS_NOT_SUPPORTED,
    }
)


@dataclass(frozen=True)
class CapabilityResolveOutcome:
    """Package capability_resolution[] + route (WF-01 / CAP-01)."""

    capability_resolution: list[dict[str, Any]]
    route: str


def _capability_id_like(value: str | None) -> bool:
    """True when value looks like a Matrix capability id (not Matrix prose)."""
    text = str(value or "").strip()
    if not text or " " in text:
        return False
    return "." in text


def _lookup(
    capability_id: str,
    *,
    overrides: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if overrides and capability_id in overrides:
        row = overrides[capability_id]
        return deepcopy(row) if isinstance(row, dict) else None
    return get_capability(capability_id)


def _is_live_ready(record: dict[str, Any]) -> bool:
    """
    Confirmed Matrix row ready to pass through (PRD §4.2).

    MCP WRITE requires non-empty evidence; other confirmed channels pass.
    """
    status = str(record.get("status") or "").strip().upper()
    if status not in {CAP_STATUS_CONFIRMED_LIVE, CAP_STATUS_CONFIRMED_LIMITED}:
        return False
    channel = str(record.get("channel") or "")
    mode = str(record.get("mode") or "").strip().upper()
    evidence = record.get("evidence")
    if mode in {CAP_MODE_WRITE, CAP_MODE_WRITE_ARTIFACT} and is_manago_mcp_write_channel(
        channel
    ):
        return isinstance(evidence, list) and len(evidence) > 0
    if is_human_operator_channel(channel):
        return True
    # REST / Agent / other confirmed (incl. READ)
    return True


def _pick_fallback_used(
    *,
    dep_fallback: str | None,
    matrix_fallback: str | None,
    default_fallback: str,
    force_human_build: bool,
) -> str | None:
    for candidate in (dep_fallback, matrix_fallback):
        text = str(candidate or "").strip()
        if text and _capability_id_like(text):
            return text
    if force_human_build:
        return str(default_fallback or DEFAULT_HUMAN_FALLBACK_CAPABILITY).strip() or (
            DEFAULT_HUMAN_FALLBACK_CAPABILITY
        )
    # Prose-only Matrix fallback is not a capability id — ignore for fallback_used.
    return None


def resolve_dependency(
    dep: dict[str, Any],
    *,
    default_fallback: str = DEFAULT_HUMAN_FALLBACK_CAPABILITY,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Resolve one blueprint capability_dependencies[] row.

    Returns capability_resolution row with optional matrix_status + channel.
    ``required_status`` is passed through (PRD §4.4); live vs fallback outcome
    is encoded in ``resolved_status`` / ``fallback_used``.
    """
    cap_id = str(dep.get("capability_id") or "").strip()
    required_status = dep.get("required_status")
    dep_fallback_raw = dep.get("fallback")
    dep_fallback = (
        str(dep_fallback_raw).strip() if dep_fallback_raw not in (None, "") else None
    )

    if not cap_id:
        return {
            "capability_id": "",
            "required_status": required_status,
            "resolved_status": RESOLVED_NOT_CONFIRMED,
            "fallback_used": None,
        }

    record = _lookup(cap_id, overrides=overrides)
    matrix_status = (
        str(record.get("status") or "").strip().upper() if record else None
    )
    channel = str(record.get("channel") or "").strip() if record else None
    matrix_fallback = str(record.get("fallback") or "").strip() if record else None

    base: dict[str, Any] = {
        "capability_id": cap_id,
        "required_status": required_status,
        "resolved_status": RESOLVED_NOT_CONFIRMED,
        "fallback_used": None,
    }
    if matrix_status:
        base["matrix_status"] = matrix_status
    if channel:
        base["channel"] = channel

    is_upsert = cap_id == CAP_ID_MCP_WORKFLOW_UPSERT

    # UPSERT special-case: execute-eligible → MCP alias; else always HUMAN_FALLBACK.
    if is_upsert:
        if record is not None and upsert_is_execute_eligible(
            status=matrix_status,
            channel=channel,
            evidence=(
                record.get("evidence")
                if isinstance(record.get("evidence"), list)
                else []
            ),
            mode=str(record.get("mode") or CAP_MODE_WRITE),
        ):
            base["resolved_status"] = RESOLVED_MCP
            base["fallback_used"] = None
            return base
        base["resolved_status"] = RESOLVED_HUMAN_FALLBACK
        base["fallback_used"] = _pick_fallback_used(
            dep_fallback=dep_fallback,
            matrix_fallback=matrix_fallback,
            default_fallback=default_fallback,
            force_human_build=True,
        )
        return base

    if record is None:
        fallback_used = _pick_fallback_used(
            dep_fallback=dep_fallback,
            matrix_fallback=None,
            default_fallback=default_fallback,
            force_human_build=False,
        )
        if fallback_used:
            base["resolved_status"] = RESOLVED_HUMAN_FALLBACK
            base["fallback_used"] = fallback_used
        else:
            base["resolved_status"] = RESOLVED_NOT_CONFIRMED
            base["fallback_used"] = None
        return base

    if matrix_status in _NOT_LIVE_STATUSES or not _is_live_ready(record):
        fallback_used = _pick_fallback_used(
            dep_fallback=dep_fallback,
            matrix_fallback=matrix_fallback,
            default_fallback=default_fallback,
            force_human_build=False,
        )
        if fallback_used:
            base["resolved_status"] = RESOLVED_HUMAN_FALLBACK
            base["fallback_used"] = fallback_used
        else:
            base["resolved_status"] = RESOLVED_NOT_CONFIRMED
            base["fallback_used"] = None
        return base

    # Live-ready confirmed — pass Matrix status through.
    base["resolved_status"] = matrix_status
    base["fallback_used"] = None
    return base


def resolve_capabilities(
    dependencies: list[Any] | None,
    *,
    default_fallback: str = DEFAULT_HUMAN_FALLBACK_CAPABILITY,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Resolve all blueprint capability_dependencies[] rows."""
    rows: list[dict[str, Any]] = []
    for dep in dependencies or []:
        if not isinstance(dep, dict):
            continue
        if not str(dep.get("capability_id") or "").strip():
            continue
        rows.append(
            resolve_dependency(
                dep,
                default_fallback=default_fallback,
                overrides=overrides,
            )
        )
    return rows


def resolve_package_route(capability_resolution: list[dict[str, Any]]) -> str:
    """
    route = MCP iff UPSERT row resolved_status == MCP; else HUMAN_FALLBACK.
    """
    for row in capability_resolution:
        if str(row.get("capability_id") or "").strip() != CAP_ID_MCP_WORKFLOW_UPSERT:
            continue
        if str(row.get("resolved_status") or "").strip().upper() == RESOLVED_MCP:
            return PACKAGE_ROUTE_MCP
    return PACKAGE_ROUTE_HUMAN_FALLBACK


def resolve_blueprint_capabilities(
    body: dict[str, Any] | None,
    *,
    default_fallback: str = DEFAULT_HUMAN_FALLBACK_CAPABILITY,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> CapabilityResolveOutcome:
    """Resolve capability_resolution[] + route from a blueprint body dict."""
    deps = None
    if isinstance(body, dict):
        deps = body.get("capability_dependencies")
    resolution = resolve_capabilities(
        deps if isinstance(deps, list) else [],
        default_fallback=default_fallback,
        overrides=overrides,
    )
    return CapabilityResolveOutcome(
        capability_resolution=resolution,
        route=resolve_package_route(resolution),
    )
