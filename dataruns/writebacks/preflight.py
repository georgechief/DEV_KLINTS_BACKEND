"""Preflight gates before writeback preview/execute (SP-07, connectors, etc.)."""

from __future__ import annotations

from typing import Any

from dataruns.dcs.worklist import extract_dcs_payload, get_latest_terminal_dcs_run
from tenants.models import Company, Connector


def run_preflight(*, company: Company, mapping: dict[str, Any]) -> str | None:
    blocked = _connector_preflight(company=company, mapping=mapping)
    if blocked:
        return blocked
    if mapping.get("requires_consent_namespace_clean"):
        return _sp07_namespace_clean(company=company)
    return None


def _connector_preflight(*, company: Company, mapping: dict[str, Any]) -> str | None:
    platforms: set[str] = set()
    for operation in mapping.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        target = str(operation.get("target") or "manago")
        if target in ("manago", "manago_ai"):
            platforms.add("manago_ai")
        elif target == "shopify":
            platforms.add("shopify")

    for platform in sorted(platforms):
        connector = (
            Connector.objects.filter(company=company, name=platform)
            .order_by("-updated_at")
            .first()
        )
        if connector is None or connector.status not in ("connected", "degraded"):
            return f"connector_not_connected:{platform}"
    return None


def _sp07_namespace_clean(*, company: Company) -> str | None:
    data_run = get_latest_terminal_dcs_run(company=company)
    if data_run is None:
        return "consent_namespace_not_clean"
    payload = extract_dcs_payload(data_run.metadata or {})
    for row in payload.get("check_results") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("check_id") or "").upper() != "SP-07":
            continue
        status = str(row.get("status") or "").upper()
        if status == "PASS":
            return None
        return "consent_namespace_not_clean"
    return "consent_namespace_not_clean"
