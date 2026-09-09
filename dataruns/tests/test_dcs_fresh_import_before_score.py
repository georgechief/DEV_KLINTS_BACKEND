"""PRD-DCS-10 — fresh import before DCS score (Steps 1–3)."""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from django.test import TestCase

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.fresh_import import (
    DcsFreshImportError,
    assert_fresh_imports_cover_connected,
    refresh_connected_platforms_for_dcs,
)
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.orchestrate import run_dcs_pipeline
from dataruns.dcs.status import resolve_dcs_app_status
from dataruns.models import DataRun
from tenants.crypto import encrypt_config
from tenants.models import Company, Connector, Tenant
from tenants.tests.bootstrap_test_helpers import successful_run_import_side_effect

_JSON_MASTER = load_check_master_from_json()


class DcsFreshImportFailClosedTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Fresh Import Co", slug="fresh-import")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Fresh Import Co",
            domain="fresh-import.test",
        )

    def test_no_connected_connectors_returns_empty_without_error(self):
        dcs_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-score",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
            },
        )
        result = refresh_connected_platforms_for_dcs(
            company=self.company,
            dcs_data_run=dcs_run,
            days=30,
        )
        self.assertEqual(result["fresh_imports"], {})
        self.assertIsNone(result["source_runs"]["shopify"])
        self.assertIsNone(result["source_runs"]["manago_ai"])

    def test_assert_raises_when_connected_platform_missing_from_fresh_imports(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config({"shop_domain": "demo.myshopify.com"}),
        )
        with self.assertRaises(DcsFreshImportError) as ctx:
            assert_fresh_imports_cover_connected(
                company=self.company,
                fresh_imports={},
            )
        self.assertEqual(ctx.exception.platform, "shopify")

    def test_assert_raises_when_data_run_id_is_null(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config({"shop_domain": "demo.myshopify.com"}),
        )
        with self.assertRaises(DcsFreshImportError) as ctx:
            assert_fresh_imports_cover_connected(
                company=self.company,
                fresh_imports={"shopify": {"data_run_id": None}},
            )
        self.assertEqual(ctx.exception.platform, "shopify")

    def test_assert_raises_when_only_one_of_two_connected_platforms_imported(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config({"shop_domain": "demo.myshopify.com"}),
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="connected",
            config=encrypt_config({"client_id": "c1", "api_secret": "s1"}),
        )
        with self.assertRaises(DcsFreshImportError) as ctx:
            assert_fresh_imports_cover_connected(
                company=self.company,
                fresh_imports={"shopify": {"data_run_id": 101}},
            )
        self.assertEqual(ctx.exception.platform, "manago_ai")

    def test_error_status_connector_not_required(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="error",
            config=encrypt_config({"shop_domain": "demo.myshopify.com"}),
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="connected",
            config=encrypt_config({"client_id": "c1", "api_secret": "s1"}),
        )
        assert_fresh_imports_cover_connected(
            company=self.company,
            fresh_imports={"manago_ai": {"data_run_id": 102}},
        )

    def test_assert_passes_when_both_connected_platforms_imported(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config({"shop_domain": "demo.myshopify.com"}),
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="degraded",
            config=encrypt_config({"client_id": "c1", "api_secret": "s1"}),
        )
        assert_fresh_imports_cover_connected(
            company=self.company,
            fresh_imports={
                "shopify": {"data_run_id": 101},
                "manago_ai": {"data_run_id": 102},
            },
        )

    @patch("dataruns.dcs.fresh_import.run_import")
    @patch("dataruns.dcs.fresh_import._ensure_shopify_token")
    @patch("dataruns.dcs.fresh_import.persist_health_report")
    @patch("dataruns.dcs.fresh_import.postflight_health", return_value=[])
    @patch("dataruns.dcs.fresh_import.load_snapshot_data", return_value={})
    @patch("dataruns.dcs.fresh_import.build_health_report", return_value={})
    def test_refresh_validates_successful_import_per_connected_platform(
        self,
        _mock_health,
        _mock_load_snap,
        _mock_postflight,
        _mock_persist_health,
        _mock_token,
        mock_run_import,
    ):
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="connected",
            config=encrypt_config({"client_id": "c1", "api_secret": "s1"}),
        )
        dcs_run = DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-score",
            status=DataRun.Status.RUNNING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
            },
        )

        def _fake_import(*, platform, company, data_run, days):
            return {
                "run_id": str(uuid.uuid4()),
                "snapshot_id": str(uuid.uuid4()),
                "counts": {"contacts": 1, "orders": 0},
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-28T00:00:00Z",
            }

        mock_run_import.side_effect = _fake_import

        result = refresh_connected_platforms_for_dcs(
            company=self.company,
            dcs_data_run=dcs_run,
            days=30,
        )
        self.assertIn("manago_ai", result["fresh_imports"])
        self.assertIsNotNone(result["fresh_imports"]["manago_ai"]["data_run_id"])
        mock_run_import.assert_called_once()

    @patch("dataruns.dcs.orchestrate._audit_dcs_failed")
    @patch("dataruns.dcs.orchestrate._notify_dcs_failed")
    @patch("dataruns.dcs.orchestrate.finalize_stage_progress_on_failure")
    @patch("dataruns.dcs.orchestrate.persist_import_stage_running")
    @patch("dataruns.dcs.orchestrate.resolve_company_from_data_run")
    @patch("dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs")
    @patch("tenants.manago_topology_service.ensure_manago_primary_owner")
    def test_pipeline_fails_when_refresh_returns_incomplete_fresh_imports(
        self,
        _mock_owner,
        mock_refresh,
        mock_resolve_company,
        _mock_import_progress,
        _mock_finalize_progress,
        _mock_notify_failed,
        _mock_audit_failed,
    ):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config({"shop_domain": "demo.myshopify.com"}),
        )
        mock_resolve_company.return_value = self.company
        mock_refresh.return_value = {
            "source_runs": {"shopify": None, "manago_ai": None},
            "fresh_imports": {},
            "window_days": 30,
        }

        domain_run = MagicMock()
        domain_run.id = uuid.uuid4()
        domain_run.status = "running"

        data_run = MagicMock()
        data_run.id = 77
        data_run.status = "pending"
        data_run.started_at = None
        data_run.run_snapshot = {}
        data_run.metadata = {
            "kind": DCS_SCORE_KIND,
            "company_id": str(self.company.id),
            "run_id": str(domain_run.id),
        }

        with patch(
            "dataruns.dcs.orchestrate._resolve_domain_run",
            return_value=domain_run,
        ):
            result = run_dcs_pipeline(data_run)

        self.assertFalse(result["ok"])
        self.assertEqual(data_run.status, "failed")
        self.assertEqual(
            data_run.metadata.get("fresh_import_failed_platform"),
            "shopify",
        )


class DcsFreshImportPipelineIntegrationTests(TestCase):
    """PRD-DCS-10 Step 3 — real ``refresh_connected_platforms_for_dcs`` in pipeline."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="DCS Import Co", slug="dcs-import")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="DCS Import Co",
            domain="dcs-import.test",
        )

    def _create_dcs_score_run(self) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name="dcs-score",
            status=DataRun.Status.PENDING,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "triggered_by": "manual",
            },
        )

    def _integration_patches(self):
        return (
            patch("dataruns.architecture.enqueue.maybe_enqueue_architecture_after_dcs"),
            patch("dataruns.dcs.orchestrate._audit_dcs_completed"),
            patch("dataruns.dcs.orchestrate._notify_dcs_completed"),
            patch("tenants.manago_topology_service.ensure_manago_primary_owner"),
            patch("dataruns.dcs.run_progress.load_check_master", return_value=_JSON_MASTER),
            patch("dataruns.dcs.orchestrate.load_check_master", return_value=_JSON_MASTER),
            patch(
                "dataruns.dcs.fresh_import.run_import",
                side_effect=successful_run_import_side_effect,
            ),
            patch(
                "dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs",
                wraps=refresh_connected_platforms_for_dcs,
            ),
        )

    def _run_pipeline_with_integration_mocks(self, dcs_run: DataRun):
        with ExitStack() as stack:
            stack.enter_context(patch("dataruns.dcs.fresh_import._ensure_shopify_token"))
            mocks = [stack.enter_context(p) for p in self._integration_patches()]
            result = run_dcs_pipeline(dcs_run)
        return result, mocks[-1], mocks[-2]

    def test_pipeline_runs_real_refresh_and_records_fresh_imports(self):
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="connected",
            config=encrypt_config({"client_id": "c1", "api_secret": "s1"}),
        )
        dcs_run = self._create_dcs_score_run()
        before = DataRun.objects.filter(
            tenant=self.tenant,
            name="dcs-fresh-import:manago_ai",
        ).count()

        result, mock_refresh, mock_run_import = self._run_pipeline_with_integration_mocks(
            dcs_run
        )

        self.assertTrue(result["ok"], result)
        mock_refresh.assert_called_once()
        refresh_kwargs = mock_refresh.call_args.kwargs
        self.assertEqual(refresh_kwargs["company"], self.company)
        self.assertEqual(refresh_kwargs["dcs_data_run"], dcs_run)

        dcs_run.refresh_from_db()
        self.assertEqual(dcs_run.status, DataRun.Status.SUCCEEDED)

        fresh_runs = DataRun.objects.filter(
            tenant=self.tenant,
            name="dcs-fresh-import:manago_ai",
            metadata__triggered_by="dcs_score",
            metadata__dcs_data_run_id=dcs_run.id,
        )
        self.assertEqual(fresh_runs.count(), before + 1)
        fresh_run = fresh_runs.latest("id")
        self.assertEqual(fresh_run.status, DataRun.Status.SUCCEEDED)

        fresh_imports = dcs_run.metadata.get("fresh_imports") or {}
        manago_block = fresh_imports["manago_ai"]
        self.assertEqual(manago_block["data_run_id"], fresh_run.id)
        self.assertIsNotNone(manago_block.get("window_end"))
        self.assertEqual(
            str((dcs_run.metadata.get("source_runs") or {}).get("manago_ai")),
            str(fresh_run.id),
        )
        mock_run_import.assert_called_once()
        import_kwargs = mock_run_import.call_args.kwargs
        self.assertEqual(import_kwargs["platform"], "manago_ai")
        self.assertEqual(import_kwargs["company"], self.company)
        self.assertEqual(import_kwargs["data_run"].name, "dcs-fresh-import:manago_ai")

        status = resolve_dcs_app_status(company=self.company)
        self.assertEqual(
            status["latest_run"]["fresh_imports"]["manago_ai"]["data_run_id"],
            fresh_run.id,
        )
        self.assertEqual(
            status["latest_run"]["fresh_imports"]["manago_ai"]["window_end"],
            manago_block["window_end"],
        )

    def test_pipeline_fresh_imports_both_connected_platforms(self):
        Connector.objects.create(
            company=self.company,
            name="shopify",
            type="ecommerce",
            status="connected",
            config=encrypt_config(
                {
                    "shop_domain": "demo.myshopify.com",
                    "access_token": "shpat_test",
                }
            ),
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="crm",
            status="connected",
            config=encrypt_config({"client_id": "c1", "api_secret": "s1"}),
        )
        dcs_run = self._create_dcs_score_run()

        result, mock_refresh, mock_run_import = self._run_pipeline_with_integration_mocks(
            dcs_run
        )

        self.assertTrue(result["ok"], result)
        mock_refresh.assert_called_once()
        self.assertEqual(mock_run_import.call_count, 2)
        imported_platforms = {
            call.kwargs["platform"] for call in mock_run_import.call_args_list
        }
        self.assertEqual(imported_platforms, {"shopify", "manago_ai"})

        dcs_run.refresh_from_db()
        fresh_imports = dcs_run.metadata.get("fresh_imports") or {}
        self.assertIn("shopify", fresh_imports)
        self.assertIn("manago_ai", fresh_imports)

        for platform in ("shopify", "manago_ai"):
            block = fresh_imports[platform]
            self.assertIsNotNone(block.get("data_run_id"))
            self.assertIsNotNone(block.get("window_end"))
            child = DataRun.objects.get(pk=block["data_run_id"])
            self.assertEqual(child.name, f"dcs-fresh-import:{platform}")
            self.assertEqual(child.metadata.get("triggered_by"), "dcs_score")
            self.assertEqual(child.metadata.get("dcs_data_run_id"), dcs_run.id)
            self.assertEqual(child.status, DataRun.Status.SUCCEEDED)
