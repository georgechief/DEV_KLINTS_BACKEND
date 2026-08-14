"""Unit tests for DCS run_snapshot builder and RunIssue persistence helpers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from dataruns.dcs.issues import build_issue_details, persist_dcs_issues
from dataruns.dcs.snapshot import build_dcs_run_snapshot
from dataruns.dcs.types import CheckResult, Evidence


class BuildDcsRunSnapshotTests(SimpleTestCase):
    @patch(
        "dataruns.dcs.snapshot.build_drift_snapshot",
        return_value={
            "drift": {
                "le08_cart_events": 0,
                "raw_enrichment": {"cart_events_present": False},
            }
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_workflow_snapshot",
        return_value={
            "workflows": [],
            "measurement": {
                "workflows_available": False,
                "raw_enrichment": {
                    "workflow_definitions_present": False,
                    "workflow_analytics_present": False,
                },
            },
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_segment_snapshot",
        return_value={
            "details": [],
            "segments": [],
            "segment": {
                "detail_key_count": 0,
                "raw_enrichment": {
                    "manago_contacts_from_raw": True,
                    "details_present": False,
                    "tags_present": False,
                },
            },
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_catalog_snapshot",
        return_value={
            "products": [],
            "catalog": {
                "manago_catalog_available": False,
                "raw_enrichment": {
                    "shopify_line_items_present": False,
                    "shopify_products_api_present": False,
                    "manago_event_products_present": False,
                    "manago_catalog_present": False,
                    "manago_catalog_meta_present": False,
                },
            },
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_product_truth_snapshot",
        return_value={
            "product_truth_rows": [],
            "product_truth": {
                "linked_contacts": 0,
                "raw_enrichment": {"shopify_from_raw": False, "manago_from_raw": False},
            },
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_consent_snapshot",
        return_value={
            "consent_rows": [],
            "consent": {
                "linked_identities": 0,
                "hard_bounce_complaint_available": False,
                "raw_enrichment": {"consent_fields_present": False},
            },
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_lifecycle_snapshot",
        return_value={
            "events": [],
            "orders": [],
            "lifecycle": {
                "shopify_paid_orders": 3,
                "manago_purchase_events": 2,
                "manago_return_cancel_events": 0,
                "raw_enrichment": {
                    "return_events_from_raw": False,
                    "external_id_from_raw": False,
                    "test_filter_applied": False,
                },
            },
        },
    )
    @patch(
        "dataruns.dcs.snapshot.build_identity_snapshot",
        return_value={
            "contacts": [],
            "orders": [],
            "identity": {
                "shopify_customers": 5,
                "manago_contacts": 7,
                "shopify_orders": 3,
                "in_both": 0,
                "manago_only": 0,
                "shopify_only": 0,
            },
        },
    )
    @patch("dataruns.dcs.snapshot._gate_inputs_from_import", return_value={})
    @patch(
        "dataruns.dcs.snapshot._connector_status",
        return_value={"status": "not_connected", "scopes": []},
    )
    @patch("dataruns.dcs.snapshot.Order.objects")
    @patch("dataruns.dcs.snapshot.Contact.objects")
    def test_snapshot_shape_from_fresh_imports(
        self,
        mock_contact_objects,
        mock_order_objects,
        _mock_connector_status,
        _mock_gate_inputs,
        _mock_identity,
        _mock_lifecycle,
        _mock_consent,
        _mock_product_truth,
        _mock_catalog,
        _mock_segment,
        _mock_workflow,
        _mock_drift,
    ):
        company_id = uuid.uuid4()
        company = SimpleNamespace(id=company_id)
        mock_contact_objects.filter.return_value.count.return_value = 12
        mock_order_objects.filter.return_value.count.return_value = 4

        snapshot = build_dcs_run_snapshot(
            company=company,
            source_runs={"shopify": 101, "manago_ai": 202},
            fresh_imports={
                "shopify": {
                    "data_run_id": 101,
                    "run_id": str(uuid.uuid4()),
                    "counts": {"contacts": 5, "orders": 3},
                    "window_start": "2026-07-01T00:00:00Z",
                    "window_end": "2026-07-31T00:00:00Z",
                },
                "manago_ai": {
                    "data_run_id": 202,
                    "run_id": str(uuid.uuid4()),
                    "counts": {"contacts": 7, "orders": 0},
                },
            },
            window_days=30,
        )

        self.assertEqual(snapshot["schema_version"], "1.0.0")
        self.assertEqual(snapshot["company_id"], str(company_id))
        self.assertEqual(snapshot["window_days"], 30)
        self.assertEqual(snapshot["counts"]["shopify_customers"], 5)
        self.assertEqual(snapshot["counts"]["shopify_orders"], 3)
        self.assertEqual(snapshot["counts"]["manago_contacts"], 7)
        self.assertEqual(snapshot["counts"]["manago_purchase_events"], 2)
        self.assertEqual(snapshot["counts"]["contacts_total"], 12)
        self.assertIn("lifecycle", snapshot)
        self.assertIn("catalog", snapshot)
        self.assertIn("segment", snapshot)
        self.assertIn("measurement", snapshot)
        self.assertIn("drift", snapshot)
        self.assertIn("manago_return_events_raw", snapshot["missing_inputs"])
        self.assertEqual(snapshot["counts"]["orders_total"], 4)
        self.assertEqual(snapshot["source_runs"]["shopify"]["data_run_id"], 101)
        self.assertIn("manago_product_catalog", snapshot["missing_inputs"])
        self.assertIn("workflows", snapshot["missing_inputs"])
        self.assertIn("as_of", snapshot)


class BuildIssueDetailsTests(SimpleTestCase):
    def test_fail_evidence_goes_to_mismatches(self):
        result = CheckResult(
            check_id="FD-01",
            status="FAIL",
            reason_code="RC-12",
            message="auth failed",
            evidence=[
                Evidence(
                    source="manago",
                    observed_at="2026-07-31T00:00:00Z",
                    locator="auth_ok",
                    value=False,
                )
            ],
        )
        details = build_issue_details(result)
        self.assertEqual(details["check_id"], "FD-01")
        self.assertEqual(details["status"], "FAIL")
        self.assertEqual(len(details["mismatches"]), 1)
        self.assertEqual(details["matches"], [])
        self.assertEqual(details["mismatches"][0]["locator"], "auth_ok")

    def test_pass_evidence_goes_to_matches(self):
        result = CheckResult(
            check_id="FD-02",
            status="PASS",
            evidence=[
                Evidence(
                    source="shopify",
                    observed_at="2026-07-31T00:00:00Z",
                    locator="auth_ok",
                    value=True,
                )
            ],
        )
        details = build_issue_details(result)
        self.assertEqual(len(details["matches"]), 1)
        self.assertEqual(details["mismatches"], [])

    def test_unknown_stub_has_empty_match_lists(self):
        result = CheckResult(
            check_id="CI-01",
            status="UNKNOWN",
            reason_code="EXECUTOR_NOT_IMPLEMENTED",
        )
        details = build_issue_details(result)
        self.assertEqual(details["matches"], [])
        self.assertEqual(details["mismatches"], [])
        self.assertEqual(details["reason_code"], "EXECUTOR_NOT_IMPLEMENTED")


class PersistDcsIssuesTests(SimpleTestCase):
    @patch("dataruns.dcs.issues.RunIssueImpact.objects")
    @patch("dataruns.dcs.issues.RunIssue.objects")
    @patch("dataruns.dcs.issues.RunIssueImpact")
    @patch("dataruns.dcs.issues.RunIssue")
    def test_persists_one_issue_and_impact_per_check(
        self,
        mock_issue_cls,
        mock_impact_cls,
        mock_issue_objects,
        mock_impact_objects,
    ):
        company = SimpleNamespace(id=uuid.uuid4())
        domain_run = MagicMock()
        results = [
            CheckResult(check_id="FD-01", status="PASS"),
            CheckResult(
                check_id="FD-02",
                status="FAIL",
                severity="Critical",
                evidence=[
                    Evidence(
                        source="shopify",
                        observed_at="2026-07-31T00:00:00Z",
                        locator="scopes",
                        value=["read_customers"],
                    )
                ],
            ),
            CheckResult(
                check_id="LE-01",
                status="UNKNOWN",
                reason_code="EXECUTOR_NOT_IMPLEMENTED",
            ),
            CheckResult(
                check_id="CI-01",
                status="UNKNOWN",
                reason_code="MISSING_INPUT:identity",
            ),
        ]
        built_issues = []

        def _issue_factory(**kwargs):
            issue = MagicMock()
            issue.id = uuid.uuid4()
            issue.severity = kwargs.get("severity")
            issue.issue_type = kwargs.get("issue_type")
            issue.entity_type = kwargs.get("entity_type")
            issue.entity_id = kwargs.get("entity_id")
            issue.details = kwargs.get("details")
            built_issues.append(issue)
            return issue

        mock_issue_cls.side_effect = _issue_factory
        mock_impact_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        mock_issue_objects.bulk_create.side_effect = lambda rows: rows

        out = persist_dcs_issues(
            company=company,
            domain_run=domain_run,
            check_results=results,
        )
        # Stub UNKNOWN+EXECUTOR_NOT_IMPLEMENTED skipped; MISSING_INPUT kept.
        self.assertEqual(len(out), 3)
        mock_issue_objects.bulk_create.assert_called_once()
        types = [i.issue_type for i in built_issues]
        self.assertEqual(types, ["FD-01", "FD-02", "CI-01"])
        self.assertEqual(built_issues[0].entity_type, "dcs_check")
        self.assertEqual(built_issues[0].entity_id, company.id)
        self.assertEqual(built_issues[1].details["status"], "FAIL")
        self.assertTrue(built_issues[1].details["mismatches"])

        mock_impact_objects.bulk_create.assert_called_once()
        impact_rows = mock_impact_objects.bulk_create.call_args.args[0]
        self.assertEqual(len(impact_rows), 3)

    @patch("dataruns.dcs.issues.RunIssueImpact.objects")
    @patch("dataruns.dcs.issues.RunIssue.objects")
    @patch("dataruns.dcs.issues.RunIssueImpact")
    @patch("dataruns.dcs.issues.RunIssue")
    def test_skips_all_when_only_unimplemented_stubs(
        self,
        mock_issue_cls,
        mock_impact_cls,
        mock_issue_objects,
        mock_impact_objects,
    ):
        company = SimpleNamespace(id=uuid.uuid4())
        domain_run = MagicMock()
        out = persist_dcs_issues(
            company=company,
            domain_run=domain_run,
            check_results=[
                CheckResult(
                    check_id="LE-01",
                    status="UNKNOWN",
                    reason_code="EXECUTOR_NOT_IMPLEMENTED",
                ),
                CheckResult(
                    check_id="PT-01",
                    status="UNKNOWN",
                    reason_code="EXECUTOR_NOT_IMPLEMENTED",
                ),
            ],
        )
        self.assertEqual(out, [])
        mock_issue_objects.bulk_create.assert_not_called()
        mock_impact_objects.bulk_create.assert_not_called()
        mock_issue_cls.assert_not_called()
