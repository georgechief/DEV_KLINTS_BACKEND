from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.m3_obs import INDUCE_MARKER
from core.tasks import health_check, ping
from dataruns.models import DataRun
from dataruns.tasks import process_data_run
from tenants.models import Tenant


class HealthCheckTests(SimpleTestCase):
    def test_health_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class M3ObsInduceErrorTests(SimpleTestCase):
    def test_disabled_returns_404(self):
        response = self.client.post(reverse("m3_obs_induce_error"))
        self.assertEqual(response.status_code, 404)

    @override_settings(M3_OBS_INDUCE_ENABLED=True, M3_OBS_INDUCE_TOKEN="test-token-obs")
    def test_wrong_token_forbidden(self):
        response = self.client.post(
            reverse("m3_obs_induce_error"),
            HTTP_X_M3_OBS_INDUCE_TOKEN="nope",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(M3_OBS_INDUCE_ENABLED=True, M3_OBS_INDUCE_TOKEN="test-token-obs")
    def test_ok_with_token(self):
        response = self.client.post(
            reverse("m3_obs_induce_error"),
            HTTP_X_M3_OBS_INDUCE_TOKEN="test-token-obs",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["marker"], INDUCE_MARKER)


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
