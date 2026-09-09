"""
GAP-01 Slice F — seed a demo tenant (W9-05 / W9-03).

Phase 1: identity + DCS master + pilots + stub connectors (no live HTTP).
Phase 2: --contacts corpus + offline DCS mid-band (REMEDIATE).

Example:
  python manage.py seed_demo_tenant --vertical=skincare --reset
  python manage.py seed_demo_tenant --vertical=skincare --contacts=200 --reset
"""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from dataruns.demo_seed.constants import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_CONTACTS,
    DEFAULT_VERTICAL,
    SUPPORTED_VERTICALS,
)
from dataruns.demo_seed.identity import (
    assert_email_available_for_slug,
    create_demo_identity,
    demo_tenant_slug,
    ensure_stub_connectors,
    reset_demo_tenant,
)
from dataruns.demo_seed.offline_dcs import (
    REMEDIATE_MAX,
    REMEDIATE_MIN,
    run_offline_demo_dcs,
)
from dataruns.models import CheckMaster
from dataruns.use_cases.models import UseCasePilot


class Command(BaseCommand):
    help = (
        "Seed an offline demo tenant (GAP-01F). "
        "Creates Tenant/Company/admin, loads masters, stub connectors, "
        "skincare contact corpus, and offline DCS (no live OAuth/HTTP)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--vertical",
            default=DEFAULT_VERTICAL,
            help=f"Demo data profile (default: {DEFAULT_VERTICAL}). v1 supports: skincare.",
        )
        parser.add_argument(
            "--contacts",
            type=int,
            default=DEFAULT_CONTACTS,
            help=f"Contact corpus size (default: {DEFAULT_CONTACTS}).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo tenant slug before seeding.",
        )
        parser.add_argument(
            "--slug",
            default="",
            help=f"Tenant slug override (default: {demo_tenant_slug(DEFAULT_VERTICAL)}).",
        )
        parser.add_argument(
            "--email",
            default=DEFAULT_ADMIN_EMAIL,
            help=f"Admin email (default: {DEFAULT_ADMIN_EMAIL}).",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_ADMIN_PASSWORD,
            help="Admin password (default: DemoPass123!).",
        )
        parser.add_argument(
            "--skip-masters",
            action="store_true",
            help="Skip seed_dcs_master + load_use_case_pilots (dev only).",
        )
        parser.add_argument(
            "--skip-dcs",
            action="store_true",
            help="Skip contact corpus + offline DCS (Phase 1 scaffold only).",
        )
        parser.add_argument(
            "--require-remediate",
            action="store_true",
            help=(
                f"Exit non-zero if headline not in REMEDIATE "
                f"[{REMEDIATE_MIN:.0f}, {REMEDIATE_MAX:.0f}]."
            ),
        )

    def handle(self, *args, **options):
        vertical = str(options["vertical"] or DEFAULT_VERTICAL).strip().lower()
        if vertical not in SUPPORTED_VERTICALS:
            raise CommandError(
                f"Unsupported --vertical={vertical!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_VERTICALS))}."
            )

        contacts = int(options["contacts"])
        if contacts < 1:
            raise CommandError("--contacts must be >= 1")

        slug = (options.get("slug") or "").strip() or demo_tenant_slug(vertical)
        email = (options.get("email") or DEFAULT_ADMIN_EMAIL).strip()
        password = options.get("password") or DEFAULT_ADMIN_PASSWORD
        do_reset = bool(options["reset"])
        skip_masters = bool(options["skip_masters"])
        skip_dcs = bool(options["skip_dcs"])
        require_remediate = bool(options["require_remediate"])

        if require_remediate and skip_dcs:
            raise CommandError(
                "--require-remediate cannot be combined with --skip-dcs "
                "(no headline to verify)."
            )

        try:
            assert_email_available_for_slug(email=email, slug=slug)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        did_reset = False
        if do_reset:
            did_reset = reset_demo_tenant(slug=slug)
            if did_reset:
                self.stdout.write(
                    f"Reset: retired existing tenant slug={slug} "
                    "(audit_logs are append-only — tenant deactivated/renamed, not hard-deleted)"
                )
            else:
                self.stdout.write(f"Reset: no existing tenant slug={slug}")

        try:
            identity = create_demo_identity(
                vertical=vertical,
                slug=slug,
                email=email,
                password=password,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        connectors = ensure_stub_connectors(
            company=identity.company,
            vertical=vertical,
        )

        if not skip_masters:
            self.stdout.write("Loading use-case pilots...")
            call_command("load_use_case_pilots", verbosity=1)
            self.stdout.write("Seeding DCS master tables...")
            call_command("seed_dcs_master", verbosity=1)
        else:
            self.stdout.write(
                self.style.WARNING("Skipping masters (--skip-masters)")
            )

        check_count = CheckMaster.objects.count()
        pilot_count = UseCasePilot.objects.count()
        if check_count == 0:
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: CheckMaster is empty - run without --skip-masters "
                    "or seed_dcs_master before DCS."
                )
            )
        if pilot_count == 0:
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: UseCasePilot is empty - run without --skip-masters "
                    "or load_use_case_pilots before Studio demo path."
                )
            )

        dcs_result = None
        if skip_dcs:
            self.stdout.write(
                self.style.WARNING("Skipping corpus + DCS (--skip-dcs)")
            )
        else:
            if check_count == 0:
                raise CommandError(
                    "Cannot run offline DCS with empty CheckMaster. "
                    "Re-run without --skip-masters."
                )
            self.stdout.write(
                f"Seeding skincare corpus ({contacts} contacts) + offline DCS..."
            )
            dcs_result = run_offline_demo_dcs(
                company=identity.company,
                contacts=contacts,
            )
            if not dcs_result.ok:
                raise CommandError(f"Offline DCS failed: {dcs_result.detail}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== GAP-01F seed_demo_tenant ==="))
        self.stdout.write(f"vertical:     {vertical}")
        self.stdout.write(f"contacts:     {contacts}")
        self.stdout.write(f"reset:        requested={do_reset} deleted={did_reset}")
        self.stdout.write(f"tenant:       {identity.tenant.name} ({identity.tenant.slug})")
        self.stdout.write(f"company:      {identity.company.name} ({identity.company.id})")
        self.stdout.write(f"email:        {identity.user.email}")
        self.stdout.write(
            "password:     (set — not printed; default DemoPass123! or --password)"
        )
        self.stdout.write(
            "connectors:   "
            + ", ".join(f"{c.name}={c.status}" for c in connectors)
            + " (demo stubs - not live OAuth)"
        )
        self.stdout.write(f"check_master: {check_count} rows")
        self.stdout.write(f"pilots:       {pilot_count} rows")
        if dcs_result is not None:
            self.stdout.write(f"dcs_run_id:   {dcs_result.data_run_id}")
            self.stdout.write(f"headline:     {dcs_result.headline_score}")
            self.stdout.write(f"run_state:    {dcs_result.run_state}")
            self.stdout.write(f"db_contacts:  {dcs_result.contact_count}")
            self.stdout.write(
                f"corpus mix:   matched={dcs_result.corpus.matched_count} "
                f"shopify_only={dcs_result.corpus.shopify_only_count} "
                f"manago_only={dcs_result.corpus.manago_only_count} "
                f"mismatch={dcs_result.corpus.mismatch_count} "
                f"manago_dup={dcs_result.corpus.manago_dup_count}"
            )
            band = (
                f"REMEDIATE [{REMEDIATE_MIN:.0f},{REMEDIATE_MAX:.0f}]"
            )
            if dcs_result.in_remediate_band:
                self.stdout.write(self.style.SUCCESS(f"band:         {band} OK"))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"band:         NOT in {band} (target, not hard AC unless "
                        f"--require-remediate) - {dcs_result.detail}"
                    )
                )
                if require_remediate:
                    raise CommandError(
                        f"Headline {dcs_result.headline_score} not in {band}."
                    )
        self.stdout.write("")
        self.stdout.write(
            "Honesty: stub connectors + offline DCS - no live Shopify/Manago HTTP. "
            "Do not claim webhook latency or live sync health from this seed."
        )
