from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.tasks import health_check, ping
from dataruns.models import DataRun
from dataruns.tasks import process_data_run
from tenants.models import Tenant


class HealthCheckTests(SimpleTestCase):
    def test_health_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class CeleryTaskTests(TestCase):
    def test_ping(self):
        result = ping.delay().get()
        self.assertEqual(result["status"], "pong")

    def test_health_check(self):
        result = health_check.delay().get()
        self.assertEqual(result["status"], "ok")

    def test_process_data_run(self):
        tenant = Tenant.objects.create(name="Acme", slug="acme")
        run = DataRun.objects.create(tenant=tenant, name="ingest-1")
        result = process_data_run.delay(run.id).get()
        run.refresh_from_db()
        self.assertTrue(result["ok"])
        self.assertEqual(run.status, DataRun.Status.SUCCEEDED)
