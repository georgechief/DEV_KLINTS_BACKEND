"""Load and validate MVP1 pilot blueprints from the Build Pack."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from dataruns.use_cases.constants import (
    MVP1_PILOT_COUNT,
    MVP1_PILOT_IDS,
    PILOT_PRIMARY_STAGES,
    USE_CASE_ID_RE,
)
from dataruns.use_cases.gaps import assert_stage_map_complete
from dataruns.use_cases.models import PilotStageMap, UseCaseBlueprint, UseCasePilot

USE_CASE_ID_PATTERN = re.compile(USE_CASE_ID_RE)


class BlueprintValidationError(ValueError):
    """Blueprint JSON failed pragmatic pack validation."""


REQUIRED_BLUEPRINT_KEYS = frozenset(
    {
        "schema_version",
        "blueprint_id",
        "use_case_id",
        "variant_id",
        "release",
        "target_platform",
        "gates",
        "audience",
        "trigger",
        "workflow",
        "measurement",
        "qa",
        "approval",
        "rollback",
        "capability_dependencies",
        "provenance",
    }
)


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def validate_blueprint_payload(
    payload: dict[str, Any],
    *,
    expected_use_case_id: str | None = None,
) -> None:
    """
    Pragmatic validation (PRD §8.2) — required gates/nodes without full Draft-2020-12.
    """
    if not isinstance(payload, dict):
        raise BlueprintValidationError("Blueprint must be a JSON object.")

    missing = REQUIRED_BLUEPRINT_KEYS - set(payload.keys())
    if missing:
        raise BlueprintValidationError(
            f"Blueprint missing required keys: {', '.join(sorted(missing))}"
        )

    use_case_id = str(payload.get("use_case_id") or "").strip()
    if not USE_CASE_ID_PATTERN.match(use_case_id):
        raise BlueprintValidationError(f"Invalid use_case_id: {use_case_id!r}")
    if use_case_id not in MVP1_PILOT_IDS:
        raise BlueprintValidationError(
            f"use_case_id {use_case_id} is not an MVP1 pilot (see PRD §3.1)."
        )
    if expected_use_case_id and use_case_id != expected_use_case_id:
        raise BlueprintValidationError(
            f"Blueprint use_case_id {use_case_id} != manifest {expected_use_case_id}."
        )

    gates = payload.get("gates")
    if not isinstance(gates, dict):
        raise BlueprintValidationError("gates must be an object.")
    if "min_dcs" not in gates:
        raise BlueprintValidationError("gates.min_dcs is required.")
    gating = gates.get("gating_check_ids")
    if not isinstance(gating, list) or not gating:
        raise BlueprintValidationError("gates.gating_check_ids must be a non-empty list.")

    workflow = payload.get("workflow")
    if not isinstance(workflow, dict):
        raise BlueprintValidationError("workflow must be an object.")
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or len(nodes) < 2:
        raise BlueprintValidationError("workflow.nodes must contain at least 2 nodes.")


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("pilot_manifest.json must be a JSON object.")
    pilots = data.get("pilots")
    if not isinstance(pilots, list):
        raise ValueError("pilot_manifest.json must contain a pilots array.")
    return data


def resolve_blueprint_path(blueprints_dir: Path, filename: str) -> Path:
    path = (blueprints_dir / filename).resolve()
    if blueprints_dir.resolve() not in path.parents and path != blueprints_dir.resolve():
        raise BlueprintValidationError(f"Blueprint path escapes pack directory: {filename}")
    return path


@dataclass
class LoadUseCasePilotsResult:
    pilots_upserted: int
    blueprints_upserted: int
    stage_maps_upserted: int
    pilot_ids: list[str]


@transaction.atomic
def load_use_case_pilots_from_pack(
    *,
    manifest_path: Path,
    blueprints_dir: Path | None = None,
) -> LoadUseCasePilotsResult:
    """
    Idempotent upsert of 16 MVP1 pilots + blueprints + stage maps.
    """
    assert_stage_map_complete()
    manifest = load_manifest(manifest_path)
    pilots = manifest.get("pilots") or []
    if len(pilots) != MVP1_PILOT_COUNT:
        raise ValueError(
            f"Expected {MVP1_PILOT_COUNT} pilots in manifest, got {len(pilots)}."
        )

    if blueprints_dir is None:
        blueprints_dir = manifest_path.parent

    seen_ids: set[str] = set()
    seen_ranks: set[int] = set()
    pilot_ids: list[str] = []

    for entry in pilots:
        if not isinstance(entry, dict):
            raise ValueError("Each manifest pilot entry must be an object.")
        use_case_id = str(entry.get("use_case_id") or "").strip()
        if use_case_id in seen_ids:
            raise ValueError(f"Duplicate use_case_id in manifest: {use_case_id}")
        seen_ids.add(use_case_id)
        if use_case_id not in MVP1_PILOT_IDS:
            raise ValueError(f"Unexpected pilot in manifest: {use_case_id}")
        pilot_ids.append(use_case_id)

        rank = int(entry.get("rank") or 0)
        if rank in seen_ranks:
            raise ValueError(f"Duplicate pilot rank in manifest: {rank}")
        seen_ranks.add(rank)

        filename = str(entry.get("file") or "").strip()
        if not filename:
            raise ValueError(f"Manifest entry {use_case_id} missing file.")

        blueprint_path = resolve_blueprint_path(blueprints_dir, filename)
        if not blueprint_path.is_file():
            raise FileNotFoundError(f"Blueprint file not found: {blueprint_path}")

        with blueprint_path.open(encoding="utf-8") as handle:
            body = json.load(handle)
        validate_blueprint_payload(body, expected_use_case_id=use_case_id)
        digest = content_hash(body)

        UseCasePilot.objects.update_or_create(
            use_case_id=use_case_id,
            defaults={
                "pilot_rank": rank,
                "title": str(entry.get("title") or body.get("title") or use_case_id),
                "release": str(manifest.get("release") or body.get("release") or "MVP1"),
                "manifest_status": str(entry.get("status") or ""),
                "mcp_dependency": bool(entry.get("mcp_dependency", True)),
                "fallback": str(entry.get("fallback") or "HUMAN.WORKFLOW.BUILD"),
                "blueprint_file": filename,
            },
        )

        UseCaseBlueprint.objects.update_or_create(
            pilot_id=use_case_id,
            defaults={
                "blueprint_id": str(body["blueprint_id"]),
                "schema_version": str(body["schema_version"]),
                "body": body,
                "content_hash": digest,
                "loaded_at": timezone.now(),
            },
        )

        PilotStageMap.objects.filter(pilot_id=use_case_id).delete()
        for stage_id in PILOT_PRIMARY_STAGES.get(use_case_id, ()):
            PilotStageMap.objects.create(
                pilot_id=use_case_id,
                stage_id=stage_id,
                is_primary=True,
            )

    if seen_ids != MVP1_PILOT_IDS:
        missing = MVP1_PILOT_IDS - seen_ids
        extra = seen_ids - MVP1_PILOT_IDS
        raise ValueError(
            f"MVP1 pilot set mismatch. missing={sorted(missing)} extra={sorted(extra)}"
        )

    if "UC-06B" not in seen_ids:
        raise ValueError("UC-06B must be present in manifest.")
    if "UC-06A" in seen_ids:
        raise ValueError("UC-06A must not be loaded as MVP1 pilot.")

    rank_by_id = {str(p["use_case_id"]): int(p["rank"]) for p in pilots}
    ordered_ids = sorted(seen_ids, key=lambda pid: rank_by_id[pid])

    return LoadUseCasePilotsResult(
        pilots_upserted=len(ordered_ids),
        blueprints_upserted=len(ordered_ids),
        stage_maps_upserted=sum(len(PILOT_PRIMARY_STAGES[p]) for p in ordered_ids),
        pilot_ids=ordered_ids,
    )
