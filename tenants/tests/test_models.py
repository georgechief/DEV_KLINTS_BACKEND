from django.test import TestCase

from tenants.models import Tenant


class TenantModelTests(TestCase):
    def test_create_tenant(self):
        tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.assertEqual(str(tenant), "Acme")
        self.assertTrue(tenant.is_active)
