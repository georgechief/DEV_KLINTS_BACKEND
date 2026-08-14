"""Golden + gate tests for DCS assemble and foundation executors."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from dataruns.dcs.assemble import AssembleValidationError, assemble_dcs_score
from dataruns.dcs.catalogue import build_failure_message
from dataruns.dcs.context_builder import (
    apply_live_manago_auth,
    build_foundation_gate_context,
)
from dataruns.dcs.executors.foundation import (
    SHOPIFY_FD02_REQUIRED_SCOPES,
    ConnectorGateInput,
    FoundationGateContext,
    evaluate_foundation_gates,
    evaluate_fd_01,
    evaluate_fd_02,
    evaluate_fd_03,
    evaluate_fd_05,
)
from dataruns.dcs.master import load_check_master_from_json
from dataruns.dcs.types import CheckResult

FIXTURES_ROOT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "dcs_scoring"
    / "reference"
    / "fixtures"
)
LUMERA_RESULTS = (
    FIXTURES_ROOT / "lumera_expected_results" / "check_results.json"
)
LUMERA_SCORE = FIXTURES_ROOT / "lumera_expected_results" / "dcs_score.json"

# Assemble unit tests use JSON fixture master (runtime DCS uses DB).
_JSON_MASTER = load_check_master_from_json()


def _assemble(results, **kwargs):
    return assemble_dcs_score(results, master=_JSON_MASTER, **kwargs)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _mutate_status(results: list[dict], check_id: str, status: str, **extra) -> list[dict]:
    cloned = copy.deepcopy(results)
    for row in cloned:
        if row["check_id"] == check_id:
            row["status"] = status
            if status in {"PASS", "WARN", "FAIL"}:
                row["score_factor"] = {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0}[status]
                row["reason_code"] = extra.get("reason_code")
            else:
                row["score_factor"] = None
                row["reason_code"] = extra.get("reason_code", "TEST_REASON")
            if "confidence" in extra:
                row["confidence"] = extra["confidence"]
            break
    return cloned


def _all_pass_from_lumera(results: list[dict]) -> list[dict]:
    cloned = copy.deepcopy(results)
    for row in cloned:
        row["status"] = "PASS"
        row["score_factor"] = 1.0
        row["confidence"] = "HIGH"
        row["confidence_factor"] = 1.0
        row["reason_code"] = None
    return cloned


def _partial_sweep(results: list[dict]) -> list[dict]:
    """Mark three Lifecycle Event scored checks UNKNOWN → coverage < 0.80."""
    cloned = copy.deepcopy(results)
    targets = {"LE-01", "LE-02", "LE-03"}
    for row in cloned:
        if row["check_id"] in targets:
            row["status"] = "UNKNOWN"
            row["score_factor"] = None
            row["reason_code"] = "MISSING_INPUT:lifecycle_evidence"
    return cloned


class CheckMasterTests(unittest.TestCase):
    def test_master_has_42_ids_matching_lumera_fixture(self):
        master = load_check_master_from_json()
        fixture_ids = {row["check_id"] for row in _load_json(LUMERA_RESULTS)}
        self.assertEqual(len(master.checks), 42)
        self.assertEqual(master.check_ids(), fixture_ids)


class AssembleLumeraTests(unittest.TestCase):
    def test_lumera_headline_and_dimensions(self):
        results = _load_json(LUMERA_RESULTS)
        expected = _load_json(LUMERA_SCORE)
        dcs = _assemble(results, erp_in_scope=True)

        self.assertEqual(dcs.blocking_gates_failed, 0)
        self.assertAlmostEqual(dcs.headline_score, expected["headline_score"], places=3)
        self.assertEqual(dcs.run_state, expected["score_state"])

        for dim_name, dim_expected in expected["dimensions"].items():
            actual = dcs.dimensions[dim_name]
            self.assertAlmostEqual(actual.score, dim_expected["score"], places=4)
            self.assertAlmostEqual(actual.coverage, dim_expected["coverage"], places=4)
            self.assertAlmostEqual(
                actual.confidence, dim_expected["confidence"], places=4
            )
            self.assertEqual(actual.weight_percent, dim_expected["weight_percent"])


class AssembleGoldenCaseTests(unittest.TestCase):
    def test_all_pass_ready_100(self):
        results = _all_pass_from_lumera(_load_json(LUMERA_RESULTS))
        dcs = _assemble(results, erp_in_scope=True)
        self.assertEqual(dcs.run_state, "READY")
        self.assertAlmostEqual(dcs.headline_score, 100.0, places=3)

    def test_gate_fail_blocked_null_headline(self):
        results = _mutate_status(_load_json(LUMERA_RESULTS), "FD-01", "FAIL")
        dcs = _assemble(results, erp_in_scope=True)
        self.assertEqual(dcs.run_state, "BLOCKED")
        self.assertIsNone(dcs.headline_score)
        self.assertGreaterEqual(dcs.blocking_gates_failed, 1)

    def test_partial_sweep_incomplete(self):
        results = _partial_sweep(_load_json(LUMERA_RESULTS))
        dcs = _assemble(results, erp_in_scope=True)
        self.assertEqual(dcs.run_state, "INCOMPLETE")
        self.assertLess(
            dcs.dimensions["02 Lifecycle Event"].coverage,
            0.80,
        )

    def test_excluded_status_requires_reason_code(self):
        results = _mutate_status(
            _load_json(LUMERA_RESULTS),
            "CI-01",
            "UNKNOWN",
            reason_code=None,
        )
        # Force missing reason
        for row in results:
            if row["check_id"] == "CI-01":
                row["reason_code"] = None
                row["score_factor"] = None
        with self.assertRaises(AssembleValidationError):
            _assemble(results, erp_in_scope=True)

    def test_erp_out_of_scope_fd03_not_blocking(self):
        results = _mutate_status(_load_json(LUMERA_RESULTS), "FD-03", "FAIL")
        dcs = _assemble(results, erp_in_scope=False)
        self.assertNotEqual(dcs.run_state, "BLOCKED")
        self.assertIsNotNone(dcs.headline_score)
        self.assertNotIn("07 Business Reality", dcs.dimensions)


class FoundationGateTests(unittest.TestCase):
    def test_manago_auth_failed_fd01_fail(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                data_run_id=10,
                health_report={
                    "summary_status": "error",
                    "blocking": True,
                    "preflight": {
                        "auth_ok": False,
                        "issues": [
                            {
                                "code": "AUTH_FAILED",
                                "severity": "error",
                                "message": "bad key",
                            }
                        ],
                    },
                    "fetch": {"issues": []},
                    "postflight": {"issues": []},
                },
            ),
            erp_in_scope=False,
        )
        result = evaluate_fd_01(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-12")
        self.assertIn("RC-12", result.root_cause_ids)
        self.assertTrue(result.message)
        self.assertIn("Configuration error", result.message)
        self.assertTrue(result.suggested_fix)
        self.assertEqual(result.severity, "Critical")
        self.assertTrue(result.root_causes)
        self.assertEqual(result.root_causes[0]["code"], "RC-12")

        dcs = self._assemble_with_gate(result, erp_in_scope=False)
        self.assertEqual(dcs.run_state, "BLOCKED")
        self.assertIsNone(dcs.headline_score)

    def test_fd01_live_auth_overrides_stale_health(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                connector_status="connected",
                live_auth_ok=False,
                live_auth_message="signed call success=false",
                health_report={
                    "summary_status": "ok",
                    "preflight": {"auth_ok": True, "issues": []},
                },
            ),
        )
        result = evaluate_fd_01(ctx)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.reason_code, "RC-12")
        self.assertIn("signed call", result.message or "")

    def test_fd01_live_auth_pass(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                live_auth_ok=True,
                live_auth_message="ok",
            ),
        )
        result = evaluate_fd_01(ctx)
        self.assertEqual(result.status, "PASS")

    def test_fd02_required_scopes_pass(self):
        ctx = FoundationGateContext(
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                connector_status="connected",
                scopes_granted=["read_customers", "read_orders"],
                health_report={
                    "summary_status": "ok",
                    "preflight": {
                        "auth_ok": True,
                        "scopes_granted": ["read_customers", "read_orders"],
                        "issues": [],
                    },
                },
            ),
        )
        result = evaluate_fd_02(ctx)
        self.assertEqual(result.status, "PASS")

    def test_fd02_full_sheet_scopes_pass(self):
        scopes = sorted(SHOPIFY_FD02_REQUIRED_SCOPES)
        ctx = FoundationGateContext(
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                connector_status="connected",
                scopes_granted=scopes,
                health_report={
                    "summary_status": "ok",
                    "preflight": {
                        "auth_ok": True,
                        "scopes_granted": scopes,
                        "issues": [],
                    },
                },
            ),
        )
        self.assertEqual(evaluate_fd_02(ctx).status, "PASS")

    def test_fd02_auth_ok_without_scopes_is_unknown(self):
        ctx = FoundationGateContext(
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                connector_status="connected",
                health_report={
                    "summary_status": "ok",
                    "preflight": {"auth_ok": True, "scopes_ok": True, "issues": []},
                },
            ),
        )
        result = evaluate_fd_02(ctx)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.reason_code, "MISSING_INPUT:scopes")

    def test_erp_out_of_scope_fd03_not_connected(self):
        ctx = FoundationGateContext(erp_in_scope=False)
        result = evaluate_fd_03(ctx)
        self.assertEqual(result.status, "NOT_CONNECTED")
        self.assertEqual(result.reason_code, "ERP_OUT_OF_SCOPE")

    def test_bootstraps_ok_fd01_fd02_fd05_pass(self):
        scopes = sorted(SHOPIFY_FD02_REQUIRED_SCOPES)
        healthy_manago = {
            "summary_status": "ok",
            "days": 30,
            "blocking": False,
            "preflight": {"auth_ok": True, "issues": []},
            "fetch": {"ok": True, "issues": []},
            "postflight": {"issues": []},
        }
        healthy_shopify = {
            "summary_status": "ok",
            "days": 30,
            "blocking": False,
            "preflight": {
                "auth_ok": True,
                "scopes_ok": True,
                "scopes_granted": scopes,
                "issues": [],
            },
            "fetch": {"ok": True, "issues": []},
            "postflight": {"issues": []},
        }
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(
                platform="manago_ai",
                connected=True,
                connector_status="connected",
                data_run_id=1,
                health_report=healthy_manago,
                topology_ok=True,
                topology_accounts=[
                    {
                        "account_id": "c1",
                        "owner": "owner@example.com",
                        "endpoint": "https://app3.manago.ai",
                        "classification": "single_account",
                        "in_scope": True,
                    }
                ],
                rate_budget={
                    "platform": "manago_ai",
                    "requests_sampled": 3,
                    "requests_ok": 3,
                    "safe_request_budget": 3,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "probe",
                },
                history_earliest={"orders": "2026-01-01T00:00:00Z"},
                tracking_measurable=True,
                tracking_active=True,
            ),
            shopify=ConnectorGateInput(
                platform="shopify",
                connected=True,
                connector_status="connected",
                data_run_id=2,
                health_report=healthy_shopify,
                scopes_granted=scopes,
                rate_budget={
                    "platform": "shopify",
                    "used": 10,
                    "limit": 40,
                    "remaining": 30,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "header",
                },
                history_earliest={"orders": "2026-01-01T00:00:00Z"},
            ),
            erp_in_scope=False,
            skip_website_scrape=True,
            extra={
                "history_depth": {
                    "platforms": {
                        "manago_ai": {
                            "platform": "manago_ai",
                            "depth_days": 30,
                            "meets_required": True,
                            "earliest": {"orders": "2026-01-01T00:00:00Z"},
                        },
                        "shopify": {
                            "platform": "shopify",
                            "depth_days": 45,
                            "meets_required": True,
                            "earliest": {"orders": "2025-12-15T00:00:00Z"},
                        },
                    },
                    "common_window_days": 30,
                }
            },
        )
        results = {r.check_id: r for r in evaluate_foundation_gates(ctx)}
        self.assertEqual(results["FD-01"].status, "PASS")
        self.assertEqual(results["FD-02"].status, "PASS")
        self.assertEqual(results["FD-04"].status, "PASS")
        self.assertEqual(results["FD-05"].status, "PASS")
        self.assertEqual(results["FD-06"].status, "PASS")
        self.assertEqual(results["FD-03"].status, "NOT_CONNECTED")
        self.assertEqual(evaluate_fd_05(ctx).confidence, "HIGH")

    def test_manago_not_connected_not_fail(self):
        ctx = FoundationGateContext(
            manago=ConnectorGateInput(platform="manago_ai", connected=False),
            erp_in_scope=False,
        )
        result = evaluate_fd_01(ctx)
        self.assertEqual(result.status, "NOT_CONNECTED")
        self.assertNotEqual(result.status, "FAIL")

    def test_failure_message_is_merchant_friendly(self):
        with_detail = build_failure_message(
            check_id="FD-01",
            root_cause_ids=["RC-12"],
            detail="Your Manago API key looks incorrect.",
        )
        self.assertEqual(with_detail, "Your Manago API key looks incorrect.")
        self.assertNotIn("RC-12", with_detail)

        without_detail = build_failure_message(
            check_id="FD-01",
            root_cause_ids=["RC-12"],
        )
        self.assertIn("wrong or absent", without_detail.lower())
        # Plain language uses definition, not technical IDs.
        self.assertNotIn("RC-12", without_detail)
        self.assertNotIn("FD-01 failed", without_detail)

    def test_context_builder_and_live_auth_hook(self):
        scopes = sorted(SHOPIFY_FD02_REQUIRED_SCOPES)
        ctx = build_foundation_gate_context(
            manago={
                "connected": True,
                "status": "connected",
                "health_report": {
                    "summary_status": "ok",
                    "days": 30,
                    "preflight": {"auth_ok": True, "issues": []},
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
                    "requests_ok": 2,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "probe",
                },
                "tracking_measurable": True,
                "tracking_active": True,
            },
            shopify={
                "connected": True,
                "status": "connected",
                "scopes_granted": scopes,
                "rate_budget": {
                    "platform": "shopify",
                    "used": 5,
                    "limit": 40,
                    "remaining": 35,
                    "hit_rate_limit": False,
                    "headroom_ok": True,
                    "source": "header",
                },
                "health_report": {
                    "summary_status": "ok",
                    "days": 30,
                    "preflight": {
                        "auth_ok": True,
                        "scopes_granted": scopes,
                        "issues": [],
                    },
                },
            },
            erp={"in_scope": False},
            tenant_id="t1",
            run_id="r1",
        )
        self.assertIsNotNone(ctx.manago)
        assert ctx.manago is not None
        apply_live_manago_auth(
            ctx.manago,
            verify=lambda **_: SimpleNamespace(valid=True, message="ok"),
            client_id="c",
            api_secret="s",
        )
        self.assertTrue(ctx.manago.live_auth_ok)
        results = {r.check_id: r for r in evaluate_foundation_gates(ctx)}
        self.assertEqual(results["FD-01"].status, "PASS")
        self.assertEqual(results["FD-02"].status, "PASS")

    def _assemble_with_gate(self, gate: CheckResult, *, erp_in_scope: bool):
        results = _load_json(LUMERA_RESULTS)
        for row in results:
            if row["check_id"] == gate.check_id:
                row["status"] = gate.status
                row["reason_code"] = gate.reason_code
                row["score_factor"] = gate.normalized_score_factor()
                break
        return _assemble(results, erp_in_scope=erp_in_scope)


if __name__ == "__main__":
    unittest.main()
