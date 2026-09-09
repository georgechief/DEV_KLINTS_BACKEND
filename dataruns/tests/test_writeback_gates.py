"""Writeback gate tests (PRD-WB-01 §5.2, WB-03 approval harden)."""

from django.test import TestCase, override_settings

from dataruns.tests.writeback_helpers import clear_writeback_allowlist, seed_writeback_allowlist
from dataruns.writebacks.gates import execute_allowed, is_writeback_execute_enabled
from tenants.models import Company, Tenant


class WritebackGatesTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="T", slug="t")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Sandbox Co",
            domain="sandbox.test",
        )

    @override_settings(WRITEBACKS_ENABLED=False)
    def test_execute_disabled_when_company_flag_off(self):
        seed_writeback_allowlist("CI-01")
        self.company.writeback_execute_enabled = False
        self.company.save(update_fields=["writeback_execute_enabled"])
        allowed, reason = execute_allowed(company=self.company, check_id="CI-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    @override_settings(WRITEBACKS_ENABLED=False)
    def test_company_flag_on_requires_approval_id(self):
        seed_writeback_allowlist("CI-01")
        self.company.writeback_execute_enabled = True
        self.company.save(update_fields=["writeback_execute_enabled"])
        self.assertTrue(is_writeback_execute_enabled(self.company))
        allowed, reason = execute_allowed(company=self.company, check_id="CI-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "approval_id_required")

    @override_settings(WRITEBACKS_ENABLED=False)
    def test_check_not_on_allowlist_denied(self):
        clear_writeback_allowlist()
        allowed, reason = execute_allowed(company=self.company, check_id="CI-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "check_not_allowlisted")
