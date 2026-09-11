"""Ensure global catalogue seeds exist after migrate (deploy / empty DB recovery).

DCS CheckMaster is seeded only when empty/incomplete (Excel read is slower).
Use-case pilots always upsert (OPS-UC-01 — idempotent, picks up pack updates).
"""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from dataruns.models import CheckMaster
from dataruns.use_cases.models import UseCasePilot

# Runtime master expects 42 active checks (dataruns.dcs.master).
_MIN_CHECK_MASTERS = 42
_MIN_PILOTS = 16


class Command(BaseCommand):
    help = (
        "Ensure DCS master + MVP1 pilots exist for this environment. "
        "Safe to run on every web boot."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-dcs-master",
            action="store_true",
            help="Re-run seed_dcs_master even when CheckMaster rows already exist.",
        )

    def handle(self, *args, **options):
        force_dcs = bool(options.get("force_dcs_master"))
        # Mirror dataruns.dcs.master: only active rows count toward the 42-check threshold.
        check_count = CheckMaster.objects.filter(is_active=True).count()

        if force_dcs or check_count < _MIN_CHECK_MASTERS:
            if check_count == 0:
                self.stdout.write("CheckMaster empty — running seed_dcs_master…")
            elif force_dcs:
                self.stdout.write(
                    f"Forcing seed_dcs_master (active CheckMaster={check_count})…"
                )
            else:
                self.stdout.write(
                    "CheckMaster incomplete "
                    f"({check_count} active < {_MIN_CHECK_MASTERS}) — "
                    "running seed_dcs_master…"
                )
            call_command("seed_dcs_master", verbosity=1)
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"CheckMaster OK ({check_count} active rows) — skip seed_dcs_master"
                )
            )

        pilot_count = UseCasePilot.objects.count()
        self.stdout.write(
            f"Loading use-case pilots (current count={pilot_count})…"
        )
        call_command("load_use_case_pilots", verbosity=1)
        pilot_count = UseCasePilot.objects.count()
        if pilot_count < _MIN_PILOTS:
            raise CommandError(
                f"UseCasePilot count {pilot_count} < {_MIN_PILOTS} "
                "after load_use_case_pilots"
            )

        # Re-read after potential seed (mirror master.py: active-only).
        check_count = CheckMaster.objects.filter(is_active=True).count()
        if check_count < _MIN_CHECK_MASTERS:
            raise CommandError(
                f"CheckMaster count {check_count} < {_MIN_CHECK_MASTERS} "
                "after seed_dcs_master"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Runtime catalogue ready: "
                f"CheckMaster={check_count}, UseCasePilot={pilot_count}"
            )
        )
