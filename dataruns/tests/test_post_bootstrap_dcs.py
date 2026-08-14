"""Tests for post-bootstrap DCS enqueue when both connectors are ready."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from dataruns.connectors.base import CONNECTOR_BOOTSTRAP_KIND
from dataruns.dcs.enqueue import (
    maybe_enqueue_dcs_after_bootstrap,
    company_has_both_commerce_connectors,
)
from dataruns.models import DataRun
from tenants.models import Company, Connector, Tenant


class PostBootstrapDcsEnqueueTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Dual Co", slug="dual-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Dual Co",
            domain="dual.example",
        )

    def _connect(self, name: str) -> Connector:
        return Connector.objects.create(
            company=self.company,
            name=name,
            type="ecommerce" if name == "shopify" else "cdp",
            status="connected",
            config={},
        )

    def _succeeded_bootstrap(self, connector: Connector) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=f"connector-bootstrap:{connector.name}",
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": CONNECTOR_BOOTSTRAP_KIND,
                "platform": connector.name,
                "connector_id": str(connector.id),
                "company_id": str(self.company.id),
                "days": 30,
            },
        )

    def test_both_connectors_helper(self):
        self.assertFalse(company_has_both_commerce_connectors(self.company))
        self._connect("shopify")
        self.assertFalse(company_has_both_commerce_connectors(self.company))
        self._connect("manago_ai")
        self.assertTrue(company_has_both_commerce_connectors(self.company))

    @patch("dataruns.dcs.enqueue.enqueue_dcs_score")
    def test_skips_when_only_one_connector(self, mock_enqueue):
        shopify = self._connect("shopify")
        self._succeeded_bootstrap(shopify)
        result = maybe_enqueue_dcs_after_bootstrap(self.company)
        self.assertIsNone(result)
        mock_enqueue.assert_not_called()

    @patch("dataruns.dcs.enqueue.enqueue_dcs_score")
    def test_skips_when_second_bootstrap_missing(self, mock_enqueue):
        shopify = self._connect("shopify")
        self._connect("manago_ai")
        self._succeeded_bootstrap(shopify)
        result = maybe_enqueue_dcs_after_bootstrap(self.company)
        self.assertIsNone(result)
        mock_enqueue.assert_not_called()

    @patch("tenants.manago_topology_service.ensure_manago_primary_owner")
    @patch("dataruns.dcs.enqueue.enqueue_dcs_score")
    def test_enqueues_when_both_bootstraps_succeeded(self, mock_enqueue, mock_ensure):
        shopify = self._connect("shopify")
        manago = self._connect("manago_ai")
        self._succeeded_bootstrap(shopify)
        self._succeeded_bootstrap(manago)

        mock_enqueue.return_value = object()
        result = maybe_enqueue_dcs_after_bootstrap(self.company)
        self.assertIsNotNone(result)
        mock_ensure.assert_called_once_with(self.company, allow_multi_owner_inference=True)
        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs.get("triggered_by"), "post_bootstrap")
        self.assertTrue(kwargs.get("queue"))
