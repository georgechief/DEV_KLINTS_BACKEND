"""Load the WB-01C possible/not CSV (source of truth for GET /writebacks/possible/)."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

SHEET_SCHEMA_VERSION = 1
PACKAGE_CSV_FILENAME = "WRITEBACK_POSSIBLE_NOT_SHEET.csv"
# Docs path is optional in production because `.dockerignore` excludes `docs/`.
DOCS_RELATIVE_PATH = Path("docs") / "maheep" / PACKAGE_CSV_FILENAME
PACKAGE_SOURCE_RELATIVE = "dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv"
DOCS_SOURCE_RELATIVE = "docs/maheep/WRITEBACK_POSSIBLE_NOT_SHEET.csv"
SHEET_GENERATED_FROM = [
    "pack:02 Check Catalogue",
    "pack:Manago Capability Matrix",
    "dataruns/writebacks/mappings/",
    "docs/maheep/WRITEBACK_SURFACE_MATRIX.md",
]

SHEET_COLUMNS = (
    "check_id",
    "check_name",
    "pack_fix_type",
    "pack_fix_owner",
    "pack_suggested_fix_summary",
    "platform",
    "op_kind",
    "entity",
    "field_or_key",
    "namespace",
    "creates_new",
    "updates_existing",
    "write_possible_today",
    "rollback_possible_today",
    "mapping_file",
    "registry_enabled",
    "blocker",
    "evidence_note",
    "last_verified",
)

_TRUE_VALUES = frozenset({"true", "1", "yes"})
_FALSE_VALUES = frozenset({"false", "0", "no", ""})


class PossibleSheetError(ValueError):
    pass


def possible_sheet_path() -> Path:
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    # 1) Preferred runtime SoT inside the package image (Docker-safe).
    pkg_candidate = here.parent / PACKAGE_CSV_FILENAME
    if pkg_candidate.exists():
        return pkg_candidate
    # 2) Optional fallback: local/editor builds that still contain docs/.
    candidate = repo_root / DOCS_RELATIVE_PATH
    if candidate.exists():
        return candidate
    try:
        from django.conf import settings

        alt = Path(settings.BASE_DIR) / DOCS_RELATIVE_PATH
        if alt.exists():
            return alt
    except Exception:
        pass
    # Return pkg candidate if we have it (so error message points at the runtime path);
    # otherwise return docs candidate (so local dev errors remain intuitive).
    return pkg_candidate if pkg_candidate.exists() else candidate


def _parse_registry_enabled(raw: str) -> bool:
    value = (raw or "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise PossibleSheetError(f"registry_enabled must be true/false, got {raw!r}")


def _normalize_row(raw: dict[str, str]) -> dict[str, Any]:
    row = {column: (raw.get(column) or "").strip() for column in SHEET_COLUMNS}
    row["registry_enabled"] = _parse_registry_enabled(str(raw.get("registry_enabled") or ""))
    return row


@lru_cache(maxsize=1)
def load_possible_sheet(path: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    sheet_path = Path(path) if path else possible_sheet_path()
    if not sheet_path.exists():
        raise PossibleSheetError(f"Possible/not sheet not found: {sheet_path}")

    rows: list[dict[str, Any]] = []
    with sheet_path.open(encoding="utf-8", newline="") as handle:
        filtered = (
            line
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        )
        reader = csv.DictReader(filtered)
        if reader.fieldnames is None:
            raise PossibleSheetError("Possible/not sheet is missing a header row")
        found = [name.strip() for name in reader.fieldnames if name and name.strip()]
        if tuple(found) != SHEET_COLUMNS:
            raise PossibleSheetError(
                "Possible/not sheet columns do not match PRD-WB-01C §2.2. "
                f"expected={list(SHEET_COLUMNS)} found={found}"
            )
        for raw in reader:
            if not any((raw.get(column) or "").strip() for column in SHEET_COLUMNS):
                continue
            rows.append(_normalize_row(raw))

    if not rows:
        raise PossibleSheetError("Possible/not sheet has no data rows")

    pkg_path = (Path(__file__).resolve().parent / PACKAGE_CSV_FILENAME).resolve()
    chosen = sheet_path.resolve()
    if chosen == pkg_path:
        return PACKAGE_SOURCE_RELATIVE, rows

    # Fallback: report docs path for local/editor fallback cases.
    return DOCS_SOURCE_RELATIVE, rows


def possible_sheet_payload() -> dict[str, Any]:
    source, rows = load_possible_sheet()
    return {
        "schema_version": SHEET_SCHEMA_VERSION,
        "source": source,
        "generated_from": list(SHEET_GENERATED_FROM),
        "count": len(rows),
        "rows": rows,
    }
