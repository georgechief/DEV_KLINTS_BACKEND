"""Unit tests for DCS score orchestration (PRD-DCS-01 MVP).

Uses SimpleTestCase + mocks so we don't depend on the broken tenants→dataruns
fresh-DB migration order. Foundation gate behavior is covered separately.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from dataruns.dcs.context_builder import build_foundation_gate_context
from dataruns.dcs.enqueue import DcsAlreadyRunningError, enqueue_dcs_score
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.orchestrate import evaluate_check_results, run_dcs_pipeline
from dataruns.dcs.types import CheckResult

_JSON_MASTER = load_check_master_from_json()


@patch(
    "dataruns.dcs.orchestrate.load_check_master",
    return_value=_JSON_MASTER,
)
class EvaluateCheckResultsTests(SimpleTestCase):
    def test_returns_exactly_42_results(self, _mock_master):
        ctx = build_foundation_gate_context(
            manago={"connected": False},
            shopify={"connected": False},
            erp={"in_scope": False},
            tenant_id="t",
            run_id="r",
        )
        results = evaluate_check_results(ctx=ctx, tenant_id="t", run_id="r")
        self.assertEqual(len(results), 42)
        by_id = {r.check_id: r for r in results}
        self.assertEqual(by_id["FD-01"].status, "NOT_CONNECTED")
        self.assertEqual(by_id["CI-01"].status, "NOT_CONNECTED")
        self.assertEqual(by_id["CI-01"].reason_code, "NO_CONNECTORS_FOR_IDENTITY")
        self.assertEqual(by_id["BR-01"].status, "NOT_CONNECTED")
        self.assertEqual(by_id["BR-01"].reason_code, "ERP_OUT_OF_SCOPE")

    def test_gate_fail_is_real_fail_not_stub(self, _mock_master):
        ctx = build_foundation_gate_context(
            manago={
                "connected": True,
                "status": "connected",
                "health_report": {
                    "summary_status": "error",
                    "preflight": {
                        "auth_ok": False,
                        "issues": [
                            {
                                "code": "AUTH_FAILED",
                                "severity": "error",
                                "message": "bad",
                            }
                        ],
                    },
                },
            },
            shopify={"connected": False},
            erp={"in_scope": False},
            tenant_id="t",
            run_id="r",
        )
        results = evaluate_check_results(ctx=ctx, tenant_id="t", run_id="r")
        by_id = {r.check_id: r for r in results}
        self.assertEqual(by_id["FD-01"].status, "FAIL")
        self.assertEqual(by_id["FD-01"].reason_code, "RC-12")


class EnqueueDcsScoreTests(SimpleTestCase):
    @patch("dataruns.dcs.enqueue.resolve_source_runs", return_value={"shopify": None, "manago_ai": None})
    @patch("dataruns.dcs.enqueue.DataRun.objects")
    @patch("dataruns.dcs.enqueue.Run.objects")
    @patch("dataruns.dcs.enqueue.find_active_dcs_data_run", return_value=None)
    def test_enqueue_creates_pending_data_run(
        self, _find_active, mock_run_objects, mock_data_run_objects, _sources
    ):
        company = SimpleNamespace(
            id=uuid.uuid4(),
            tenant=SimpleNamespace(id=uuid.uuid4()),
        )
        domain_run = SimpleNamespace(id=uuid.uuid4())
        data_run = SimpleNamespace(id=101, status="pending")
        mock_run_objects.create.return_value = domain_run
        mock_data_run_objects.create.return_value = data_run

        result = enqueue_dcs_score(company=company, queue=False)
        self.assertEqual(result.data_run.id, 101)
        self.assertFalse(result.task_queued)
        mock_data_run_objects.create.assert_called_once()
        kwargs = mock_data_run_objects.create.call_args.kwargs
        self.assertEqual(kwargs["name"], "dcs-score")
        self.assertEqual(kwargs["metadata"]["kind"], "dcs_score")
        self.assertEqual(kwargs["metadata"]["company_id"], str(company.id))

    @patch(
        "dataruns.dcs.enqueue.find_active_dcs_data_run",
        return_value=SimpleNamespace(id=7, status="running"),
    )
    def test_enqueue_conflict(self, _find_active):
        company = SimpleNamespace(id=uuid.uuid4())
        with self.assertRaises(DcsAlreadyRunningError):
            enqueue_dcs_score(company=company, queue=False)


class RunDcsPipelineTests(SimpleTestCase):
    @patch("dataruns.architecture.enqueue.maybe_enqueue_architecture_after_dcs")
    @patch("dataruns.dcs.orchestrate._audit_dcs_completed")
    @patch("dataruns.dcs.run_diff.persist_consecutive_run_diff")
    @patch("dataruns.dcs.orchestrate.persist_stage_progress")
    @patch("dataruns.dcs.orchestrate.persist_import_stage_running")
    @patch(
        "dataruns.dcs.orchestrate.load_check_master",
        return_value=_JSON_MASTER,
    )
    @patch("dataruns.dcs.orchestrate.persist_dcs_results")
    @patch("dataruns.dcs.orchestrate.build_foundation_context_for_company")
    @patch("dataruns.dcs.orchestrate.build_dcs_run_snapshot")
    @patch("dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs")
    @patch("dataruns.dcs.orchestrate.resolve_company_from_data_run")
    def test_pipeline_success_path(
        self,
        mock_resolve_company,
        mock_refresh,
        mock_snapshot,
        mock_build_ctx,
        mock_persist,
        _mock_master,
        _mock_import_progress,
        _mock_stage_progress,
        mock_persist_run_diff,
        mock_audit_completed,
        _mock_arch_enqueue,
    ):
        tenant_id = uuid.uuid4()
        company = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            tenant=SimpleNamespace(id=tenant_id),
        )
        mock_resolve_company.return_value = company
        mock_refresh.return_value = {
            "source_runs": {"shopify": 11, "manago_ai": 10},
            "fresh_imports": {
                "shopify": {"data_run_id": 11, "counts": {"contacts": 1, "orders": 1}},
                "manago_ai": {"data_run_id": 10, "counts": {"contacts": 2, "orders": 0}},
            },
            "window_days": 30,
        }
        mock_snapshot.return_value = {
            "schema_version": "1.0.0",
            "company_id": str(company.id),
            "as_of": "2026-07-31T12:00:00Z",
            "window_days": 30,
            "counts": {},
            "missing_inputs": [],
        }

        ctx = build_foundation_gate_context(
            manago={
                "connected": True,
                "status": "connected",
                "health_report": {
                    "summary_status": "ok",
                    "days": 30,
                    "preflight": {"auth_ok": True, "issues": []},
                    "fetch": {"issues": []},
                    "postflight": {"issues": []},
                },
                "topology_ok": True,
                "topology_accounts": [
                    {
                        "account_id": "c1",
                        "owner": "owner@example.com",
                        "endpoint": "https://app3.manago.ai",
                        "classification": "single_account",
                        "in_scope": True,
                    }
                ],
                "rate_budget": {
                    "platform": "manago_ai",
                    "requests_ok": 3,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "import",
                },
                "tracking_measurable": True,
                "tracking_active": True,
            },
            shopify={
                "connected": True,
                "status": "connected",
                "scopes_granted": [
                    "read_customers",
                    "read_orders",
                ],
                "rate_budget": {
                    "platform": "shopify",
                    "used": 12,
                    "limit": 40,
                    "remaining": 28,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "import",
                },
                "health_report": {
                    "summary_status": "ok",
                    "days": 30,
                    "preflight": {
                        "auth_ok": True,
                        "scopes_granted": [
                            "read_customers",
                            "read_orders",
                        ],
                        "issues": [],
                    },
                    "fetch": {"issues": []},
                    "postflight": {"issues": []},
                },
            },
            erp={"in_scope": False},
            tenant_id=str(tenant_id),
            run_id="run-1",
        )
        ctx.extra["manago_topology"] = {
            "schema_version": "1.0.0",
            "source": "manago_ai",
            "accounts": [
                {
                    "account_id": "c1",
                    "owner": "owner@example.com",
                    "endpoint": "https://app3.manago.ai",
                    "classification": "single_account",
                    "in_scope": True,
                }
            ],
            "topology_ok": True,
        }
        ctx.extra["history_depth"] = {
            "platforms": {
                "shopify": {
                    "platform": "shopify",
                    "depth_days": 30,
                    "meets_required": True,
                    "earliest": {"orders": "2026-06-01T00:00:00Z"},
                }
            },
            "common_window_days": 30,
        }
        mock_build_ctx.return_value = (
            ctx,
            {"manago_ai": 10, "shopify": 11},
        )

        run_score = SimpleNamespace(id=uuid.uuid4())
        mock_persist.return_value = run_score

        domain_run = MagicMock()
        domain_run.id = uuid.uuid4()
        domain_run.status = "running"

        data_run = MagicMock()
        data_run.id = 55
        data_run.status = "pending"
        data_run.started_at = None
        data_run.run_snapshot = {}
        data_run.metadata = {
            "kind": "dcs_score",
            "erp_in_scope": False,
            "company_id": str(company.id),
            "source_runs": {},
            "run_id": str(domain_run.id),
        }

        mock_persist_run_diff.return_value = {
            "schema_version": 1,
            "baseline": True,
            "headline_score": None,
        }

        with patch(
            "dataruns.dcs.orchestrate._resolve_domain_run",
            return_value=domain_run,
        ), patch("dataruns.dcs.orchestrate.transaction.atomic"), patch(
            "dataruns.dcs.orchestrate._notify_dcs_completed"
        ) as mock_notify, patch(
            "tenants.manago_topology_service.ensure_manago_primary_owner"
        ):
            result = run_dcs_pipeline(data_run)

        self.assertTrue(result["ok"])
        self.assertEqual(result["check_count"], 42)
        self.assertEqual(result["data_run_id"], 55)
        self.assertEqual(result["run_snapshot_as_of"], "2026-07-31T12:00:00Z")
        mock_refresh.assert_called_once()
        mock_snapshot.assert_called_once()
        self.assertEqual(
            data_run.run_snapshot["as_of"], "2026-07-31T12:00:00Z"
        )
        self.assertIn("account_map", data_run.run_snapshot)
        self.assertTrue(data_run.run_snapshot["account_map"]["topology_ok"])
        self.assertEqual(
            data_run.run_snapshot["gate_inputs"]["topology"]["topology_ok"],
            True,
        )
        self.assertEqual(
            data_run.run_snapshot["history_depth"]["common_window_days"], 30
        )
        self.assertIn("rate_budgets", data_run.run_snapshot["gate_inputs"])
        mock_persist.assert_called_once()
        saved_results = mock_persist.call_args.kwargs["check_results"]
        self.assertEqual(len(saved_results), 42)
        mock_notify.assert_called_once()
        mock_persist_run_diff.assert_called_once_with(
            company=company,
            data_run=data_run,
        )
        mock_audit_completed.assert_called_once()
        audit_kwargs = mock_audit_completed.call_args.kwargs
        self.assertEqual(audit_kwargs["run_diff"]["baseline"], True)
        self.assertTrue(all(isinstance(r, CheckResult) for r in saved_results))
        # Fresh source runs are passed into gate context builder.
        ctx_kwargs = mock_build_ctx.call_args.kwargs
        self.assertEqual(ctx_kwargs["source_run_ids"]["shopify"], 11)
        self.assertEqual(ctx_kwargs["source_run_ids"]["manago_ai"], 10)

    @patch("dataruns.dcs.orchestrate._audit_dcs_failed")
    @patch("dataruns.dcs.orchestrate.finalize_stage_progress_on_failure")
    @patch("dataruns.dcs.orchestrate.persist_import_stage_running")
    @patch("dataruns.dcs.orchestrate.resolve_company_from_data_run")
    @patch("dataruns.dcs.orchestrate.refresh_connected_platforms_for_dcs")
    @patch("dataruns.dcs.orchestrate._notify_dcs_failed")
    @patch("tenants.manago_topology_service.ensure_manago_primary_owner")
    def test_pipeline_fails_when_fresh_import_fails(
        self,
        _mock_ensure_owner,
        mock_notify_failed,
        mock_refresh,
        mock_resolve_company,
        _mock_import_progress,
        _mock_finalize_progress,
        _mock_audit_failed,
    ):
        from dataruns.dcs.fresh_import import DcsFreshImportError

        tenant_id = uuid.uuid4()
        company = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            tenant=SimpleNamespace(id=tenant_id),
        )
        mock_resolve_company.return_value = company
        mock_refresh.side_effect = DcsFreshImportError(
            "Fresh shopify import failed: boom",
            platform="shopify",
        )

        domain_run = MagicMock()
        domain_run.id = uuid.uuid4()
        domain_run.status = "running"

        data_run = MagicMock()
        data_run.id = 56
        data_run.status = "pending"
        data_run.started_at = None
        data_run.run_snapshot = {}
        data_run.metadata = {
            "kind": "dcs_score",
            "company_id": str(company.id),
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
            data_run.metadata.get("fresh_import_failed_platform"), "shopify"
        )
        mock_notify_failed.assert_called_once()

    def test_pipeline_rejects_non_dcs_data_run(self):
        data_run = MagicMock()
        data_run.metadata = {"kind": "connector_bootstrap"}
        result = run_dcs_pipeline(data_run)
        self.assertFalse(result["ok"])

    def test_pipeline_idempotent_when_already_succeeded(self):
        data_run = MagicMock()
        data_run.id = 99
        data_run.status = "succeeded"
        data_run.metadata = {
            "kind": "dcs_score",
            "dcs_run": {"run_state": "INCOMPLETE", "headline_score": None},
        }
        result = run_dcs_pipeline(data_run)
        self.assertTrue(result["ok"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["run_state"], "INCOMPLETE")
