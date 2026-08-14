"""Phase C dependency graph — WF-04, WF-09, TAG-04, PROP-04 (PRD-AF-01 §7.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from dataruns.architecture.inventory import InventoryAsset, ProbeOutcome
from dataruns.architecture.models import ArchitectureAsset

# Pack sheet 05 edge types used in MVP1 graph assembly.
EDGE_USES = "USES"
EDGE_READS = "READS"
EDGE_WRITES = "WRITES"
EDGE_SENDS = "SENDS"

RULE_DEP_01 = "DEP-01"  # Workflow → Segment USES
RULE_DEP_02 = "DEP-02"  # Workflow → Tag/Property READS
RULE_DEP_03 = "DEP-03"  # Workflow → Channel SENDS

_TAG_HINT_KEYS = frozenset(
    {
        "tag",
        "tags",
        "tagname",
        "tagnames",
        "requiredtags",
        "requiredtag",
        "addtag",
        "removetag",
        "writetag",
        "contacttag",
    }
)
_SEGMENT_HINT_KEYS = frozenset(
    {
        "segment",
        "segments",
        "segmentid",
        "segmentids",
        "segmentname",
        "audience",
        "audiences",
    }
)
_PROP_HINT_KEYS = frozenset(
    {
        "property",
        "properties",
        "propertykey",
        "propertykeys",
        "field",
        "fields",
        "detail",
        "details",
        "attribute",
        "attributes",
        "keyinformation",
    }
)
_WRITE_HINT_KEYS = frozenset(
    {
        "addtag",
        "removetag",
        "writetag",
        "settag",
        "assigntag",
        "action",
        "actions",
    }
)
_CHANNEL_HINT_KEYS = frozenset(
    {
        "channel",
        "channels",
        "email",
        "sms",
        "push",
        "whatsapp",
        "viber",
    }
)

_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{1,120}")


@dataclass(frozen=True)
class GraphEdge:
    source_asset_id: str
    target_asset_id: str
    edge_type: str
    rule_id: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphResult:
    edges: list[GraphEdge]
    probes: list[ProbeOutcome]
    graph_complete: bool
    evidence_coverage: float


def _norm_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        out: list[str] = []
        for k in ("name", "tag", "value", "id", "key", "externalId", "external_id"):
            if k in value and value[k] is not None:
                out.extend(_as_str_list(value[k]))
        return out
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_as_str_list(item))
        return out
    return []


def _walk_refs(node: Any, *, path: str = "") -> list[tuple[str, str, list[str]]]:
    """
    Yield (hint_family, locator, values) from nested workflow definition payloads.

    hint_family: tag | segment | property | channel | write_tag | other
    """
    found: list[tuple[str, str, list[str]]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            nk = _norm_key(key)
            locator = f"{path}.{key}" if path else str(key)
            if nk in _TAG_HINT_KEYS:
                family = "write_tag" if nk in _WRITE_HINT_KEYS else "tag"
                found.append((family, locator, _as_str_list(value)))
            elif nk in _SEGMENT_HINT_KEYS:
                found.append(("segment", locator, _as_str_list(value)))
            elif nk in _PROP_HINT_KEYS:
                found.append(("property", locator, _as_str_list(value)))
            elif nk in _CHANNEL_HINT_KEYS:
                found.append(("channel", locator, _as_str_list(value)))
            elif nk in {"trigger", "triggertype", "event", "condition", "conditions", "filter", "filters"}:
                # Treat nested condition trees as potential refs; also keep raw trigger strings.
                found.append(("trigger", locator, _as_str_list(value)))
                found.extend(_walk_refs(value, path=locator))
                continue
            found.extend(_walk_refs(value, path=locator))
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            found.extend(_walk_refs(item, path=f"{path}[{idx}]"))
    return found


def _index_assets(
    assets: Iterable[InventoryAsset],
) -> tuple[
    dict[str, InventoryAsset],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    by_id = {a.asset_id: a for a in assets}
    tags_by_name: dict[str, str] = {}
    props_by_name: dict[str, str] = {}
    segments_by_name: dict[str, str] = {}
    for asset in assets:
        name_key = asset.name.strip().lower()
        if not name_key:
            continue
        if asset.asset_type == ArchitectureAsset.AssetType.TAG:
            tags_by_name[name_key] = asset.asset_id
        elif asset.asset_type == ArchitectureAsset.AssetType.PROPERTY:
            props_by_name[name_key] = asset.asset_id
        elif asset.asset_type == ArchitectureAsset.AssetType.SEGMENT:
            segments_by_name[name_key] = asset.asset_id
    return by_id, tags_by_name, props_by_name, segments_by_name


def _match_name(name: str, lookup: dict[str, str]) -> str | None:
    key = name.strip().lower()
    if not key:
        return None
    if key in lookup:
        return lookup[key]
    # Loose: strip common prefixes
    for prefix in ("tag:", "prop:", "segment:", "seg:"):
        if key.startswith(prefix):
            bare = key[len(prefix) :]
            if bare in lookup:
                return lookup[bare]
    return None


def _scan_text_for_known(
    text: str,
    *,
    tags_by_name: dict[str, str],
    props_by_name: dict[str, str],
    segments_by_name: dict[str, str],
) -> list[tuple[str, str, str]]:
    """Return (target_asset_id, edge_type, rule_id) from free-text trigger/condition strings."""
    hits: list[tuple[str, str, str]] = []
    tokens = {m.group(0).lower() for m in _WORD_RE.finditer(text)}
    # Prefer longer names first to avoid partial collisions.
    for name, asset_id in sorted(tags_by_name.items(), key=lambda kv: -len(kv[0])):
        if name in tokens or name in text.lower():
            hits.append((asset_id, EDGE_READS, RULE_DEP_02))
    for name, asset_id in sorted(props_by_name.items(), key=lambda kv: -len(kv[0])):
        if name in tokens or name in text.lower():
            hits.append((asset_id, EDGE_READS, RULE_DEP_02))
    for name, asset_id in sorted(segments_by_name.items(), key=lambda kv: -len(kv[0])):
        if name in tokens or name in text.lower():
            hits.append((asset_id, EDGE_USES, RULE_DEP_01))
    return hits


def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[GraphEdge] = []
    for edge in edges:
        key = (
            edge.source_asset_id,
            edge.target_asset_id,
            edge.edge_type,
            edge.rule_id,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def build_workflow_edges(
    workflows: list[InventoryAsset],
    *,
    tags_by_name: dict[str, str],
    props_by_name: dict[str, str],
    segments_by_name: dict[str, str],
) -> tuple[list[GraphEdge], dict[str, Any]]:
    """
    WF-04 / WF-09 core: extract trigger → primitive and condition/action edges
    from inventoried workflow definitions (REST list + any nested payload).
    """
    edges: list[GraphEdge] = []
    workflows_with_trigger = 0
    workflows_with_any_ref = 0
    shallow_definitions = 0

    for wf in workflows:
        definition = wf.definition if isinstance(wf.definition, dict) else {}
        raw_keys = definition.get("raw_keys") or []
        # "Shallow" = list metadata only (no nested condition/action payload).
        rich_markers = {
            "conditions",
            "condition",
            "actions",
            "action",
            "nodes",
            "steps",
            "graph",
            "definition",
            "tags",
            "segments",
            "properties",
        }
        has_rich = bool(rich_markers.intersection(str(k).lower() for k in raw_keys)) or any(
            k in definition for k in rich_markers
        )
        if not has_rich and not definition.get("trigger"):
            shallow_definitions += 1

        trigger = definition.get("trigger")
        if trigger not in (None, "", []):
            workflows_with_trigger += 1
            for text in _as_str_list(trigger):
                for target_id, edge_type, rule_id in _scan_text_for_known(
                    text,
                    tags_by_name=tags_by_name,
                    props_by_name=props_by_name,
                    segments_by_name=segments_by_name,
                ):
                    edges.append(
                        GraphEdge(
                            source_asset_id=wf.asset_id,
                            target_asset_id=target_id,
                            edge_type=edge_type,
                            rule_id=rule_id,
                            evidence={
                                "probe": "WF-04",
                                "locator": "definition.trigger",
                                "trigger": text,
                            },
                        )
                    )

        refs = _walk_refs(definition)
        saw_ref = False
        for family, locator, values in refs:
            for value in values:
                if family == "tag":
                    target = _match_name(value, tags_by_name)
                    if target:
                        saw_ref = True
                        edges.append(
                            GraphEdge(
                                source_asset_id=wf.asset_id,
                                target_asset_id=target,
                                edge_type=EDGE_READS,
                                rule_id=RULE_DEP_02,
                                evidence={"probe": "WF-09", "locator": locator, "value": value},
                            )
                        )
                elif family == "write_tag":
                    target = _match_name(value, tags_by_name)
                    if target:
                        saw_ref = True
                        edges.append(
                            GraphEdge(
                                source_asset_id=wf.asset_id,
                                target_asset_id=target,
                                edge_type=EDGE_WRITES,
                                rule_id=RULE_DEP_02,
                                evidence={"probe": "WF-09", "locator": locator, "value": value},
                            )
                        )
                elif family == "segment":
                    target = _match_name(value, segments_by_name)
                    if target:
                        saw_ref = True
                        edges.append(
                            GraphEdge(
                                source_asset_id=wf.asset_id,
                                target_asset_id=target,
                                edge_type=EDGE_USES,
                                rule_id=RULE_DEP_01,
                                evidence={"probe": "WF-09", "locator": locator, "value": value},
                            )
                        )
                elif family == "property":
                    target = _match_name(value, props_by_name)
                    if target:
                        saw_ref = True
                        edges.append(
                            GraphEdge(
                                source_asset_id=wf.asset_id,
                                target_asset_id=target,
                                edge_type=EDGE_READS,
                                rule_id=RULE_DEP_02,
                                evidence={"probe": "WF-09", "locator": locator, "value": value},
                            )
                        )
                elif family == "channel":
                    # Channel assets are not inventoried in Phase B; record SENDS only when
                    # a CHANNEL asset already exists (future CHAN probes).
                    continue
                elif family == "trigger":
                    for target_id, edge_type, rule_id in _scan_text_for_known(
                        value,
                        tags_by_name=tags_by_name,
                        props_by_name=props_by_name,
                        segments_by_name=segments_by_name,
                    ):
                        saw_ref = True
                        edges.append(
                            GraphEdge(
                                source_asset_id=wf.asset_id,
                                target_asset_id=target_id,
                                edge_type=edge_type,
                                rule_id=rule_id,
                                evidence={
                                    "probe": "WF-04",
                                    "locator": locator,
                                    "value": value,
                                },
                            )
                        )
        if saw_ref:
            workflows_with_any_ref += 1

    edges = _dedupe_edges(edges)
    stats = {
        "workflow_count": len(workflows),
        "workflows_with_trigger": workflows_with_trigger,
        "workflows_with_resolved_refs": workflows_with_any_ref,
        "shallow_definitions": shallow_definitions,
        "edge_count": len(edges),
        "segments_inventoried": len(segments_by_name),
    }
    return edges, stats


def _where_used_probe(
    *,
    probe_id: str,
    asset_type: str,
    assets: list[InventoryAsset],
    edges: list[GraphEdge],
    segments_incomplete: bool,
) -> ProbeOutcome:
    """TAG-04 / PROP-04 — invert workflow edges into where-used evidence."""
    targets = {a.asset_id for a in assets if a.asset_type == asset_type}
    where_used: dict[str, list[str]] = {aid: [] for aid in targets}
    for edge in edges:
        if edge.target_asset_id not in where_used:
            continue
        if edge.source_asset_id not in where_used[edge.target_asset_id]:
            where_used[edge.target_asset_id].append(edge.source_asset_id)

    referenced = sum(1 for refs in where_used.values() if refs)
    evidence = {
        "asset_count": len(targets),
        "referenced_count": referenced,
        "orphan_count": len(targets) - referenced,
        "where_used_sample": {
            aid: refs[:20] for aid, refs in list(where_used.items())[:50]
        },
    }
    if not targets:
        return ProbeOutcome(
            probe_id=probe_id,
            status="incomplete",
            evidence={**evidence, "note": f"No {asset_type} assets inventoried."},
        )
    if segments_incomplete and probe_id == "TAG-04":
        evidence["segments"] = "incomplete_no_list_api"
        evidence["note"] = (
            "Tag where-used from workflow defs; segment where-used deferred "
            "(no segment list/where-used REST)."
        )
        return ProbeOutcome(probe_id=probe_id, status="partial", evidence=evidence)

    return ProbeOutcome(
        probe_id=probe_id,
        status="succeeded",
        evidence=evidence,
    )


def run_phase_c_graph(*, assets: list[InventoryAsset]) -> GraphResult:
    """
    Build dependency edges from Phase B inventory definitions.

    Without MCP workflow_read / segment where-used, graph is often partial —
    ``graph_complete`` stays False so BL-009 cannot emit Retire/Consolidate.
    """
    _by_id, tags_by_name, props_by_name, segments_by_name = _index_assets(assets)
    workflows = [a for a in assets if a.asset_type == ArchitectureAsset.AssetType.WORKFLOW]
    segments_incomplete = len(segments_by_name) == 0

    edges, stats = build_workflow_edges(
        workflows,
        tags_by_name=tags_by_name,
        props_by_name=props_by_name,
        segments_by_name=segments_by_name,
    )

    # WF-04 — trigger → primitive mapping quality
    if not workflows:
        wf04 = ProbeOutcome(
            probe_id="WF-04",
            status="incomplete",
            evidence={"error": "no_workflows", **stats},
        )
    elif stats["workflows_with_trigger"] == 0 and stats["edge_count"] == 0:
        wf04 = ProbeOutcome(
            probe_id="WF-04",
            status="incomplete",
            evidence={
                **stats,
                "note": (
                    "Workflow list lacks trigger/condition detail; "
                    "MCP workflow_read preferred (sheet 04 Q8)."
                ),
            },
        )
    elif stats["shallow_definitions"] > 0 or stats["workflows_with_trigger"] < len(workflows):
        wf04 = ProbeOutcome(
            probe_id="WF-04",
            status="partial",
            evidence={
                **stats,
                "note": "Some workflows missing trigger/condition payload on REST list.",
            },
        )
    else:
        wf04 = ProbeOutcome(probe_id="WF-04", status="succeeded", evidence=stats)

    # WF-09 — full graph gate
    if segments_incomplete or stats["shallow_definitions"] > 0 or wf04.status != "succeeded":
        wf09_status = "partial" if edges or workflows else "incomplete"
        wf09 = ProbeOutcome(
            probe_id="WF-09",
            status=wf09_status,
            evidence={
                **stats,
                "segments": "incomplete_no_list_api" if segments_incomplete else "ok",
                "note": (
                    "Full anti-break graph requires segment where-used + rich workflow defs; "
                    "Retire/Consolidate remain blocked (sheet 01/08)."
                ),
            },
        )
        graph_complete = False
    else:
        wf09 = ProbeOutcome(
            probe_id="WF-09",
            status="succeeded",
            evidence={**stats, "segments": "ok"},
        )
        graph_complete = True

    tag04 = _where_used_probe(
        probe_id="TAG-04",
        asset_type=ArchitectureAsset.AssetType.TAG,
        assets=assets,
        edges=edges,
        segments_incomplete=segments_incomplete,
    )
    prop04 = _where_used_probe(
        probe_id="PROP-04",
        asset_type=ArchitectureAsset.AssetType.PROPERTY,
        assets=assets,
        edges=edges,
        segments_incomplete=False,
    )

    probes = [wf04, wf09, tag04, prop04]
    weights = {
        "succeeded": 1.0,
        "partial": 0.6,
        "incomplete": 0.2,
        "failed": 0.0,
    }
    coverage = sum(weights.get(p.status, 0.0) for p in probes) / max(len(probes), 1)

    return GraphResult(
        edges=edges,
        probes=probes,
        graph_complete=graph_complete,
        evidence_coverage=round(coverage, 4),
    )
