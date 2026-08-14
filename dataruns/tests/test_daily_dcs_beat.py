from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import TestCase
from django_celery_beat.models import PeriodicTask
from django_celery_beat.schedulers import ModelEntry
from django_celery_beat.tzcrontab import TzAwareCrontab

from dataruns.dcs.enqueue import (
    DAILY_BEAT_TRIGGER,
    DCS_SCORE_DATA_RUN_NAME,
    DCS_SCORE_KIND,
    DcsAlreadyRunningError,
    enqueue_dcs_score,
    has_daily_dcs_run_today,
)
from dataruns.models import DataRun
from dataruns.tasks import dispatch_daily_dcs_scores
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant

IST = ZoneInfo("Asia/Kolkata")
DCS_BEAT_SCHEDULE_KEY = "dcs-daily-score-1500-ist"


class DailyDcsBeatTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme",
            domain="acme.com",
        )
        self.other_tenant = Tenant.objects.create(name="Beta", slug="beta")
        self.other_company = Company.objects.create(
            tenant=self.other_tenant,
            name="Beta",
            domain="beta.com",
        )

    def _create_shopify_connector(self, company, *, status="connected"):
        connector = Connector.objects.create(
            company=company,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "acme.myshopify.com"},
            status=status,
        )
        ConnectorSnapshot.objects.create(
            connector=connector,
            version=1,
            snapshot_data={"shop_domain": "acme.myshopify.com", "shop_id": 42},
        )
        return connector

    def _dcs_beat_entry(self):
        return settings.CELERY_BEAT_SCHEDULE[DCS_BEAT_SCHEDULE_KEY]

    def test_beat_schedule_fires_at_1500_ist(self):
        entry = self._dcs_beat_entry()
        schedule = entry["schedule"]
        self.assertEqual(entry["task"], "dataruns.dispatch_daily_dcs_scores")
        self.assertIsInstance(schedule, TzAwareCrontab)
        self.assertEqual(schedule.hour, {15})
        self.assertEqual(schedule.minute, {0})
        self.assertEqual(schedule.tz, IST)

    def test_beat_schedule_is_due_at_1500_ist(self):
        schedule = self._dcs_beat_entry()["schedule"]
        last_run_at = datetime(2026, 7, 28, 15, 0, tzinfo=IST)

        schedule.nowfun = lambda: datetime(2026, 7, 29, 14, 59, tzinfo=IST)
        self.assertFalse(schedule.is_due(last_run_at).is_due)

        schedule.nowfun = lambda: datetime(2026, 7, 29, 15, 0, tzinfo=IST)
        self.assertTrue(schedule.is_due(last_run_at).is_due)

    def test_beat_schedule_syncs_to_django_celery_beat_admin(self):
        entry = self._dcs_beat_entry()
        ModelEntry.from_entry(DCS_BEAT_SCHEDULE_KEY, **entry)

        periodic_task = PeriodicTask.objects.get(name=DCS_BEAT_SCHEDULE_KEY)
        self.assertEqual(periodic_task.task, "dataruns.dispatch_daily_dcs_scores")
        self.assertTrue(periodic_task.enabled)
        crontab = periodic_task.crontab
        self.assertEqual(crontab.hour, "15")
        self.assertEqual(crontab.minute, "0")
        self.assertEqual(str(crontab.timezone), "Asia/Kolkata")

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_connected_shopify_company_enqueues_run_dcs_score(self, mock_delay):
        self._create_shopify_connector(self.company)

        result = enqueue_dcs_score(self.company, triggered_by=DAILY_BEAT_TRIGGER)

        self.assertFalse(result.skipped)
        self.assertTrue(result.task_queued)
        self.assertIsNotNone(result.data_run)
        mock_delay.assert_called_once_with(result.data_run.id)
        self.assertEqual(result.data_run.name, DCS_SCORE_DATA_RUN_NAME)
        self.assertEqual(result.data_run.status, DataRun.Status.PENDING)
        metadata = result.data_run.metadata
        self.assertEqual(metadata["kind"], DCS_SCORE_KIND)
        self.assertEqual(metadata["triggered_by"], DAILY_BEAT_TRIGGER)
        self.assertEqual(metadata["company_id"], str(self.company.id))

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_dispatch_daily_dcs_scores_enqueues_connected_shopify_company(self, mock_delay):
        self._create_shopify_connector(self.company)

        result = dispatch_daily_dcs_scores()

        self.assertEqual(result["eligible_companies"], 1)
        self.assertEqual(result["enqueued"], 1)
        self.assertEqual(result["skipped_already_ran"], 0)
        self.assertEqual(result["errors"], [])
        mock_delay.assert_called_once()

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_company_without_connectors_is_not_eligible(self, mock_delay):
        result = dispatch_daily_dcs_scores()

        self.assertEqual(result["eligible_companies"], 0)
        self.assertEqual(result["enqueued"], 0)
        mock_delay.assert_not_called()

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_second_dispatch_same_ist_day_skips_duplicate(self, mock_delay):
        self._create_shopify_connector(self.company)
        ist_moment = datetime(2026, 7, 29, 16, 0, tzinfo=IST)

        with patch("django.utils.timezone.now", return_value=ist_moment):
            first = enqueue_dcs_score(self.company, triggered_by=DAILY_BEAT_TRIGGER)
            second = enqueue_dcs_score(self.company, triggered_by=DAILY_BEAT_TRIGGER)

        self.assertFalse(first.skipped)
        self.assertTrue(second.skipped)
        self.assertEqual(second.skip_reason, "already_ran_today")
        mock_delay.assert_called_once()

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_dispatch_daily_dcs_scores_skips_second_run_same_ist_day(self, mock_delay):
        self._create_shopify_connector(self.company)
        ist_moment = datetime(2026, 7, 29, 16, 0, tzinfo=IST)

        with patch("django.utils.timezone.now", return_value=ist_moment):
            first = dispatch_daily_dcs_scores()
            second = dispatch_daily_dcs_scores()

        self.assertEqual(first["enqueued"], 1)
        self.assertEqual(second["enqueued"], 0)
        self.assertEqual(second["skipped_already_ran"], 1)
        mock_delay.assert_called_once()

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_one_company_error_does_not_block_others(self, mock_delay):
        from dataruns.dcs.enqueue import enqueue_dcs_score as real_enqueue

        self._create_shopify_connector(self.company)
        self._create_shopify_connector(self.other_company)

        def side_effect(company, *, triggered_by):
            if company.id == self.company.id:
                raise RuntimeError("boom")
            return real_enqueue(company, triggered_by=triggered_by)

        with patch("dataruns.dcs.enqueue.enqueue_dcs_score", side_effect=side_effect):
            result = dispatch_daily_dcs_scores()

        self.assertEqual(result["eligible_companies"], 2)
        self.assertEqual(result["enqueued"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["company_id"], str(self.company.id))

    @patch("dataruns.tasks.run_dcs_score.delay")
    def test_manual_trigger_works_independently_of_daily_idempotency(self, mock_delay):
        """Manual ignores IST daily skip; concurrent active runs still conflict."""
        self._create_shopify_connector(self.company)
        ist_moment = datetime(2026, 7, 29, 16, 0, tzinfo=IST)

        with patch("django.utils.timezone.now", return_value=ist_moment):
            daily = enqueue_dcs_score(self.company, triggered_by=DAILY_BEAT_TRIGGER)
            self.assertFalse(daily.skipped)
            assert daily.data_run is not None
            daily.data_run.status = DataRun.Status.SUCCEEDED
            daily.data_run.save(update_fields=["status", "updated_at"])

            skipped_daily = enqueue_dcs_score(
                self.company, triggered_by=DAILY_BEAT_TRIGGER
            )
            self.assertTrue(skipped_daily.skipped)
            self.assertEqual(skipped_daily.skip_reason, "already_ran_today")

            first_manual = enqueue_dcs_score(self.company, triggered_by="manual")
            self.assertFalse(first_manual.skipped)
            with self.assertRaises(DcsAlreadyRunningError):
                enqueue_dcs_score(self.company, triggered_by="manual")

        self.assertEqual(mock_delay.call_count, 2)

    def test_has_daily_dcs_run_today_ignores_failed_runs(self):
        self._create_shopify_connector(self.company)
        ist_moment = datetime(2026, 7, 29, 10, 0, tzinfo=IST)
        with patch("django.utils.timezone.now", return_value=ist_moment):
            DataRun.objects.create(
                tenant=self.tenant,
                name=DCS_SCORE_DATA_RUN_NAME,
                status=DataRun.Status.FAILED,
                metadata={
                    "kind": DCS_SCORE_KIND,
                    "triggered_by": DAILY_BEAT_TRIGGER,
                    "company_id": str(self.company.id),
                },
            )
            self.assertFalse(has_daily_dcs_run_today(self.company))

    def test_error_status_connector_is_not_eligible(self):
        self._create_shopify_connector(self.company, status="error")

        result = dispatch_daily_dcs_scores()

        self.assertEqual(result["eligible_companies"], 0)
