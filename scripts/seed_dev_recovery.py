"""One-time dev recovery: tenant + admin user + pilots + DCS master."""
from __future__ import annotations

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")
django.setup()

from django.core.management import call_command
from django.db import transaction

from tenants.models import Company, Tenant, User

EMAIL = "admin@klints.local"
PASSWORD = "TestPass123!"
TENANT_NAME = "Klints Dev"
COMPANY_NAME = "Klints Dev Co"
COMPANY_DOMAIN = "klints.dev"


def main() -> int:
    if User.objects.filter(email__iexact=EMAIL).exists():
        print(f"User {EMAIL} already exists — skipping user create")
    else:
        with transaction.atomic():
            tenant = Tenant.objects.create(name=TENANT_NAME, slug="klints-dev")
            Company.objects.create(
                tenant=tenant,
                name=COMPANY_NAME,
                domain=COMPANY_DOMAIN,
            )
            user = User.objects.create_user(
                email=EMAIL,
                password=PASSWORD,
                name="Admin",
                tenant=tenant,
                role=User.Role.ADMIN,
            )
            user.email_verified = True
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.save(
                update_fields=[
                    "email_verified",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "updated_at",
                ]
            )
        print(f"Created {EMAIL} (tenant={tenant.slug})")

    print("Loading use-case pilots...")
    call_command("load_use_case_pilots", verbosity=1)

    print("Seeding DCS master tables...")
    call_command("seed_dcs_master", verbosity=1)

    user = User.objects.get(email__iexact=EMAIL)
    company = Company.objects.filter(tenant_id=user.tenant_id).first()
    print("\n=== Recovery complete ===")
    print(f"Email:    {EMAIL}")
    print(f"Password: {PASSWORD}")
    print(f"Tenant:   {user.tenant.name} ({user.tenant.slug})")
    print(f"Company:  {company.name if company else '—'}")
    print(f"Users:    {User.objects.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
