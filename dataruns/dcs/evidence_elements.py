"""Enrich DCS evidence rows with element / field metadata (PRD-FE-11 / FE-11B)."""

from __future__ import annotations

import re
from typing import Any

from dataruns.connectors.mapping import load_connector_map, mappings_for_entity

_PLACEHOLDER_LOCATORS = frozenset({"—", "-", "n/a", "na", "none", "null"})

# Check-level defaults when executors emit bare {side, count, …} rows.
# Worklist-only (PRD-FE-11 §0b) — executors / CheckResult unchanged (Sahil).
_CHECK_DEFAULTS: dict[str, dict[str, Any]] = {
    "CI-01": {
        "entity": "contact",
        "element": "contact.identity",
        "element_label": "Contact identity",
    },
    "CI-13": {
        "entity": "contact",
        "element": "contact.state",
        "element_label": "Contact state",
        "default_source": "manago_ai",
    },
    "FD-02": {
        "entity": "config",
        "element": "shopify.scopes",
        "element_label": "Shopify API scopes",
        "default_source": "shopify",
    },
    "LE-01": {
        "entity": "order",
        "element": "lifecycle.purchase_count",
        "element_label": "Purchase count parity",
        "default_source": "snapshot",
    },
    "LE-02": {
        "entity": "order",
        "element": "lifecycle.purchase_value",
        "element_label": "Purchase value parity",
        "default_source": "snapshot",
    },
    "LE-04": {
        "entity": "order",
        "element": "lifecycle.duplicate_purchase",
        "element_label": "Duplicate purchase events",
        "default_source": "snapshot",
    },
    "LE-09": {
        "entity": "order",
        "element": "lifecycle.returns_cancellations",
        "element_label": "Returns and cancellations",
        "default_source": "snapshot",
    },
    "LE-13": {
        "entity": "event",
        "element": "drift.event_volume",
        "element_label": "Event volume drift",
        "default_source": "snapshot",
    },
    "PT-04": {
        "entity": "contact",
        "element": "order.net_vs_gross",
        "element_label": "Net vs gross per contact",
        "default_source": "snapshot",
    },
    "SP-07": {
        "entity": "contact",
        "element": "contact.detail_keys",
        "element_label": "Manago contact detail keys",
        "default_source": "manago_ai",
    },
    "CC-03": {
        "entity": "contact",
        "element": "consent.provenance",
        "element_label": "Consent provenance",
        "default_source": "manago_ai",
    },
    "ME-08": {
        "entity": "order",
        "element": "measurement.baseline",
        "element_label": "Measurement baseline",
        "default_source": "manago_ai",
    },
    "ME-09": {
        "entity": "contact",
        "element": "contact.deliverability",
        "element_label": "Email deliverability",
        "default_source": "manago_ai",
    },
}

_SIDE_LABELS: dict[str, str] = {
    "dead_state": "Contact state (dead/blocked/resigned)",
    "dead_date_cluster": "Contact state spike day",
    "manago_only": "Contact (Manago only)",
    "shopify_only": "Contact (Shopify only)",
    "duplicate_purchase": "Duplicate purchase events",
    "shopify_only_return": "Return/cancel (Shopify only)",
    "manago_only_return": "Return/cancel (Manago only)",
    "net_overstatement": "Net overstatement vs Shopify",
    "driver": "Purchase value driver",
    "missing_external_id": "Missing external order ID",
    "weak_provenance": "Weak consent provenance",
    "shopify_holds_evidence": "Shopify holds consent evidence",
    "manago_only_unevidenced": "Manago-only unevidenced consent",
    "klints_detail_collision": "Manago detail key collision",
    "klints_tag_collision": "Manago tag collision",
    "bounce_or_invalid": "Bounce or invalid email rate",
    "history": "Order history baseline gap",
    "volume": "Volume baseline gap",
    "aov": "AOV baseline gap",
    "stale_decision_field": "Stale decision field",
    "stale_or_stall": "Stale lifecycle domain",
}

_SIDE_SOURCE: dict[str, str] = {
    "manago_only": "manago_ai",
    "shopify_only": "shopify",
    "manago_only_return": "manago_ai",
    "shopify_only_return": "shopify",
    "dead_state": "manago_ai",
    "dead_date_cluster": "manago_ai",
    "bounce_or_invalid": "manago_ai",
    "klints_detail_collision": "manago_ai",
    "klints_tag_collision": "manago_ai",
    "weak_provenance": "manago_ai",
    "shopify_holds_evidence": "shopify",
    "manago_only_unevidenced": "manago_ai",
}

_LOCATOR_LABELS: dict[str, str] = {
    "drift.contact_state_distribution": "Contact state distribution",
    "identity.contact_count_reconciliation": "Contact count reconciliation",
    "lifecycle.duplicate_purchase_events": "Duplicate purchase events",
    "drift.event_volume": "Event volume drift",
    "product_truth.net_vs_gross_per_contact": "Net vs gross per contact",
}


def _humanize_token(text: str) -> str:
    cleaned = re.sub(r"[_\-.]+", " ", text.strip())
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def _is_placeholder_locator(locator: Any) -> bool:
    if not isinstance(locator, str):
        return True
    return locator.strip().lower() in _PLACEHOLDER_LOCATORS


def _value_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _present(container: dict[str, Any], key: str) -> bool:
    if key not in container:
        return False
    val = container.get(key)
    if val is None:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    return True


def _side_from_item(item: dict[str, Any], value: dict[str, Any]) -> str:
    side = item.get("side")
    if isinstance(side, str) and side.strip():
        return side.strip()
    nested = value.get("side")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return ""


def _infer_source(
    *,
    item: dict[str, Any],
    value: dict[str, Any],
    check_id: str,
    current_source: str,
) -> str:
    side = _side_from_item(item, value)
    if side in _SIDE_SOURCE:
        return _SIDE_SOURCE[side]

    check_defaults = _CHECK_DEFAULTS.get(check_id, {})
    default_source = check_defaults.get("default_source")
    if isinstance(default_source, str) and default_source.strip():
        if current_source in {"", "klints", "unknown"}:
            return default_source.strip()

    if current_source not in {"", "klints", "unknown"}:
        return current_source

    if check_id == "CI-13":
        return "manago_ai"
    return current_source


def _db_key_from_item(
    item: dict[str, Any],
    value: dict[str, Any],
    *,
    entity: str = "",
    raw_value: Any = None,
) -> str | None:
    for container in (item, value):
        for key in ("db_key", "field", "canonical_field"):
            raw = container.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()

    def _hint(container: dict[str, Any]) -> str | None:
        if entity == "order":
            if (
                _present(container, "amount")
                or _present(container, "total_price")
                or _present(container, "representative_value")
            ):
                return "amount"
            if _present(container, "transactionId"):
                return "external_id"
            raw = container.get("value")
            if raw is not None and not isinstance(raw, dict) and raw != "":
                return "amount"
        if _present(container, "email") or _present(container, "person.email"):
            return "email"
        if (
            _present(container, "amount")
            or _present(container, "total_price")
            or _present(container, "representative_value")
        ):
            return "amount"
        if _present(container, "transactionId"):
            return "external_id"
        return None

    for container in (item, value):
        hinted = _hint(container)
        if hinted:
            return hinted
    if entity == "order" and isinstance(raw_value, (int, float)):
        return "amount"
    return None


def _entity_from_field_hints(
    item: dict[str, Any],
    value: dict[str, Any],
) -> str | None:
    for container in (item, value):
        if (
            _present(container, "transactionId")
            or _present(container, "total_price")
            or _present(container, "amount")
            or _present(container, "representative_value")
        ):
            return "order"
    for container in (item, value):
        if _present(container, "email") or _present(container, "person.email"):
            return "contact"
    return None


def _entity_from_item(
    item: dict[str, Any],
    value: dict[str, Any],
    *,
    check_id: str,
) -> str | None:
    for container in (item, value):
        raw = container.get("entity")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    hinted = _entity_from_field_hints(item, value)
    if hinted:
        return hinted
    return _CHECK_DEFAULTS.get(check_id, {}).get("entity")


def _api_key_for_db_key(*, platform: str, entity: str, db_key: str) -> str | None:
    if platform not in {"shopify", "manago_ai"}:
        return None
    try:
        connector_map = load_connector_map(platform)
    except ValueError:
        return None
    for row in mappings_for_entity(connector_map, entity):
        if row.get("db_key") == db_key:
            api_key = row.get("api_key")
            if isinstance(api_key, str) and api_key.strip():
                return api_key.strip()
    return None


def _label_from_locator(locator: str) -> str | None:
    if _is_placeholder_locator(locator):
        return None
    if locator in _LOCATOR_LABELS:
        return _LOCATOR_LABELS[locator]
    leaf = locator.rsplit(".", 1)[-1]
    return _humanize_token(leaf) if leaf else None


def _label_from_side(*, side: str, value: dict[str, Any]) -> str | None:
    if not side:
        return None
    if side in _SIDE_LABELS:
        label = _SIDE_LABELS[side]
        bucket = value.get("bucket")
        if side == "dead_state" and isinstance(bucket, str) and bucket.strip():
            return f"{label} ({bucket.strip()})"
        return label
    return _humanize_token(side)


def enrich_evidence_element(
    check_id: str,
    item: dict[str, Any],
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """
    Additive element metadata for worklist evidence rows.

    Never overwrites rich executor-provided element / api_key / db_key fields.
    When entity + mapped api_key are known, ``element`` is ``{entity}.{api_key}``
    (PRD-FE-11B). ``element_label`` stays human copy for “What we found”.
    """
    check_id = (check_id or "").strip()
    out = dict(normalized)

    for key in ("entity", "db_key", "api_key", "element", "element_label"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            out[key] = raw.strip()

    value = _value_dict(out.get("value"))

    if not isinstance(out.get("entity"), str) or not out["entity"].strip():
        entity = _entity_from_item(item, value, check_id=check_id)
        if entity:
            out["entity"] = entity

    source = _infer_source(
        item=item,
        value=value,
        check_id=check_id,
        current_source=str(out.get("source") or ""),
    )
    if source:
        out["source"] = source

    entity = str(out.get("entity") or "")
    if not isinstance(out.get("db_key"), str) or not out["db_key"].strip():
        db_key = _db_key_from_item(
            item, value, entity=entity, raw_value=out.get("value")
        )
        if db_key:
            out["db_key"] = db_key

    db_key = str(out.get("db_key") or "")
    if not entity and db_key == "amount":
        out["entity"] = "order"
        entity = "order"
    elif not entity and db_key == "email":
        out["entity"] = "contact"
        entity = "contact"

    if (
        db_key
        and entity
        and (not isinstance(out.get("api_key"), str) or not out["api_key"].strip())
    ):
        api_key = _api_key_for_db_key(platform=source, entity=entity, db_key=db_key)
        if api_key:
            out["api_key"] = api_key

    executor_element = False
    for raw_element in (item.get("element"), value.get("element")):
        if isinstance(raw_element, str) and raw_element.strip():
            executor_element = True
            break

    check_defaults = _CHECK_DEFAULTS.get(check_id, {})
    api_key = str(out.get("api_key") or "").strip()
    if executor_element:
        if not isinstance(out.get("element"), str) or not out["element"].strip():
            for raw_element in (item.get("element"), value.get("element")):
                if isinstance(raw_element, str) and raw_element.strip():
                    out["element"] = raw_element.strip()
                    break
    elif entity and api_key:
        out["element"] = f"{entity}.{api_key}"
    elif not isinstance(out.get("element"), str) or not out["element"].strip():
        if isinstance(check_defaults.get("element"), str):
            out["element"] = check_defaults["element"]
        elif isinstance(out.get("locator"), str) and out["locator"].strip():
            out["element"] = out["locator"].strip()

    if (
        not isinstance(out.get("element_label"), str)
        or not out["element_label"].strip()
    ):
        element_label = item.get("element_label")
        if isinstance(element_label, str) and element_label.strip():
            out["element_label"] = element_label.strip()
        elif isinstance(value.get("element_label"), str) and value["element_label"].strip():
            out["element_label"] = value["element_label"].strip()
        else:
            side = _side_from_item(item, value)
            side_label = _label_from_side(side=side, value=value)
            if side_label:
                out["element_label"] = side_label
            else:
                locator = str(out.get("locator") or "")
                if locator in _LOCATOR_LABELS:
                    out["element_label"] = _LOCATOR_LABELS[locator]
                elif isinstance(check_defaults.get("element_label"), str):
                    out["element_label"] = check_defaults["element_label"]
                else:
                    locator_label = _label_from_locator(locator)
                    if locator_label:
                        out["element_label"] = locator_label

    locator = out.get("locator")
    if _is_placeholder_locator(locator):
        out["locator"] = ""

    return out
