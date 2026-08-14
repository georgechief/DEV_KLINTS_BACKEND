from django.test import TestCase

from dataruns.models import DataRun
from tenants.models import Tenant


class DataRunModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")

    def test_create_data_run(self):
        run = DataRun.objects.create(tenant=self.tenant, name="ingest-1")
        self.assertEqual(run.status, DataRun.Status.PENDING)
        self.assertEqual(str(run), "ingest-1 (pending)")
