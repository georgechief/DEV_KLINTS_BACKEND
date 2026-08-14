from django.core.management.base import BaseCommand, CommandError

from dataruns.audit import verify_audit_chain_for_company
from tenants.models import Company


class Command(BaseCommand):
    help = "Verify per-company audit log hash chain integrity (PRD-AUDIT-01 §8)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company-id",
            required=True,
            help="Company UUID to verify.",
        )

    def handle(self, *args, **options):
        company_id = options["company_id"]
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise CommandError(f"Company not found: {company_id}")

        errors = verify_audit_chain_for_company(company=company)
        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError(f"Audit chain verification failed for company {company_id}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Audit chain verification passed for company {company_id}"
            )
        )
