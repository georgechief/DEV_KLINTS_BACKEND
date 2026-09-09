"""Add, remove, or seed writeback check allowlist rows (DB; no env)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dataruns.models import WritebackAllowedCheck
from dataruns.tests.writeback_helpers import DEFAULT_WRITEBACK_ALLOWLIST

DEFAULT_CHECKS = DEFAULT_WRITEBACK_ALLOWLIST


class Command(BaseCommand):
    help = "Manage WritebackAllowedCheck rows for writeback execute gates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-id",
            action="append",
            default=[],
            help="Check id to enable/disable (repeatable).",
        )
        parser.add_argument(
            "--enable",
            action="store_true",
            help="Enable the given check id(s).",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Disable the given check id(s).",
        )
        parser.add_argument(
            "--seed-defaults",
            action="store_true",
            help=f"Ensure defaults exist: {', '.join(DEFAULT_CHECKS)}.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="Print current allowlist rows.",
        )

    def handle(self, *args, **options):
        if options["list"]:
            rows = WritebackAllowedCheck.objects.order_by("check_id")
            if not rows.exists():
                self.stdout.write("No writeback allowlist rows.")
                return
            for row in rows:
                state = "enabled" if row.enabled else "disabled"
                self.stdout.write(f"{row.check_id}\t{state}")
            return

        if options["seed_defaults"]:
            for check_id in DEFAULT_CHECKS:
                row, created = WritebackAllowedCheck.objects.get_or_create(
                    check_id=check_id,
                    defaults={"enabled": True},
                )
                if not created and not row.enabled:
                    row.enabled = True
                    row.save(update_fields=["enabled", "updated_at"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Default writeback allowlist ready: {', '.join(DEFAULT_CHECKS)}"
                )
            )
            return

        check_ids = [str(value).strip().upper() for value in options["check_id"] if value]
        enable = bool(options["enable"])
        disable = bool(options["disable"])
        if not check_ids:
            raise CommandError(
                "Pass --check-id, --seed-defaults, or --list."
            )
        if enable == disable:
            raise CommandError("Pass exactly one of --enable or --disable.")

        for check_id in check_ids:
            row, _created = WritebackAllowedCheck.objects.get_or_create(
                check_id=check_id,
                defaults={"enabled": enable},
            )
            if row.enabled != enable:
                row.enabled = enable
                row.save(update_fields=["enabled", "updated_at"])
            state = "enabled" if enable else "disabled"
            self.stdout.write(
                self.style.SUCCESS(f"Writeback allowlist: {check_id} {state}.")
            )
