"""GAP-01F Phase 1 — seed_demo_tenant scaffold honesty tests."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from dataruns.connectors.base import decrypt_connector_config, get_connector
from dataruns.demo_seed.constants import DEMO_SEED_CONFIG_MARKER
from dataruns.demo_seed.identity import assert_email_available_for_slug
from tenants.models import Company, Connector, Tenant, User


class SeedDemoTenantPhase1Tests(TestCase):
    def test_assert_email_blocks_foreign_tenant_before_reset(self):
        other = Tenant.objects.create(name="Other", slug="other-co")
        User.objects.create_user(
            email="taken@example.com",
            password="TestPass123!",
            name="Taken",
            tenant=other,
            role=User.Role.ADMIN,
        )
        with self.assertRaises(ValueError) as ctx:
            assert_email_available_for_slug(
                email="taken@example.com",
                slug="klints-demo-skincare",
            )
        self.assertIn("other-co", str(ctx.exception))
        self.assertIn("--reset only retires slug", str(ctx.exception))

    def test_seed_creates_identity_stubs_and_refuses_without_reset(self):
        out = StringIO()
        call_command(
            "seed_demo_tenant",
            "--vertical=skincare",
            "--slug=gap01f-test-demo",
            "--email=gap01f-test@example.com",
            "--password=TestPass123!",
            "--skip-masters",
            "--skip-dcs",
            stdout=out,
        )
        tenant = Tenant.objects.get(slug="gap01f-test-demo")
        company = Company.objects.get(tenant=tenant)
        user = User.objects.get(email__iexact="gap01f-test@example.com")
        self.assertEqual(user.tenant_id, tenant.id)
        self.assertTrue(user.check_password("TestPass123!"))
        self.assertTrue(user.email_verified)
        self.assertEqual(user.role, User.Role.ADMIN)

        shopify = get_connector(company=company, platform="shopify")
        manago = get_connector(company=company, platform="manago_ai")
        self.assertEqual(shopify.status, "connected")
        self.assertEqual(manago.status, "connected")
        self.assertEqual(shopify.type, "ecommerce")
        self.assertEqual(manago.type, "cdp")
        shop_cfg = decrypt_connector_config(shopify.config)
        manago_cfg = decrypt_connector_config(manago.config)
        self.assertTrue(shop_cfg.get(DEMO_SEED_CONFIG_MARKER))
        self.assertTrue(manago_cfg.get(DEMO_SEED_CONFIG_MARKER))
        self.assertEqual(shop_cfg.get("vertical"), "skincare")

        with self.assertRaises(CommandError) as ctx:
            call_command(
                "seed_demo_tenant",
                "--vertical=skincare",
                "--slug=gap01f-test-demo",
                "--email=gap01f-test@example.com",
                "--skip-masters",
                "--skip-dcs",
            )
        self.assertIn("--reset", str(ctx.exception))

        # Foreign email + --reset must fail *before* deleting the demo slug.
        other = Tenant.objects.create(name="Other2", slug="other-2")
        User.objects.create_user(
            email="foreign@example.com",
            password="TestPass123!",
            name="Foreign",
            tenant=other,
            role=User.Role.ADMIN,
        )
        with self.assertRaises(CommandError) as ctx2:
            call_command(
                "seed_demo_tenant",
                "--vertical=skincare",
                "--slug=gap01f-test-demo",
                "--email=foreign@example.com",
                "--reset",
                "--skip-masters",
                "--skip-dcs",
            )
        self.assertIn("other-2", str(ctx2.exception))
        self.assertTrue(Tenant.objects.filter(slug="gap01f-test-demo").exists())
        self.assertEqual(Connector.objects.filter(company=company).count(), 2)

        # --reset with same-tenant email recreates cleanly.
        call_command(
            "seed_demo_tenant",
            "--vertical=skincare",
            "--slug=gap01f-test-demo",
            "--email=gap01f-test@example.com",
            "--password=TestPass123!",
            "--reset",
            "--skip-masters",
            "--skip-dcs",
            stdout=StringIO(),
        )
        self.assertTrue(Tenant.objects.filter(slug="gap01f-test-demo").exists())
        self.assertTrue(
            User.objects.filter(email__iexact="gap01f-test@example.com").exists()
        )

    def test_reset_retires_tenant_when_audit_logs_exist(self):
        """F0.6: --reset must work even though audit_logs cannot be DELETE'd."""
        from dataruns.audit import append_audit_event

        out = StringIO()
        call_command(
            "seed_demo_tenant",
            "--vertical=skincare",
            "--slug=gap01f-audit-reset",
            "--email=gap01f-audit-reset@example.com",
            "--password=TestPass123!",
            "--skip-masters",
            "--skip-dcs",
            stdout=out,
        )
        tenant = Tenant.objects.get(slug="gap01f-audit-reset")
        company = Company.objects.get(tenant=tenant)
        append_audit_event(
            company=company,
            action="gap01f.demo_seed",
            summary="demo audit row",
            performed_by="gap01f-test",
        )
        call_command(
            "seed_demo_tenant",
            "--vertical=skincare",
            "--slug=gap01f-audit-reset",
            "--email=gap01f-audit-reset@example.com",
            "--password=TestPass123!",
            "--reset",
            "--skip-masters",
            "--skip-dcs",
            stdout=StringIO(),
        )
        self.assertTrue(Tenant.objects.filter(slug="gap01f-audit-reset").exists())
        self.assertTrue(
            Tenant.objects.filter(slug__startswith="gap01f-audit-reset-retired-").exists()
        )
        self.assertTrue(
            User.objects.filter(email__iexact="gap01f-audit-reset@example.com").exists()
        )
        retired = Tenant.objects.get(slug__startswith="gap01f-audit-reset-retired-")
        self.assertFalse(retired.is_active)