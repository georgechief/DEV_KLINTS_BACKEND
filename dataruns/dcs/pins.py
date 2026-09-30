"""Resolve DCS scoring pins from a terminal DataRun (solid scoring universe).

Score and Fix/writeback live rebuild must share the same pinned ConnectorSnapshots
from ``metadata.fresh_imports`` / ``metadata.source_runs`` — never silently mix
with Contact DB ghosts or a newer unrelated snapshot.
"""

from __future__ import annotations

from typing import Any

from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.worklist import get_latest_terminal_dcs_run
from dataruns.models import DataRun
from tenants.models import Company

SourceRunIds = dict[str, int | None]
PinnedSnapshotIds = dict[str, str | None]


def normalize_source_run_ids(source_runs: dict[str, Any] | None) -> SourceRunIds:
    out: SourceRunIds = {"shopify": None, "manago_ai": None}
    if not isinstance(source_runs, dict):
        return out
    for platform in ("shopify", "manago_ai"):
        value = source_runs.get(platform)
        if value is None:
            continue
        try:
            out[platform] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def pinned_snapshot_ids_from_fresh_imports(
    fresh_imports: dict[str, Any] | None,
) -> PinnedSnapshotIds:
    out: PinnedSnapshotIds = {"shopify": None, "manago_ai": None}
    if not isinstance(fresh_imports, dict):
        return out
    for platform in ("shopify", "manago_ai"):
        block = fresh_imports.get(platform)
        if not isinstance(block, dict):
            continue
        snapshot_id = block.get("snapshot_id")
        if snapshot_id is not None and str(snapshot_id).strip():
            out[platform] = str(snapshot_id)
    return out


def pins_from_dcs_data_run(
    data_run: DataRun | None,
) -> tuple[SourceRunIds, PinnedSnapshotIds]:
    """Extract source_run_ids + snapshot_ids from a DCS DataRun metadata."""
    if data_run is None:
        return (
            {"shopify": None, "manago_ai": None},
            {"shopify": None, "manago_ai": None},
        )
    meta = data_run.metadata if isinstance(data_run.metadata, dict) else {}
    return (
        normalize_source_run_ids(meta.get("source_runs")),
        pinned_snapshot_ids_from_fresh_imports(meta.get("fresh_imports")),
    )


def resolve_scoring_pins(
    *,
    company: Company,
    dcs_data_run: DataRun | None = None,
) -> tuple[SourceRunIds, PinnedSnapshotIds, DataRun | None]:
    """Return (source_run_ids, pinned_snapshot_ids, data_run).

    Defaults to the latest **succeeded** DCS score for the company (not FAILED),
    so Fix never rebuilds from a broken run's empty pins.
    """
    run = dcs_data_run
    if run is None:
        run = (
            DataRun.objects.filter(
                name=DCS_SCORE_DATA_RUN_NAME,
                status=DataRun.Status.SUCCEEDED,
                metadata__kind=DCS_SCORE_KIND,
                metadata__company_id=str(company.id),
            )
            .order_by("-created_at")
            .first()
        )
        if run is None:
            # Fallback: any terminal run (worklist may still show FAILED).
            run = get_latest_terminal_dcs_run(company=company)
    source_runs, snapshots = pins_from_dcs_data_run(run)
    return source_runs, snapshots, run


def has_any_pin(
    source_run_ids: SourceRunIds | None,
    pinned_snapshot_ids: PinnedSnapshotIds | None,
) -> bool:
    ids = source_run_ids or {}
    snaps = pinned_snapshot_ids or {}
    return any(ids.get(p) for p in ("shopify", "manago_ai")) or any(
        snaps.get(p) for p in ("shopify", "manago_ai")
    )
