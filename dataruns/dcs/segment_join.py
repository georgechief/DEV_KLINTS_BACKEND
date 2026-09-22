"""Excel sheet 02/06 segment & detail join for DCS scoring (PRD-DCS-04 batch 4c).

Builds from Manago ConnectorSnapshot raw contacts:
- ``properties`` / ``dictionaryProperties`` (standard details)
- ``contactTags`` (tags)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from dataruns.dcs.lifecycle_join import (
    PinnedSnapshotIds,
    SourceRunIds,
    _connector_raw_for_platform,
)
from tenants.models import Company

SP_SAMPLE = 50
_KLINTS_DETAIL = re.compile(r"^klints_", re.I)
_KLINTS_TAG = re.compile(r"^klints:", re.I)
# Baseline writeback-owned markers (PRD-WB / WB-09). Also union keys/tags declared
# by enabled writeback mappings with namespace klints_ / klints: (see helpers).
_KLINTS_OWNED_DETAIL_KEYS_BASE = frozenset(
    {
        "klints_backfill",
        "klints_consent_evidence",
    }
)
_KLINTS_OWNED_TAGS_BASE = frozenset()


@lru_cache(maxsize=1)
def _owned_keys_from_enabled_mappings() -> tuple[frozenset[str], frozenset[str]]:
    """Pull klints_ / klints: targets from enabled writeback mapping ops."""
    details: set[str] = set()
    tags: set[str] = set()
    try:
        from dataruns.writebacks.registry import get_check_mapping, list_mapping_entries

        for entry in list_mapping_entries():
            if not entry.get("enabled"):
                continue
            check_id = str(entry.get("check_id") or "").strip().upper()
            if not check_id:
                continue
            try:
                spec = get_check_mapping(check_id)
            except Exception:
                continue
            for operation in spec.get("operations") or []:
                if not isinstance(operation, dict):
                    continue
                namespace = str(operation.get("namespace") or "")
                fields = (operation.get("from_evidence") or {}).get("fields") or {}
                if not isinstance(fields, dict):
                    continue
                if namespace == "klints_":
                    detail = fields.get("detail_key")
                    if isinstance(detail, dict) and "const" in detail:
                        text = str(detail.get("const") or "").strip().lower()
                        if text.startswith("klints_"):
                            details.add(text)
                    if operation.get("mark_klints_backfill"):
                        details.add("klints_backfill")
                if namespace == "klints:":
                    tag = fields.get("tag")
                    if isinstance(tag, dict) and "const" in tag:
                        text = str(tag.get("const") or "").strip().lower()
                        if text.startswith("klints:"):
                            tags.add(text)
    except Exception:
        return frozenset(), frozenset()
    return frozenset(details), frozenset(tags)


def clear_klints_owned_keys_cache() -> None:
    _owned_keys_from_enabled_mappings.cache_clear()


def klints_owned_detail_keys() -> frozenset[str]:
    mapped, _tags = _owned_keys_from_enabled_mappings()
    return _KLINTS_OWNED_DETAIL_KEYS_BASE | mapped


def klints_owned_tags() -> frozenset[str]:
    _details, mapped = _owned_keys_from_enabled_mappings()
    return _KLINTS_OWNED_TAGS_BASE | mapped


def is_klints_owned_detail(key: str) -> bool:
    return str(key or "").strip().lower() in klints_owned_detail_keys()


def is_klints_owned_tag(tag: str) -> bool:
    return str(tag or "").strip().lower() in {t.lower() for t in klints_owned_tags()}


def legacy_namespace_rename(name: str) -> str:
    """Excel SP-07 Option A — move collision off namespace under legacy_ prefix."""
    text = str(name or "").strip()
    if not text:
        return text
    if text.lower().startswith("legacy_"):
        return text
    return f"legacy_{text}"


_BOOL_TOKENS = frozenset(
    {"true", "false", "yes", "no", "y", "n", "0", "1", "on", "off"}
)
_DATE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{10,13})$"
)


def _classify_value(value: Any) -> str:
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "numeric"
    text = str(value).strip()
    if not text:
        return "empty"
    low = text.lower()
    if low in _BOOL_TOKENS:
        return "boolean"
    try:
        float(text.replace(",", ""))
        return "numeric"
    except ValueError:
        pass
    if _DATE_RE.match(text):
        return "date_like"
    return "text"


def _iter_detail_pairs(contact: dict[str, Any]) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for bag_name in ("properties", "dictionaryProperties", "details", "customFields"):
        bag = contact.get(bag_name)
        if isinstance(bag, dict):
            for k, v in bag.items():
                pairs.append((str(k), v))
        elif isinstance(bag, list):
            for item in bag:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("key") or item.get("property")
                if name is None:
                    continue
                pairs.append((str(name), item.get("value")))
    return pairs


def _iter_tags(contact: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    raw = contact.get("contactTags") or contact.get("tags") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return tags
    for item in raw:
        if isinstance(item, str):
            tags.append(item)
        elif isinstance(item, dict):
            name = item.get("tag") or item.get("name") or item.get("label")
            if name is not None:
                tags.append(str(name))
    return tags


def build_segment_snapshot(
    *,
    company: Company,
    source_run_ids: SourceRunIds = None,
    pinned_snapshot_ids: PinnedSnapshotIds = None,
) -> dict[str, Any]:
    ids = source_run_ids or {}
    snaps = pinned_snapshot_ids or {}
    manago_raw = _connector_raw_for_platform(
        company=company,
        platform="manago_ai",
        source_run_id=ids.get("manago_ai"),
        snapshot_id=snaps.get("manago_ai"),
    )
    shopify_raw = _connector_raw_for_platform(
        company=company,
        platform="shopify",
        source_run_id=ids.get("shopify"),
        snapshot_id=snaps.get("shopify"),
    )
    contacts = [c for c in (manago_raw.get("contacts") or []) if isinstance(c, dict)]
    metafields = [
        m
        for m in (shopify_raw.get("customer_metafields") or [])
        if isinstance(m, dict)
    ]

    key_formats: dict[str, Counter] = defaultdict(Counter)
    key_samples: dict[str, list[Any]] = defaultdict(list)
    all_keys: set[str] = set()
    all_tags: set[str] = set()
    contacts_with_details = 0
    contacts_with_tags = 0

    for contact in contacts:
        pairs = _iter_detail_pairs(contact)
        tags = _iter_tags(contact)
        if pairs:
            contacts_with_details += 1
        if tags:
            contacts_with_tags += 1
        for key, value in pairs:
            all_keys.add(key)
            fmt = _classify_value(value)
            key_formats[key][fmt] += 1
            if len(key_samples[key]) < 5:
                key_samples[key].append(value)
        for tag in tags:
            all_tags.add(tag)

    inconsistent: list[dict[str, Any]] = []
    for key, formats in key_formats.items():
        # Ignore empty alongside a single real type.
        non_empty = {k: v for k, v in formats.items() if k != "empty"}
        if len(non_empty) > 1:
            inconsistent.append(
                {
                    "key": key,
                    "format_distribution": dict(formats),
                    "samples": key_samples.get(key) or [],
                }
            )

    # Excel SP-03: keys duplicating each other semantically.
    semantic_groups: dict[str, list[str]] = defaultdict(list)
    for key in all_keys:
        semantic_groups[_semantic_key(key)].append(key)
    semantic_dupes = [
        {"normalized": norm, "keys": sorted(keys)}
        for norm, keys in sorted(semantic_groups.items())
        if len(keys) > 1 and norm
    ]

    klints_detail_collisions = sorted(
        k
        for k in all_keys
        if _KLINTS_DETAIL.match(k) and not is_klints_owned_detail(k)
    )
    klints_tag_collisions = sorted(
        t for t in all_tags if _KLINTS_TAG.match(t) and not is_klints_owned_tag(t)
    )

    # Excel SP-03: Shopify customer metafields as source comparison.
    metafield_keys = sorted(
        {
            f"{m.get('namespace')}.{m.get('key')}"
            for m in metafields
            if m.get("namespace") is not None and m.get("key") is not None
        }
    )
    manago_key_set = {k.lower() for k in all_keys}
    metafield_overlap = [
        mk
        for mk in metafield_keys
        if mk.lower() in manago_key_set or mk.split(".")[-1].lower() in manago_key_set
    ]

    details_payload = [
        {
            "key": key,
            "format_distribution": dict(formats),
            "value_count": sum(formats.values()),
        }
        for key, formats in sorted(key_formats.items())
    ]

    return {
        "details": details_payload[:500],
        "segments": [{"tag": t} for t in sorted(all_tags)[:500]],
        "segment": {
            "contacts_scanned": len(contacts),
            "contacts_with_details": contacts_with_details,
            "contacts_with_tags": contacts_with_tags,
            "detail_key_count": len(all_keys),
            "tag_count": len(all_tags),
            "inconsistent_keys": len(inconsistent),
            "inconsistent_sample": inconsistent[:SP_SAMPLE],
            "semantic_duplicate_groups": len(semantic_dupes),
            "semantic_duplicate_sample": semantic_dupes[:SP_SAMPLE],
            "shopify_metafield_keys": metafield_keys[:SP_SAMPLE],
            "shopify_metafield_overlap": metafield_overlap[:SP_SAMPLE],
            "klints_detail_collisions": klints_detail_collisions[:SP_SAMPLE],
            "klints_tag_collisions": klints_tag_collisions[:SP_SAMPLE],
            "klints_collision_count": (
                len(klints_detail_collisions) + len(klints_tag_collisions)
            ),
            "raw_enrichment": {
                "manago_contacts_from_raw": bool(contacts),
                "details_present": contacts_with_details > 0,
                "tags_present": contacts_with_tags > 0,
                "shopify_metafields_present": bool(metafields),
            },
        },
    }


def _semantic_key(key: str) -> str:
    """Normalize detail keys so ORDER_AVG / orderAvg / order-average collide."""
    text = str(key or "").strip().lower()
    text = text.replace("average", "avg").replace("number", "num")
    text = text.replace("summary", "sum")
    return re.sub(r"[^a-z0-9]+", "", text)

