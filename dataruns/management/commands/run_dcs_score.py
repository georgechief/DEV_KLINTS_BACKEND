"""Enqueue / run a DCS score for a company (local smoke testing)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dataruns.dcs.enqueue import DcsAlreadyRunningError, enqueue_dcs_score
from dataruns.dcs.orchestrate import run_dcs_pipeline
from tenants.models import Company


class Command(BaseCommand):
    help = (
        "Enqueue (or synchronously run) a DCS score for a company. "
        "Requires Manago/Shopify bootstrap data already in DB."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company-id",
            required=True,
            help="Company UUID",
        )
        parser.add_argument(
            "--erp-in-scope",
            action="store_true",
            help="Treat ERP as in scope (default: false)",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run pipeline in-process instead of Celery .delay()",
        )
        parser.add_argument(
            "--live-revalidate",
            action="store_true",
            help="Optional live Manago/Shopify auth probe during gates",
        )

    def handle(self, *args, **options):
        company_id = options["company_id"]
        try:
            company = Company.objects.select_related("tenant").get(pk=company_id)
        except Company.DoesNotExist as exc:
            raise CommandError(f"Company not found: {company_id}") from exc

        try:
            enqueued = enqueue_dcs_score(
                company=company,
                erp_in_scope=bool(options["erp_in_scope"]),
                live_revalidate=bool(options["live_revalidate"]),
                triggered_by="management_command",
                queue=not bool(options["sync"]),
            )
        except DcsAlreadyRunningError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Created DataRun {enqueued.data_run.id} "
                f"(domain Run {enqueued.domain_run.id})"
            )
        )

        if options["sync"]:
            result = run_dcs_pipeline(enqueued.data_run)
            self.stdout.write(self.style.SUCCESS(f"Pipeline result: {result}"))
            return

        if enqueued.task_queued:
            self.stdout.write("Queued dataruns.run_dcs_score via Celery.")
        else:
            self.stdout.write("DataRun created but task was not queued.")
