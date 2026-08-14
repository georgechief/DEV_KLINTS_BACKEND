"""Sheet 02/03 catalogue helpers for foundation gate messaging.

Prefer DB RootCauseMaster / CheckMaster; fall back to JSON fixtures when
masters are not seeded (unit tests / empty env).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.db.models import Max

_DIR = Path(__file__).resolve().parent


def _rc_cache_token() -> str:
    from dataruns.models import RootCauseMaster

    updated = RootCauseMaster.objects.aggregate(m=Max("updated_at")).get("m")
    count = RootCauseMaster.objects.count()
    return f"{count}:{updated}"


def _check_cache_token() -> str:
    from dataruns.models import CheckMaster as CheckMasterRow

    updated = CheckMasterRow.objects.aggregate(m=Max("updated_at")).get("m")
    count = CheckMasterRow.objects.filter(is_active=True).count()
    return f"{count}:{updated}"


@lru_cache(maxsize=1)
def _load_root_cause_catalogue_json() -> dict[str, dict[str, Any]]:
    return json.loads((_DIR / "root_causes.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_foundation_gate_catalogue_json() -> dict[str, dict[str, Any]]:
    return json.loads((_DIR / "foundation_gates.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _load_root_cause_catalogue_db(cache_token: str) -> dict[str, dict[str, Any]]:
    del cache_token
    from dataruns.models import RootCauseMaster

    return {
        row.code: {
            "name": row.name,
            "definition": row.description,
            "standard_remediation_pattern": row.standard_remediation_pattern,
            "user_definition": getattr(row, "user_definition", None) or "",
        }
        for row in RootCauseMaster.objects.all()
    }


@lru_cache(maxsize=8)
def _load_check_name_catalogue_db(cache_token: str) -> dict[str, dict[str, Any]]:
    del cache_token
    from dataruns.models import CheckMaster as CheckMasterRow

    return {
        row.check_id: {
            "check_name": row.check_name,
            "severity": row.severity,
            "root_cause_ids": list(row.root_cause_ids or []),
            "systems_compared": row.systems_compared,
            "cadence": row.cadence,
            "suggested_fix": row.suggested_fix or "",
            "fix_type": row.fix_type or "",
            "fix_owner": row.fix_owner or "",
        }
        for row in CheckMasterRow.objects.filter(is_active=True)
    }


def load_root_cause_catalogue() -> dict[str, dict[str, Any]]:
    try:
        from_db = _load_root_cause_catalogue_db(_rc_cache_token())
        if from_db:
            return from_db
    except Exception:  # noqa: BLE001
        pass
    return _load_root_cause_catalogue_json()


def load_foundation_gate_catalogue() -> dict[str, dict[str, Any]]:
    """
    Merge JSON catalogue (detection_logic / suggested_fix) with DB CheckMaster
    fields (name, severity, root_cause_ids) when seeded.
    """
    base = dict(_load_foundation_gate_catalogue_json())
    try:
        from_db = _load_check_name_catalogue_db(_check_cache_token())
    except Exception:  # noqa: BLE001
        return base
    if not from_db:
        return base
    merged: dict[str, dict[str, Any]] = {}
    for check_id, db_row in from_db.items():
        merged[check_id] = {**(base.get(check_id) or {}), **db_row}
    # Keep JSON-only keys (should not happen for MVP1).
    for check_id, json_row in base.items():
        merged.setdefault(check_id, dict(json_row))
    return merged


def root_cause_details(codes: list[str]) -> list[dict[str, str]]:
    taxonomy = load_root_cause_catalogue()
    details: list[dict[str, str]] = []
    for code in codes:
        row = taxonomy.get(code)
        if not row:
            details.append(
                {
                    "code": code,
                    "name": code,
                    "definition": "",
                    "standard_remediation_pattern": "",
                }
            )
            continue
        details.append(
            {
                "code": code,
                "name": str(row.get("name") or code),
                "definition": str(row.get("definition") or ""),
                "user_definition": str(row.get("user_definition") or ""),
                "standard_remediation_pattern": str(
                    row.get("standard_remediation_pattern") or ""
                ),
            }
        )
    return details


def foundation_gate_meta(check_id: str) -> dict[str, Any]:
    return dict(load_foundation_gate_catalogue().get(check_id) or {})


def user_facing_check_name(check_id: str) -> str:
    """Plain-language check title for UI / email (falls back to catalogue name)."""
    meta = foundation_gate_meta(check_id)
    return str(
        meta.get("user_check_name") or meta.get("check_name") or check_id
    ).strip()


def user_facing_suggested_fix(check_id: str, fallback: str | None = None) -> str | None:
    """Plain-language remediation for merchants."""
    meta = foundation_gate_meta(check_id)
    text = str(
        meta.get("user_suggested_fix")
        or fallback
        or meta.get("suggested_fix")
        or ""
    ).strip()
    return text or None


def build_failure_message(
    *,
    check_id: str,
    root_cause_ids: list[str],
    detail: str | None = None,
) -> str:
    """
    Merchant-facing fail message stored on QaCheck / shown in email.

    Prefer a concrete ``detail`` when provided. Otherwise explain the primary
    root cause in plain language. Technical IDs (FD-*, RC-*) stay on
    ``reason_code`` / ``root_cause_ids`` / evidence — not in this string.
    """
    title = user_facing_check_name(check_id)
    detail_clean = (detail or "").strip()
    if detail_clean:
        return detail_clean

    rc_parts = root_cause_details(root_cause_ids)
    if rc_parts:
        primary = rc_parts[0]
        explanation = str(
            primary.get("user_definition")
            or primary.get("definition")
            or ""
        ).strip()
        name = str(primary.get("name") or "").strip()
        if explanation:
            return f"{title}: {explanation}"
        if name:
            return f"{title}: {name}."
    return f"{title} needs attention."
