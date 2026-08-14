"""Phase B inventory probes — WF-01, TAG-01, PROP-01 (PRD-AF-01 §7.1)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timezone as dt_timezone
from typing import Any

from django.utils import timezone

from dataruns.architecture.constants import MANAGO_CONNECTOR_NAME, MANAGO_ELIGIBLE_STATUSES
from dataruns.architecture.models import ArchitectureAsset
from dataruns.connectors.base import decrypt_connector_config
from dataruns.connectors.manago_ai.client import (
    _fetch_contact_tags,
    _fetch_workflows,
    _resolve_owner,
)
from tenants.models import Company, Connector, ConnectorSnapshot

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._:-]+")


@dataclass
class InventoryAsset:
    asset_id: str
    asset_type: str
    name: str
    status: str = ""
    definition: dict[str, Any] = field(default_factory=dict)
    capability_path: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    lifecycle_stage: str | None = None


@dataclass
class ProbeOutcome:
    probe_id: str
    status: str  # succeeded | partial | failed | incomplete
    evidence: dict[str, Any] = field(default_factory=dict)
    assets: list[InventoryAsset] = field(default_factory=list)


@dataclass
class InventoryResult:
    assets: list[InventoryAsset]
    probes: list[ProbeOutcome]
    evidence_coverage: float


def _slug(value: str, *, max_len: int = 180) -> str:
    cleaned = _SLUG_RE.sub("_", value.strip())[:max_len]
    return cleaned or "unknown"


def _now_iso() -> str:
    return timezone.now().astimezone(dt_timezone.utc).isoformat()


def _provenance(*, source: str, locator: str, value: Any = None) -> dict[str, Any]:
    return {
        "source_versions": {"manago_rest": "v2"},
        "created_at": _now_iso(),
        "evidence": [
            {
                "source": source,
                "locator": locator,
                "value": value,
                "observed_at": _now_iso(),
            }
        ],
    }


def _load_manago_connector(company: Company) -> Connector:
    return Connector.objects.get(
        company=company,
        name=MANAGO_CONNECTOR_NAME,
        status__in=MANAGO_ELIGIBLE_STATUSES,
    )


def _workflow_status(row: dict[str, Any]) -> str:
    for key in ("status", "state", "workflowStatus", "active"):
        raw = row.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool):
            return "active" if raw else "inactive"
        text = str(raw).strip()
        if text:
            return text
    return "unknown"


def _latest_manago_snapshot_data(company: Company) -> dict[str, Any]:
    snap = (
        ConnectorSnapshot.objects.filter(
            connector__company=company,
            connector__name=MANAGO_CONNECTOR_NAME,
        )
        .order_by("-created_at")
        .first()
    )
    if snap is None or not isinstance(snap.snapshot_data, dict):
        return {}
    return snap.snapshot_data


def _snapshot_raw_block(snapshot_data: dict[str, Any]) -> dict[str, Any]:
    raw = snapshot_data.get("raw")
    if isinstance(raw, dict):
        return raw
    payload = snapshot_data.get("payload")
    if isinstance(payload, dict):
        return payload
    return snapshot_data


def _contacts_from_snapshot(company: Company, *, limit_contacts: int = 200) -> list[dict[str, Any]]:
    snapshot_data = _latest_manago_snapshot_data(company)
    if not snapshot_data:
        return []
    contacts = snapshot_data.get("contacts")
    if not isinstance(contacts, list) or not contacts:
        contacts = _snapshot_raw_block(snapshot_data).get("contacts")
    if not isinstance(contacts, list):
        return []
    return [c for c in contacts[:limit_contacts] if isinstance(c, dict)]


def _map_workflow_assets(
    workflows: list[dict[str, Any]],
    *,
    capability_path: str,
    source: str,
) -> list[InventoryAsset]:
    assets: list[InventoryAsset] = []
    for row in workflows:
        external = row.get("externalId") or row.get("external_id")
        internal = row.get("id")
        key = str(external or internal or "").strip()
        if not key:
            continue
        name = str(row.get("name") or key).strip() or key
        assets.append(
            InventoryAsset(
                asset_id=f"wf:{_slug(key)}",
                asset_type=ArchitectureAsset.AssetType.WORKFLOW,
                name=name,
                status=_workflow_status(row),
                definition={
                    "external_id": external,
                    "id": internal,
                    "created_on": row.get("createdOn") or row.get("created_on"),
                    "engine": row.get("engine") or row.get("type"),
                    "trigger": row.get("trigger") or row.get("triggerType"),
                    "tags": row.get("tags") or row.get("requiredTags"),
                    "segments": row.get("segments") or row.get("segmentIds"),
                    "properties": row.get("properties") or row.get("propertyKeys"),
                    "conditions": row.get("conditions") or row.get("filters"),
                    "actions": row.get("actions") or row.get("nodes"),
                    "raw_keys": sorted(str(k) for k in row.keys()),
                },
                capability_path=capability_path,
                provenance=_provenance(
                    source=source,
                    locator=f"workflow/{key}",
                    value={"name": name},
                ),
            )
        )
    return assets


def inventory_workflows(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    timeout: float = 30.0,
    company: Company | None = None,
) -> ProbeOutcome:
    """WF-01 — Active workflow inventory via POST api/workflow/list (+ snapshot fallback)."""
    workflows, err = _fetch_workflows(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        timeout=timeout,
    )
    source = "manago.api.workflow.list"
    capability = "RESTV2.WORKFLOW.LIST"
    if err:
        workflows = []
    if (not workflows) and company is not None:
        raw = _snapshot_raw_block(_latest_manago_snapshot_data(company))
        snap_workflows = raw.get("workflows") or []
        if isinstance(snap_workflows, list) and snap_workflows:
            workflows = [w for w in snap_workflows if isinstance(w, dict)]
            source = "manago.connector_snapshot.workflows"
            capability = "SNAPSHOT.WORKFLOW.LIST"
            err = None

    if err and not workflows:
        return ProbeOutcome(
            probe_id="WF-01",
            status="failed",
            evidence={"error": err, "count": 0},
        )

    assets = _map_workflow_assets(
        workflows,
        capability_path=capability,
        source=source,
    )
    return ProbeOutcome(
        probe_id="WF-01",
        status="succeeded",
        evidence={
            "count": len(assets),
            "raw_count": len(workflows),
            "source": source,
        },
        assets=assets,
    )


def inventory_tags(
    *,
    endpoint: str,
    client_id: str,
    api_secret: str,
    owner: str,
    timeout: float = 30.0,
    company: Company | None = None,
) -> ProbeOutcome:
    """TAG-01 — Tag inventory via POST api/contact/tags (segments incomplete)."""
    tags, err = _fetch_contact_tags(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        owner=owner,
        timeout=timeout,
    )
    source = "manago.api.contact.tags"
    if err:
        tags = []
    if (not tags) and company is not None:
        raw = _snapshot_raw_block(_latest_manago_snapshot_data(company))
        snap_tags = raw.get("tags") or []
        if isinstance(snap_tags, list) and snap_tags:
            tags = [t for t in snap_tags if isinstance(t, dict)]
            source = "manago.connector_snapshot.tags"
            err = None

    if err and not tags:
        return ProbeOutcome(
            probe_id="TAG-01",
            status="failed",
            evidence={
                "error": err,
                "tags_count": 0,
                "segments": "incomplete_no_list_api",
            },
        )

    assets: list[InventoryAsset] = []
    for row in tags:
        name = str(row.get("tag") or "").strip()
        if not name:
            continue
        count = int(row.get("numberOfTagged") or 0)
        assets.append(
            InventoryAsset(
                asset_id=f"tag:{_slug(name)}",
                asset_type=ArchitectureAsset.AssetType.TAG,
                name=name,
                status="active",
                definition={"number_of_tagged": count},
                capability_path="RESTV2.CONTACT.TAGS",
                provenance=_provenance(
                    source=source,
                    locator=f"tag/{name}",
                    value={"numberOfTagged": count},
                ),
            )
        )

    return ProbeOutcome(
        probe_id="TAG-01",
        status="partial",
        evidence={
            "tags_count": len(assets),
            "segments": "incomplete_no_list_api",
            "source": source,
            "note": "Tags inventoried; segments deferred until REST/MCP list exists.",
        },
        assets=assets,
    )


def _property_keys_from_snapshot(company: Company, *, limit_contacts: int = 200) -> list[str]:
    contacts = _contacts_from_snapshot(company, limit_contacts=limit_contacts)
    if not contacts:
        return []

    keys: set[str] = set()
    for contact in contacts:
        for bag_key in (
            "properties",
            "contactProperties",
            "dictionaryProperties",
            "contactDetails",
            "details",
        ):
            props = contact.get(bag_key)
            if isinstance(props, dict):
                for key in props.keys():
                    if isinstance(key, str) and key.strip():
                        keys.add(key.strip())
            elif isinstance(props, list):
                for item in props:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("key") or item.get("property")
                        if isinstance(name, str) and name.strip():
                            keys.add(name.strip())
    return sorted(keys)


def inventory_properties(*, company: Company) -> ProbeOutcome:
    """
    PROP-01 — Property inventory.

    No confirmed Manago contact-schema list API in repo; best-effort union of
    property keys from the latest connector snapshot contacts. Incomplete when
    no snapshot/sample exists (PRD §7.4).
    """
    keys = _property_keys_from_snapshot(company)
    if not keys:
        return ProbeOutcome(
            probe_id="PROP-01",
            status="incomplete",
            evidence={
                "count": 0,
                "source": "connector_snapshot_contacts",
                "note": "No contact property catalog endpoint; snapshot empty or missing.",
            },
        )

    assets = [
        InventoryAsset(
            asset_id=f"prop:{_slug(key)}",
            asset_type=ArchitectureAsset.AssetType.PROPERTY,
            name=key,
            status="observed",
            definition={"key": key, "source": "contact_sample_union"},
            capability_path="MANUAL_CONFIG.CONTACT_PROPERTY_INFER",
            provenance=_provenance(
                source="manago.connector_snapshot.contacts",
                locator=f"property/{key}",
                value={"inferred": True},
            ),
        )
        for key in keys
    ]
    return ProbeOutcome(
        probe_id="PROP-01",
        status="partial",
        evidence={
            "count": len(assets),
            "source": "connector_snapshot_contacts",
            "note": "Inferred from latest import snapshot; not a formal schema catalog.",
        },
        assets=assets,
    )


def run_phase_b_inventory(*, company: Company, timeout: float = 30.0) -> InventoryResult:
    """Run WF-01 / TAG-01 / PROP-01 and return normalized assets + probe outcomes."""
    from dataruns.connectors.manago_ai.client import _resolve_credentials

    connector = _load_manago_connector(company)
    raw_config = connector.config if isinstance(connector.config, dict) else {}
    config = decrypt_connector_config(raw_config)
    endpoint, client_id, api_secret = _resolve_credentials(config)

    owner = _resolve_owner(
        endpoint=endpoint,
        client_id=client_id,
        api_secret=api_secret,
        timeout=timeout,
        config=config,
    )

    probes = [
        inventory_workflows(
            endpoint=endpoint,
            client_id=client_id,
            api_secret=api_secret,
            timeout=timeout,
            company=company,
        ),
        inventory_tags(
            endpoint=endpoint,
            client_id=client_id,
            api_secret=api_secret,
            owner=owner,
            timeout=timeout,
            company=company,
        ),
        inventory_properties(company=company),
    ]

    # Deduplicate by asset_id (last write wins).
    by_id: dict[str, InventoryAsset] = {}
    for probe in probes:
        for asset in probe.assets:
            by_id[asset.asset_id] = asset

    # Coverage: 3 Phase-B probes; succeeded=1.0, partial=0.6, incomplete=0.2, failed=0.
    weights = {
        "succeeded": 1.0,
        "partial": 0.6,
        "incomplete": 0.2,
        "failed": 0.0,
    }
    coverage = sum(weights.get(p.status, 0.0) for p in probes) / max(len(probes), 1)

    return InventoryResult(
        assets=list(by_id.values()),
        probes=probes,
        evidence_coverage=round(coverage, 4),
    )
