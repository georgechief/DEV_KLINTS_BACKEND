"""Seed disabled writeback mapping stubs for automated-writeback checks."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from dataruns.models import CheckMaster
from dataruns.writebacks.stub_factory import (
    _MAPPINGS_DIR,
    build_stub_spec,
    load_registry,
    save_registry,
    stub_filename,
)


class Command(BaseCommand):
    help = "Create disabled writeback mapping JSON stubs for CheckMaster automated-writeback checks."

    def handle(self, *args, **options):
        registry = load_registry()
        mappings = registry.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            raise ValueError("registry.json mappings must be an object")

        created_files = 0
        created_entries = 0

        rows = CheckMaster.objects.filter(
            fix_type__icontains="Automated writeback",
        ).order_by("sequence")

        for row in rows:
            check_id = str(row.check_id or "").strip().upper()
            if not check_id:
                continue
            filename = stub_filename(check_id)
            path = _MAPPINGS_DIR / filename
            if not path.exists():
                spec = build_stub_spec(
                    check_id=check_id,
                    check_name=row.check_name,
                    template_id=_infer_template_id(row),
                )
                path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
                created_files += 1

            if check_id not in mappings:
                mappings[check_id] = {
                    "file": filename,
                    "enabled": False,
                    "template_id": _infer_template_id(row),
                }
                created_entries += 1
            elif mappings[check_id].get("file") != filename and not path.exists():
                mappings[check_id]["file"] = filename

        save_registry(registry)
        self.stdout.write(
            self.style.SUCCESS(
                f"Writeback stubs: {created_files} files written, "
                f"{created_entries} registry entries added "
                f"({len(mappings)} total mappings)."
            )
        )


def _infer_template_id(row: CheckMaster) -> str | None:
    suggested = (row.suggested_fix or "").upper()
    for token in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11"):
        if token in suggested:
            return token
    check_id = str(row.check_id or "").upper()
    if check_id.startswith("CI-"):
        return "T1"
    if check_id.startswith("LE-"):
        return "T5"
    if check_id.startswith("CC-"):
        return "T8"
    if check_id.startswith("SP-"):
        return "T9"
    if check_id.startswith("PT-"):
        return "T7"
    return None

