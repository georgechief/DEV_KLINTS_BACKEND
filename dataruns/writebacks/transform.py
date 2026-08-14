"""Evidence rows → WriteIntent list (PRD-WB-01 §3–4)."""

from __future__ import annotations

from typing import Any

from dataruns.connectors.mapping import UnmappedFieldError, reverse_map_record
from dataruns.dcs.worklist import WorklistDetailNotFound, build_worklist_detail
from dataruns.writebacks.guards import apply_guards
from dataruns.writebacks.snapshot import (
    contact_detail_value,
    contact_has_tag,
    find_manago_contact,
)
from dataruns.writebacks.types import WriteIntent
from tenants.models import Company


def collect_evidence_rows(
    *,
    company: Company,
    check_id: str,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    try:
        detail = build_worklist_detail(company=company, check_id=check_id)
    except WorklistDetailNotFound:
        return []

    rows: list[dict[str, Any]] = []
    for key in ("mismatches", "evidence", "matches"):
        candidates = detail.get(key)
        if isinstance(candidates, list) and candidates:
            for item in candidates:
                if isinstance(item, dict):
                    rows.append(item)
            break

    if max_rows is not None and max_rows >= 0:
        return rows[:max_rows]
    return rows


def build_intents_from_mapping(
    *,
    company: Company,
    mapping: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> list[WriteIntent]:
    check_id = str(mapping.get("check_id") or "")
    template_id = mapping.get("template_id")
    rollback_block = mapping.get("rollback")
    rollback_strategy = (
        str(rollback_block.get("strategy"))
        if isinstance(rollback_block, dict) and rollback_block.get("strategy")
        else None
    )
    intents: list[WriteIntent] = []

    for operation in mapping.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        for index, row in enumerate(evidence_rows):
            intent = _intent_from_operation(
                company=company,
                check_id=check_id,
                template_id=template_id,
                operation=operation,
                row=row,
                row_index=index,
                rollback_strategy=rollback_strategy,
            )
            if intent is not None:
                intents.append(intent)
    return intents


def _intent_from_operation(
    *,
    company: Company,
    check_id: str,
    template_id: Any,
    operation: dict[str, Any],
    row: dict[str, Any],
    row_index: int,
    rollback_strategy: str | None = None,
) -> WriteIntent | None:
    from_evidence = operation.get("from_evidence")
    if not isinstance(from_evidence, dict):
        return None

    context = _evidence_context(row)
    if not _match_evidence(from_evidence.get("match"), context):
        return None

    fields = _resolve_fields(from_evidence.get("fields"), context)
    entity_key = _resolve_path_value(from_evidence.get("entity_key"), context)
    entity_key = "" if entity_key is None else str(entity_key)

    op_kind = str(operation.get("op_kind") or "")
    target = str(operation.get("target") or "manago")
    namespace = str(operation.get("namespace") or "")
    operation_id = str(operation.get("operation_id") or f"{target}.{op_kind}")
    entity_type = str(operation.get("entity_type") or "contact")
    capability_id = operation.get("capability_id")
    guards = [str(g) for g in (operation.get("guards") or []) if g]

    guard_reason = apply_guards(
        guards=guards,
        entity_key=entity_key,
        namespace=namespace,
        fields=fields,
    )
    if guard_reason:
        return WriteIntent(
            check_id=check_id,
            op_kind=op_kind,
            operation=operation_id,
            target_system=target,
            entity_type=entity_type,
            entity_key=entity_key,
            namespace=namespace,
            template_id=str(template_id) if template_id else None,
            source_evidence_ref=str(row.get("locator") or row_index),
            status="error",
            error_reason=guard_reason,
            capability_id=str(capability_id) if capability_id else None,
        )

    try:
        payload, before, after, rollback = _build_payload_and_state(
            company=company,
            op_kind=op_kind,
            target=target,
            fields=fields,
            entity_key=entity_key,
            context=context,
            mark_klints_backfill=bool(operation.get("mark_klints_backfill")),
            extras=operation.get("extras") if isinstance(operation.get("extras"), dict) else None,
        )
    except UnmappedFieldError as exc:
        return WriteIntent(
            check_id=check_id,
            op_kind=op_kind,
            operation=operation_id,
            target_system=target,
            entity_type=entity_type,
            entity_key=entity_key,
            namespace=namespace,
            template_id=str(template_id) if template_id else None,
            source_evidence_ref=str(row.get("locator") or row_index),
            status="error",
            error_reason=str(exc),
            capability_id=str(capability_id) if capability_id else None,
        )

    if operation.get("mark_klints_backfill") and not payload.get("_mark_klints_backfill"):
        payload["_mark_klints_backfill"] = True

    return WriteIntent(
        check_id=check_id,
        op_kind=op_kind,
        operation=operation_id,
        target_system=target,
        entity_type=entity_type,
        entity_key=entity_key,
        namespace=namespace,
        template_id=str(template_id) if template_id else None,
        payload=payload,
        before=before,
        after=after,
        rollback_snapshot=rollback,
        source_evidence_ref=str(row.get("locator") or row_index),
        status="ready",
        capability_id=str(capability_id) if capability_id else None,
        rollback_strategy=rollback_strategy,
    )


def _evidence_context(row: dict[str, Any]) -> dict[str, Any]:
    context = dict(row)
    value = row.get("value")
    if isinstance(value, dict):
        for key, item in value.items():
            context.setdefault(key, item)
    context["value"] = value
    return context


def _match_evidence(rule: Any, context: dict[str, Any]) -> bool:
    if rule is None:
        return True
    if not isinstance(rule, dict):
        return True
    if "const" in rule:
        actual = _resolve_path_value(rule, context)
        return actual == rule.get("const")
    path = rule.get("path")
    if isinstance(path, str):
        return _resolve_path_value({"path": path}, context) is not None
    return True


def _resolve_fields(spec: Any, context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        return {}
    resolved: dict[str, Any] = {}
    for key, rule in spec.items():
        resolved[key] = _resolve_path_value(rule, context)
    return resolved


def _resolve_path_value(rule: Any, context: dict[str, Any]) -> Any:
    if not isinstance(rule, dict):
        return rule
    if "const" in rule:
        return rule.get("const")
    path = rule.get("path")
    if not isinstance(path, str):
        return None
    return _get_path(context, path)


def _get_path(context: dict[str, Any], path: str) -> Any:
    if path in context:
        return context[path]
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _build_payload_and_state(
    *,
    company: Company,
    op_kind: str,
    target: str,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
    mark_klints_backfill: bool = False,
    extras: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if op_kind == "contact_upsert" and target == "manago":
        return _contact_upsert_payload(
            company=company,
            fields=fields,
            entity_key=entity_key,
            mark_klints_backfill=mark_klints_backfill,
            extras=extras,
        )
    if op_kind == "detail_set" and target == "manago":
        return _detail_set_payload(company=company, fields=fields, entity_key=entity_key)
    if op_kind == "tag_add" and target == "manago":
        return _tag_add_payload(company=company, fields=fields, entity_key=entity_key)
    if op_kind == "event_ingest" and target == "manago":
        payload, before, after, rollback = _event_ingest_payload(
            fields=fields,
            entity_key=entity_key,
            context=context,
        )
        if extras:
            payload.update(extras)
            after = {**after, **extras}
        return payload, before, after, rollback
    raise ValueError(f"unsupported_op_kind:{op_kind}")


def _contact_upsert_payload(
    *,
    company: Company,
    fields: dict[str, Any],
    entity_key: str,
    mark_klints_backfill: bool = False,
    extras: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    email = str(fields.get("email") or entity_key or "").strip()
    db_record = {
        "email": email,
    }
    link_key = fields.get("link_key")
    if link_key:
        db_record["link_key"] = str(link_key)
    payload = reverse_map_record(
        db_record,
        platform="manago_ai",
        entity="contact",
        extras=extras,
    )
    if mark_klints_backfill:
        props = payload.get("properties")
        if not isinstance(props, dict):
            props = {}
            payload["properties"] = props
        props.setdefault("klints_backfill", "true")
        payload["_mark_klints_backfill"] = True
    contact = find_manago_contact(company, email=email)
    before = {"email": email, "present_in_manago": contact is not None}
    after = dict(payload)
    rollback = {"email": email, "existed": contact is not None}
    return payload, before, after, rollback


def _detail_set_payload(
    *,
    company: Company,
    fields: dict[str, Any],
    entity_key: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    detail_key = str(fields.get("detail_key") or "")
    detail_value = fields.get("detail_value")
    contact_id = str(fields.get("contact_id") or "").strip()
    email = entity_key if "@" in entity_key else ""
    contact = find_manago_contact(company, email=email or None, contact_id=contact_id or None)
    before_value = contact_detail_value(contact, detail_key) if contact else None
    payload = {
        "email": email or (contact or {}).get("email"),
        "contactId": contact_id or (contact or {}).get("contactId") or (contact or {}).get("id"),
        "properties": {detail_key: detail_value},
    }
    before = {detail_key: before_value}
    after = {detail_key: detail_value}
    rollback = {detail_key: before_value}
    return payload, before, after, rollback


def _tag_add_payload(
    *,
    company: Company,
    fields: dict[str, Any],
    entity_key: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    tag = str(fields.get("tag") or "")
    email = entity_key if "@" in entity_key else ""
    contact = find_manago_contact(company, email=email or None)
    had_tag = contact_has_tag(contact, tag) if contact else False
    payload = {
        "email": email or None,
        "contactId": (contact or {}).get("contactId") or (contact or {}).get("id"),
        "tag": tag,
        "order_id": fields.get("order_id"),
    }
    before = {"tag": tag, "present": had_tag}
    after = {"tag": tag, "present": True}
    rollback = {"tag": tag, "present": had_tag}
    return payload, before, after, rollback


def _event_ingest_payload(
    *,
    fields: dict[str, Any],
    entity_key: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    order_id = str(fields.get("order_id") or entity_key or "")
    email = fields.get("email") or (entity_key if "@" in str(entity_key) else None)
    contact_id = fields.get("contact_id")
    payload = {
        "externalId": order_id,
        "contactExtEventType": str(fields.get("event_type") or "PURCHASE"),
        "value": fields.get("value") or context.get("representative_value") or context.get("count"),
    }
    if email:
        payload["email"] = str(email)
    if contact_id:
        payload["contactId"] = str(contact_id)
    before = {"externalId": order_id, "event_exists": False}
    after = dict(payload)
    rollback = {"externalId": order_id}
    return payload, before, after, rollback
