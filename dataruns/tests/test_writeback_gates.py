"""Writeback gate tests (PRD-WB-01 §5.2)."""

from django.test import TestCase, override_settings

from dataruns.writebacks.gates import execute_allowed, is_sandbox_company
from tenants.models import Company, Tenant


class WritebackGatesTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="T", slug="t")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Sandbox Co",
            domain="sandbox.test",
        )

    @override_settings(
        WRITEBACK_SANDBOX_COMPANY_IDS=[],
        WRITEBACK_CHECK_ALLOWLIST=["CI-01"],
        WRITEBACKS_ENABLED=False,
    )
    def test_non_sandbox_execute_denied(self):
        allowed, reason = execute_allowed(company=self.company, check_id="CI-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "writebacks_disabled")

    @override_settings(
        WRITEBACK_CHECK_ALLOWLIST=["CI-01"],
        WRITEBACKS_ENABLED=False,
    )
    def test_sandbox_company_allowed_when_listed(self):
        company_id = str(self.company.id)
        with self.settings(WRITEBACK_SANDBOX_COMPANY_IDS=[company_id]):
            self.assertTrue(is_sandbox_company(self.company))
            allowed, reason = execute_allowed(company=self.company, check_id="CI-01")
            self.assertTrue(allowed)
            self.assertIsNone(reason)

    @override_settings(
        WRITEBACK_SANDBOX_COMPANY_IDS=[],
        WRITEBACK_CHECK_ALLOWLIST=[],
        WRITEBACKS_ENABLED=False,
    )
    def test_check_not_on_allowlist_denied(self):
        allowed, reason = execute_allowed(company=self.company, check_id="CI-01")
        self.assertFalse(allowed)
        self.assertEqual(reason, "check_not_allowlisted")
