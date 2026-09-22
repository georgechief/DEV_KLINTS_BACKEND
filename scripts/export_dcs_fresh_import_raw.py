#!/usr/bin/env python
"""
Export ConnectorSnapshot.raw from DCS fresh-import runs for offline debugging.

Read-only: does not modify application data, DCS checks, or connector payloads.

Usage examples:
  # After a DCS run completes, export by DataRun id:
  python scripts/export_dcs_fresh_import_raw.py --dcs-data-run-id 458

  # Export latest succeeded DCS run for a company:
  python scripts/export_dcs_fresh_import_raw.py --company-id <uuid> --latest

  # Poll until a running DCS run finishes fresh imports, then export immediately:
  python scripts/export_dcs_fresh_import_raw.py --watch-dcs-data-run-id 461 --poll-seconds 5

  # Export directly by ConnectorSnapshot id (e.g. from metadata.fresh_imports):
  python scripts/export_dcs_fresh_import_raw.py --snapshot-id <uuid> --platform shopify

Output layout (under --output-dir, default exports/dcs_fresh_import_raw/):
  <dcs_run_or_timestamp>/
    manifest.json
    shopify_snapshot_<snapshot_id>.json          # full snapshot_data (includes raw)
    shopify_raw_orders_<snapshot_id>.json        # snapshot_data.raw.orders only
    manago_ai_snapshot_<snapshot_id>.json
    manago_ai_raw_transactions_<snapshot_id>.json
    manago_ai_raw_contacts_<snapshot_id>.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django

django.setup()

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.models import DataRun
from tenants.models import ConnectorSnapshot

DEFAULT_OUTPUT_ROOT = BACKEND / "exports" / "dcs_fresh_import_raw"
PLATFORMS = ("shopify", "manago_ai")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def _parse_uuid(value: str, *, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid {label}: {value!r}") from exc


def _resolve_dcs_data_run(
    *,
    dcs_data_run_id: int | None,
    watch_dcs_data_run_id: int | None,
    company_id: str | None,
    latest: bool,
) -> DataRun:
    if watch_dcs_data_run_id is not None:
        return DataRun.objects.get(pk=watch_dcs_data_run_id)
    if dcs_data_run_id is not None:
        return DataRun.objects.get(pk=dcs_data_run_id)
    if latest:
        qs = DataRun.objects.filter(
            metadata__kind=DCS_SCORE_KIND,
            status=DataRun.Status.SUCCEEDED,
        )
        if company_id:
            qs = qs.filter(metadata__company_id=str(company_id))
        run = qs.order_by("-id").first()
        if run is None:
            raise SystemExit("No succeeded DCS DataRun found.")
        return run
    raise SystemExit(
        "Provide --dcs-data-run-id, --watch-dcs-data-run-id, or --latest."
    )


def _fresh_imports_ready(data_run: DataRun) -> bool:
    meta = data_run.metadata or {}
    fresh = meta.get("fresh_imports")
    if not isinstance(fresh, dict):
        return False
    for platform in PLATFORMS:
        block = fresh.get(platform)
        if not isinstance(block, dict):
            continue
        if block.get("data_run_id") is not None and block.get("snapshot_id"):
            return True
    return False


def _wait_for_fresh_imports(
    data_run: DataRun,
    *,
    poll_seconds: float,
    timeout_seconds: float,
) -> DataRun:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        data_run.refresh_from_db()
        if _fresh_imports_ready(data_run):
            return data_run
        if data_run.status in {
            DataRun.Status.SUCCEEDED,
            DataRun.Status.FAILED,
        } and not _fresh_imports_ready(data_run):
            break
        time.sleep(poll_seconds)
    data_run.refresh_from_db()
    if not _fresh_imports_ready(data_run):
        raise SystemExit(
            f"DCS DataRun {data_run.id} has no fresh_imports.snapshot_id yet "
            f"(status={data_run.status}). Export after fresh imports complete."
        )
    return data_run


def _load_snapshot(snapshot_id: str) -> ConnectorSnapshot:
    try:
        return ConnectorSnapshot.objects.get(pk=snapshot_id)
    except ConnectorSnapshot.DoesNotExist as exc:
        raise SystemExit(
            f"ConnectorSnapshot {snapshot_id!r} not found in DB. "
            "It may have been deleted (connector CASCADE) or never persisted."
        ) from exc


def _export_platform_raw(
    *,
    platform: str,
    snapshot_id: str,
    out_dir: Path,
) -> dict[str, Any]:
    snapshot = _load_snapshot(snapshot_id)
    snapshot_data = snapshot.snapshot_data
    if not isinstance(snapshot_data, dict):
        snapshot_data = {}
    raw = snapshot_data.get("raw")
    if not isinstance(raw, dict):
        raw = {}

    platform_prefix = platform.replace("_", "-")
    full_path = out_dir / f"{platform}_snapshot_{snapshot_id}.json"
    _write_json(
        full_path,
        {
            "snapshot_id": str(snapshot.id),
            "connector_id": str(snapshot.connector_id),
            "version": snapshot.version,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            "snapshot_data": snapshot_data,
        },
    )

    sidecar_paths: dict[str, str] = {"full_snapshot_json": str(full_path)}

    if platform == "shopify":
        orders = raw.get("orders")
        if not isinstance(orders, list):
            orders = []
        orders_path = out_dir / f"shopify_raw_orders_{snapshot_id}.json"
        _write_json(
            orders_path,
            {
                "snapshot_id": str(snapshot.id),
                "platform": platform,
                "record_type": "orders",
                "count": len(orders),
                "records": orders,
            },
        )
        sidecar_paths["raw_orders_json"] = str(orders_path)
        sidecar_paths["orders_count"] = len(orders)

    elif platform == "manago_ai":
        transactions = raw.get("transactions")
        if not isinstance(transactions, list):
            transactions = []
        contacts = raw.get("contacts")
        if not isinstance(contacts, list):
            contacts = []

        tx_path = out_dir / f"manago_ai_raw_transactions_{snapshot_id}.json"
        _write_json(
            tx_path,
            {
                "snapshot_id": str(snapshot.id),
                "platform": platform,
                "record_type": "transactions",
                "count": len(transactions),
                "records": transactions,
            },
        )
        contacts_path = out_dir / f"manago_ai_raw_contacts_{snapshot_id}.json"
        _write_json(
            contacts_path,
            {
                "snapshot_id": str(snapshot.id),
                "platform": platform,
                "record_type": "contacts",
                "count": len(contacts),
                "records": contacts,
            },
        )
        sidecar_paths["raw_transactions_json"] = str(tx_path)
        sidecar_paths["raw_contacts_json"] = str(contacts_path)
        sidecar_paths["transactions_count"] = len(transactions)
        sidecar_paths["contacts_count"] = len(contacts)

    return {
        "platform": platform,
        "snapshot_id": str(snapshot.id),
        "connector_id": str(snapshot.connector_id),
        "snapshot_version": snapshot.version,
        "snapshot_created_at": snapshot.created_at.isoformat()
        if snapshot.created_at
        else None,
        "files": sidecar_paths,
        "raw_keys": sorted(raw.keys()),
    }


def export_from_dcs_data_run(
    data_run: DataRun,
    *,
    output_dir: Path,
) -> Path:
    meta = data_run.metadata or {}
    fresh_imports = meta.get("fresh_imports")
    if not isinstance(fresh_imports, dict):
        raise SystemExit(
            f"DCS DataRun {data_run.id} has no metadata.fresh_imports."
        )

    run_label = f"dcs_{data_run.id}_{_utc_stamp()}"
    out_dir = output_dir / run_label
    out_dir.mkdir(parents=True, exist_ok=True)

    exported: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for platform in PLATFORMS:
        block = fresh_imports.get(platform)
        if not isinstance(block, dict):
            missing.append({"platform": platform, "reason": "no fresh_imports block"})
            continue
        snapshot_id = block.get("snapshot_id")
        if not snapshot_id:
            missing.append({"platform": platform, "reason": "snapshot_id missing"})
            continue
        snapshot_id = str(snapshot_id)
        try:
            exported.append(
                _export_platform_raw(
                    platform=platform,
                    snapshot_id=snapshot_id,
                    out_dir=out_dir,
                )
            )
        except SystemExit as exc:
            missing.append(
                {
                    "platform": platform,
                    "snapshot_id": snapshot_id,
                    "reason": str(exc),
                }
            )

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dcs_data_run_id": data_run.id,
        "dcs_status": data_run.status,
        "company_id": meta.get("company_id"),
        "dcs_finished_at": data_run.finished_at.isoformat()
        if data_run.finished_at
        else None,
        "fresh_imports": fresh_imports,
        "source_runs": meta.get("source_runs"),
        "exported_platforms": exported,
        "missing_or_failed": missing,
        "output_directory": str(out_dir.resolve()),
    }
    manifest_path = out_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    print(f"Wrote manifest: {manifest_path.resolve()}")
    for item in exported:
        print(
            f"  {item['platform']}: snapshot_id={item['snapshot_id']} "
            f"orders/tx={item['files'].get('orders_count') or item['files'].get('transactions_count')}"
        )
    if missing:
        print("Missing/failed exports:")
        for item in missing:
            print(f"  {item}")
    return out_dir


def export_single_snapshot(
    *,
    snapshot_id: str,
    platform: str,
    output_dir: Path,
) -> Path:
    _parse_uuid(snapshot_id, label="snapshot_id")
    if platform not in PLATFORMS:
        raise SystemExit(f"--platform must be one of {PLATFORMS}")
    out_dir = output_dir / f"snapshot_{snapshot_id}_{_utc_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    _export_platform_raw(platform=platform, snapshot_id=snapshot_id, out_dir=out_dir)
    manifest_path = out_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_id": snapshot_id,
            "platform": platform,
            "output_directory": str(out_dir.resolve()),
        },
    )
    print(f"Exported snapshot {snapshot_id} to {out_dir.resolve()}")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export DCS fresh-import ConnectorSnapshot.raw to JSON files."
    )
    parser.add_argument("--dcs-data-run-id", type=int, help="Succeeded/running DCS DataRun id")
    parser.add_argument(
        "--watch-dcs-data-run-id",
        type=int,
        help="Poll until fresh_imports appear on this DCS DataRun, then export",
    )
    parser.add_argument("--company-id", help="Filter --latest to one company uuid")
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Use latest succeeded DCS DataRun (optional --company-id filter)",
    )
    parser.add_argument(
        "--snapshot-id",
        help="Export one ConnectorSnapshot directly (requires --platform)",
    )
    parser.add_argument(
        "--platform",
        choices=PLATFORMS,
        help="Platform label when using --snapshot-id",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root directory (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Poll interval for --watch-dcs-data-run-id",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=3600.0,
        help="Max wait for --watch-dcs-data-run-id",
    )
    args = parser.parse_args()

    if args.snapshot_id:
        if not args.platform:
            raise SystemExit("--platform is required with --snapshot-id")
        export_single_snapshot(
            snapshot_id=args.snapshot_id,
            platform=args.platform,
            output_dir=args.output_dir,
        )
        return

    data_run = _resolve_dcs_data_run(
        dcs_data_run_id=args.dcs_data_run_id,
        watch_dcs_data_run_id=args.watch_dcs_data_run_id,
        company_id=args.company_id,
        latest=args.latest,
    )

    if args.watch_dcs_data_run_id is not None:
        print(
            f"Waiting for fresh_imports on DCS DataRun {data_run.id} "
            f"(poll={args.poll_seconds}s, timeout={args.timeout_seconds}s)..."
        )
        data_run = _wait_for_fresh_imports(
            data_run,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )

    export_from_dcs_data_run(data_run, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
