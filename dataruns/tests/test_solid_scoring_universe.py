"""Solid scoring universe — pins, Contact tombstone, LE-09 thin-fetch."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from dataruns.dcs.contact_sync import (
    snapshot_has_contact_surface,
    sync_contacts_to_snapshot,
)
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME, DCS_SCORE_KIND
from dataruns.dcs.executors.foundation import FoundationGateContext
from dataruns.dcs.executors.lifecycle import evaluate_le_09
from dataruns.dcs.identity_join import build_identity_snapshot
from dataruns.dcs.pins import resolve_scoring_pins
from dataruns.models import Contact, DataRun
from tenants.models import Company, Tenant


class PinsResolverTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PinT", slug="pin-solid")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Pin Co", domain="pin-solid.test"
        )

    def test_resolve_from_latest_dcs_metadata(self):
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "source_runs": {"shopify": 101, "manago_ai": 102},
                "fresh_imports": {
                    "shopify": {"snapshot_id": "snap-s"},
                    "manago_ai": {"snapshot_id": "snap-m"},
                },
            },
        )
        source_runs, snaps, run = resolve_scoring_pins(company=self.company)
        self.assertIsNotNone(run)
        self.assertEqual(source_runs["shopify"], 101)
        self.assertEqual(snaps["manago_ai"], "snap-m")

    def test_prefers_succeeded_over_newer_failed(self):
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "source_runs": {"shopify": 1, "manago_ai": 2},
                "fresh_imports": {
                    "shopify": {"snapshot_id": "good-s"},
                    "manago_ai": {"snapshot_id": "good-m"},
                },
            },
        )
        DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.FAILED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "source_runs": {},
                "fresh_imports": {},
            },
        )
        _sr, snaps, run = resolve_scoring_pins(company=self.company)
        self.assertEqual(run.status, DataRun.Status.SUCCEEDED)
        self.assertEqual(snaps["shopify"], "good-s")


class ContactTombstoneTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="TombT", slug="tomb-solid")
        self.company = Company.objects.create(
            tenant=self.tenant, name="Tomb Co", domain="tomb-solid.test"
        )

    def test_sync_tombstones_ghosts_and_identity_skips(self):
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="live-1",
            email="a@x.com",
        )
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="ghost-1",
            email="g@x.com",
        )
        snap = {
            "raw": {
                "contacts": [
                    {
                        "id": "live-1",
                        "email": "a@x.com",
                        "externalId": "",
                    }
                ]
            }
        }
        result = sync_contacts_to_snapshot(
            company=self.company,
            platform="manago_ai",
            snapshot_data=snap,
        )
        self.assertEqual(result["tombstoned"], 1)
        self.assertEqual(result.get("skipped"), 0)
        ghost = Contact.objects.get(external_id="ghost-1")
        self.assertTrue(ghost.excluded)
        live = Contact.objects.get(external_id="live-1")
        self.assertFalse(live.excluded)

        identity = build_identity_snapshot(company=self.company)["identity"]
        if (identity.get("contacts_source") or {}).get("manago_ai") == "db":
            self.assertEqual(identity.get("manago_contacts"), 1)

    def test_empty_dict_snapshot_does_not_wipe(self):
        Contact.objects.create(
            company=self.company,
            source="manago_ai",
            external_id="keep-me",
            email="k@x.com",
        )
        self.assertFalse(
            snapshot_has_contact_surface(snapshot_data={}, platform="manago_ai")
        )
        result = sync_contacts_to_snapshot(
            company=self.company,
            platform="manago_ai",
            snapshot_data={},
        )
        self.assertEqual(result.get("skipped"), 1)
        self.assertEqual(result["tombstoned"], 0)
        self.assertFalse(Contact.objects.get(external_id="keep-me").excluded)


class Le09ThinFetchTests(SimpleTestCase):
    def test_thin_events_yield_unknown_not_fail(self):
        snapshot = {
            "connectors": {
                "shopify": {"status": "connected"},
                "manago_ai": {"status": "connected"},
            },
            "lifecycle": {
                "shopify_refund_cancel_orders": 85,
                "manago_return_cancel_events": 81,
                "return_coverage": {
                    "shopify_only_returns_count": 4,
                    "manago_only_returns_count": 0,
                    "shopify_only_returns": ["1", "2", "3", "4"],
                    "manago_only_returns": [],
                    "return_value_delta": 0.04,
                    "shopify_return_value": 100.0,
                    "shopify_only_returns_value": 10.0,
                    "manago_return_value": 90.0,
                },
                "raw_enrichment": {
                    "events_thin_vs_prior": True,
                    "manago_return_events_current": 81,
                    "manago_return_events_prior": 85,
                    "return_events_from_raw": True,
                },
            },
        }
        ctx = FoundationGateContext(
            tenant_id="t1",
            run_id="r1",
            evaluated_at="2026-09-24T12:00:00Z",
            extra={"scoring_snapshot": snapshot},
        )
        result = evaluate_le_09(ctx)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "INCOMPLETE_FETCH:events")
