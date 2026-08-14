from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from dataruns.use_cases.constants import DEFAULT_BLUEPRINTS_DIR_REL, DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import (
    BlueprintValidationError,
    load_use_case_pilots_from_pack,
)


class Command(BaseCommand):
    help = "Load MVP1 use-case pilots and blueprints from the Build Pack (PRD-UC-01 §8.2)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            type=str,
            default="",
            help="Path to pilot_manifest.json (default: pack 04_MVP1_Pilot_Blueprints/).",
        )
        parser.add_argument(
            "--blueprints-dir",
            type=str,
            default="",
            help="Directory containing UC-*_blueprint.json files.",
        )

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        manifest_arg = (options.get("manifest") or "").strip()
        if manifest_arg:
            manifest_path = Path(manifest_arg)
            if not manifest_path.is_absolute():
                manifest_path = base / manifest_path
        else:
            manifest_path = base / DEFAULT_MANIFEST_REL

        blueprints_arg = (options.get("blueprints_dir") or "").strip()
        if blueprints_arg:
            blueprints_dir = Path(blueprints_arg)
            if not blueprints_dir.is_absolute():
                blueprints_dir = base / blueprints_dir
        else:
            blueprints_dir = base / DEFAULT_BLUEPRINTS_DIR_REL

        try:
            result = load_use_case_pilots_from_pack(
                manifest_path=manifest_path,
                blueprints_dir=blueprints_dir,
            )
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc
        except BlueprintValidationError as exc:
            raise CommandError(f"Blueprint validation failed: {exc}") from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Use-case pilot load complete:\n"
                f"  Pilots upserted: {result.pilots_upserted}\n"
                f"  Blueprints upserted: {result.blueprints_upserted}\n"
                f"  Stage maps upserted: {result.stage_maps_upserted}\n"
                f"  IDs: {', '.join(result.pilot_ids)}"
            )
        )
