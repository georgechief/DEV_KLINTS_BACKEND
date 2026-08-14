"""Excel sheet 02 ME-02 workflow measurement join (PRD-DCS-04 batch 4c).

Uses Manago ``api/workflow/list`` + ``api/workflow/statistics`` when ingested
into ConnectorSnapshot raw.
"""

from __future__ import annotations

from typing import Any

from dataruns.dcs.lifecycle_join import _latest_connector_raw
from tenants.models import Company


def build_workflow_snapshot(*, company: Company) -> dict[str, Any]:
    manago_raw = _latest_connector_raw(company=company, platform="manago_ai")
    workflows = [w for w in (manago_raw.get("workflows") or []) if isinstance(w, dict)]
    stats_rows = [
        s for s in (manago_raw.get("workflow_stats") or []) if isinstance(s, dict)
    ]
    stats_by_id = {
        str(s.get("externalId")): s for s in stats_rows if s.get("externalId") is not None
    }

    live = []
    with_purchase = []
    zero_outcome = []
    for workflow in workflows:
        wid = str(workflow.get("externalId") or workflow.get("id") or "")
        if not wid:
            continue
        live.append(workflow)
        stats = stats_by_id.get(wid) or {}
        revenue = stats.get("revenueStats") if isinstance(stats.get("revenueStats"), dict) else {}
        # Excel: PURCHASE linkage / measurable outcome path.
        # revenueStats with transaction counts or sales ⇒ measurement wired.
        tx = int(revenue.get("totalTransactionNumber") or 0)
        sales = float(revenue.get("totalSales") or 0)
        stats_ok = bool(stats.get("stats_ok"))
        measurable = stats_ok and (tx > 0 or sales > 0)
        # If stats endpoint returns an object (even zeros), conversion measurement
        # is wired — zero activity ≠ unwired. Unwired = stats missing/failed.
        if not stats_ok:
            zero_outcome.append(
                {
                    "externalId": wid,
                    "name": workflow.get("name"),
                    "reason": "no_analytics",
                }
            )
        elif measurable:
            with_purchase.append(wid)
        else:
            # Wired but zero conversions in window — still counts as measured path.
            with_purchase.append(wid)

    workflows_available = bool(workflows) and manago_raw.get("workflows_fetch_note") is None
    # Also available if we got an empty successful list (note is None and key present).
    if "workflows" in manago_raw and manago_raw.get("workflows_fetch_note") is None:
        workflows_available = True

    return {
        "workflows": [
            {
                "id": w.get("id"),
                "externalId": w.get("externalId"),
                "name": w.get("name"),
                "createdOn": w.get("createdOn"),
            }
            for w in workflows[:200]
        ],
        "measurement": {
            "workflows_available": workflows_available,
            "live_workflow_count": len(live),
            "with_purchase_linkage": len(with_purchase),
            "zero_outcome_path": len(zero_outcome),
            "zero_outcome_sample": zero_outcome[:50],
            "workflow_stats_count": len(stats_rows),
            "funnel_membership_ids_seen": 0,
            "raw_enrichment": {
                "manago_contacts_from_raw": bool(manago_raw.get("contacts")),
                "workflow_definitions_present": workflows_available,
                "workflow_analytics_present": bool(stats_rows),
                "workflows_fetch_note": manago_raw.get("workflows_fetch_note"),
            },
        },
    }
