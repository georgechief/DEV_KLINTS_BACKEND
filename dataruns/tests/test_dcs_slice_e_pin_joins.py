"""DCS-10 Slice E — pin snapshot joins to this run's import DataRun."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from django.test import TestCase

from dataruns.connectors.base import CONNECTOR_FETCH_KIND
from dataruns.dcs.consent_join import build_consent_snapshot
from dataruns.dcs.lifecycle_join import (
    _connector_raw_for_import_data_run,
    _connector_raw_for_platform,
    build_lifecycle_snapshot,
)
from dataruns.dcs.snapshot import build_dcs_run_snapshot
from dataruns.models import DataRun, Run, RunConnector
from tenants.models import Company, Connector, ConnectorSnapshot, Tenant


class SliceEPinJoinTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Pin Co", slug="pin-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Pin Co",
            domain="pin.co",
        )
        self.connector = Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            config={"shop_domain": "pin.myshopify.com"},
            status="connected",
        )
        self.latest_snapshot = ConnectorSnapshot.objects.create(
            connector=self.connector,
            version=2,
            snapshot_data={
                "raw": {
                    "orders": [{"id": 999, "test": False, "financial_status": "paid"}],
                },
            },
        )
        self.pinned_snapshot = ConnectorSnapshot.objects.create(
            connector=self.connector,
            version=1,
            snapshot_data={
                "raw": {
                    "orders": [{"id": 101, "test": False, "financial_status": "paid"}],
                },
            },
        )
        self.pinned_data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:shopify",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
                "snapshot_id": str(self.pinned_snapshot.id),
            },
        )

    def test_connector_raw_for_import_data_run_reads_snapshot_id(self):
        raw = _connector_raw_for_import_data_run(self.pinned_data_run.id)
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertEqual(raw["orders"][0]["id"], 101)

    def test_connector_raw_for_platform_pins_not_latest(self):
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            source_run_id=self.pinned_data_run.id,
        )
        self.assertEqual(raw["orders"][0]["id"], 101)

    def test_connector_raw_for_platform_falls_back_to_latest_without_pin(self):
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            source_run_id=None,
        )
        self.assertEqual(raw["orders"][0]["id"], 999)

    def test_connector_raw_for_platform_falls_back_when_data_run_missing(self):
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            source_run_id=999_999,
        )
        self.assertEqual(raw["orders"][0]["id"], 999)

    def test_connector_raw_for_platform_rejects_wrong_platform(self):
        manago_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:manago_ai",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "manago_ai",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
                "snapshot_id": str(self.pinned_snapshot.id),
            },
        )
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            source_run_id=manago_run.id,
        )
        self.assertEqual(raw["orders"][0]["id"], 999)

    def test_connector_raw_for_platform_falls_back_when_snapshot_unresolvable(self):
        orphan_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:shopify",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
            },
        )
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            source_run_id=orphan_run.id,
        )
        self.assertEqual(raw["orders"][0]["id"], 999)

    def test_connector_raw_for_platform_prefers_snapshot_id(self):
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            snapshot_id=str(self.pinned_snapshot.id),
        )
        self.assertEqual(raw["orders"][0]["id"], 101)

    def test_connector_raw_for_import_data_run_via_run_id(self):
        domain_run = Run.objects.create(
            company=self.company,
            run_type="incremental",
            status="completed",
        )
        RunConnector.objects.create(
            run=domain_run,
            connector_snapshot=self.pinned_snapshot,
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:shopify",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
                "run_id": str(domain_run.id),
            },
        )
        raw = _connector_raw_for_import_data_run(
            data_run.id,
            company=self.company,
            platform="shopify",
        )
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertEqual(raw["orders"][0]["id"], 101)

    def test_connector_raw_for_platform_rejects_wrong_connector_snapshot_id(self):
        manago_connector = Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            config={},
            status="connected",
        )
        manago_snapshot = ConnectorSnapshot.objects.create(
            connector=manago_connector,
            version=1,
            snapshot_data={
                "raw": {
                    "contacts": [{"contactId": "m1", "email": "m@example.com"}],
                },
            },
        )
        raw = _connector_raw_for_platform(
            company=self.company,
            platform="shopify",
            snapshot_id=str(manago_snapshot.id),
        )
        self.assertEqual(raw["orders"][0]["id"], 999)

    def test_build_consent_snapshot_uses_pinned_shopify_raw(self):
        unpinned = build_consent_snapshot(company=self.company)
        unpinned_raw = (unpinned.get("consent") or {}).get("raw_enrichment") or {}
        self.assertFalse(unpinned_raw.get("shopify_customers_from_raw"))

        pinned_snapshot = ConnectorSnapshot.objects.create(
            connector=self.connector,
            version=3,
            snapshot_data={
                "raw": {
                    "customers": [{"id": 1, "email": "pinned@example.com"}],
                },
            },
        )
        data_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-fresh-import:shopify",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_FETCH_KIND,
                "platform": "shopify",
                "company_id": str(self.company.id),
                "triggered_by": "dcs_score",
                "snapshot_id": str(pinned_snapshot.id),
            },
        )
        pinned = build_consent_snapshot(
            company=self.company,
            source_run_ids={"shopify": data_run.id, "manago_ai": None},
        )
        pinned_raw = (pinned.get("consent") or {}).get("raw_enrichment") or {}
        self.assertTrue(pinned_raw.get("shopify_customers_from_raw"))

    def test_build_lifecycle_snapshot_uses_pinned_shopify_orders(self):
        payload = build_lifecycle_snapshot(
            company=self.company,
            source_run_ids={"shopify": self.pinned_data_run.id, "manago_ai": None},
        )
        paid = payload.get("orders") or []
        order_ids = {row.get("order.id") for row in paid}
        self.assertIn("101", order_ids)

    def test_build_dcs_run_snapshot_passes_source_run_ids_to_joins(self):
        company_id = uuid.uuid4()
        company = type("Co", (), {"id": company_id})()
        with patch(
            "dataruns.dcs.snapshot.build_lifecycle_snapshot",
        ) as mock_lifecycle:
            mock_lifecycle.return_value = {
                "events": [],
                "orders": [],
                "lifecycle": {
                    "shopify_paid_orders": 0,
                    "manago_purchase_events": 0,
                    "manago_return_cancel_events": 0,
                    "raw_enrichment": {},
                },
            }
            with patch("dataruns.dcs.snapshot.build_identity_snapshot", return_value={"identity": {}, "contacts": [], "orders": []}):
                with patch("dataruns.dcs.snapshot.build_consent_snapshot", return_value={"consent": {}, "consent_rows": []}):
                    with patch("dataruns.dcs.snapshot.build_product_truth_snapshot", return_value={"product_truth": {}, "product_truth_rows": []}):
                        with patch("dataruns.dcs.snapshot.build_catalog_snapshot", return_value={"catalog": {}, "products": []}):
                            with patch("dataruns.dcs.snapshot.build_segment_snapshot", return_value={"segment": {}, "segments": [], "details": []}):
                                with patch("dataruns.dcs.snapshot.build_workflow_snapshot", return_value={"measurement": {}, "workflows": []}):
                                    with patch("dataruns.dcs.snapshot.build_drift_snapshot", return_value={"drift": {}}):
                                        with patch("dataruns.dcs.snapshot._gate_inputs_from_import", return_value={}):
                                            with patch("dataruns.dcs.snapshot._connector_status", return_value={"status": "connected", "scopes": []}):
                                                with patch("dataruns.dcs.snapshot.Contact.objects") as contact_qs:
                                                    with patch("dataruns.dcs.snapshot.Order.objects") as order_qs:
                                                        contact_qs.filter.return_value.count.return_value = 0
                                                        order_qs.filter.return_value.count.return_value = 0
                                                        build_dcs_run_snapshot(
                                                            company=company,
                                                            source_runs={
                                                                "shopify": 101,
                                                                "manago_ai": 202,
                                                            },
                                                            fresh_imports={
                                                                "shopify": {
                                                                    "snapshot_id": "snap-shop",
                                                                },
                                                                "manago_ai": {
                                                                    "snapshot_id": "snap-man",
                                                                },
                                                            },
                                                        )
        mock_lifecycle.assert_called_once_with(
            company=company,
            source_run_ids={"shopify": 101, "manago_ai": 202},
            pinned_snapshot_ids={
                "shopify": "snap-shop",
                "manago_ai": "snap-man",
            },
        )
