"""Set Company.writeback_execute_enabled for writeback approve/execute."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from tenants.models import Company


class Command(BaseCommand):
    help = "Set Company.writeback_execute_enabled (break-glass; product path is Settings UI)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company-id",
            required=True,
            help="Company UUID (from /api/v1/auth/me/ → company.id).",
        )
        parser.add_argument(
            "--enable",
            action="store_true",
            help="Enable writeback execute for this company.",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Disable writeback execute for this company.",
        )

    def handle(self, *args, **options):
        enable = bool(options["enable"])
        disable = bool(options["disable"])
        if enable == disable:
            raise CommandError("Pass exactly one of --enable or --disable.")

        company_id = str(options["company_id"]).strip()
        company = Company.objects.filter(id=company_id).first()
        if company is None:
            raise CommandError(f"Company not found: {company_id}")

        company.writeback_execute_enabled = enable
        company.save(update_fields=["writeback_execute_enabled"])
        state = "enabled" if enable else "disabled"
        self.stdout.write(
            self.style.SUCCESS(
                f"Writeback execute {state} for {company.name} ({company.id})."
            )
        )
