"""Tests for Architecture Assessment Phase A (PRD-AF-01)."""

from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import patch

from dataruns.architecture.constants import ARCHITECTURE_ASSESSMENT_KIND
from dataruns.architecture.enqueue import (
    enqueue_architecture_assessment,
    maybe_enqueue_architecture_after_dcs,
)
from dataruns.architecture.models import ArchitectureAssessment
from dataruns.architecture.runner import run_architecture_assessment_job
from dataruns.architecture.views import ArchitectureLatestView
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.models import DataRun
from tenants.models import Company, Connector, Tenant, User


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ArchitectureEnqueueTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme AF", slug="acme-af")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme AF",
            domain="acme-af.com",
        )

    def _dcs_run(self, *, status=DataRun.Status.SUCCEEDED) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name="DCS Score",
            status=status,
            metadata={"kind": DCS_SCORE_KIND, "company_id": str(self.company.id)},
        )

    def _connect_manago(self) -> Connector:
        return Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )

    def test_skip_without_manago(self):
        dcs = self._dcs_run()
        result = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        self.assertTrue(result.skipped)
        self.assertEqual(result.skip_reason, "manago_not_eligible")
        self.assertEqual(ArchitectureAssessment.objects.count(), 0)

    def test_enqueue_creates_assessment_and_data_run(self):
        self._connect_manago()
        dcs = self._dcs_run()
        result = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        self.assertFalse(result.skipped)
        self.assertIsNotNone(result.assessment)
        self.assertEqual(result.assessment.status, ArchitectureAssessment.Status.PENDING)
        self.assertEqual(result.data_run.metadata.get("kind"), ARCHITECTURE_ASSESSMENT_KIND)
        self.assertEqual(result.assessment.source_dcs_data_run_id, dcs.id)

    def test_coalesce_when_already_running(self):
        self._connect_manago()
        dcs1 = self._dcs_run()
        first = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs1,
            queue=False,
        )
        dcs2 = self._dcs_run()
        second = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs2,
            queue=False,
        )
        self.assertTrue(second.skipped)
        self.assertEqual(second.skip_reason, "already_running")
        self.assertEqual(ArchitectureAssessment.objects.count(), 1)
        first.assessment.refresh_from_db()
        self.assertEqual(first.assessment.source_dcs_data_run_id, dcs2.id)

    @patch("dataruns.tasks.run_architecture_assessment.delay")
    def test_maybe_enqueue_after_dcs_best_effort(self, _mock_delay):
        self._connect_manago()
        dcs = self._dcs_run()
        result = maybe_enqueue_architecture_after_dcs(
            company=self.company,
            source_dcs_data_run=dcs,
        )
        self.assertIsNotNone(result)
        self.assertFalse(result.skipped)

    @patch("dataruns.architecture.runner.run_phase_b_inventory")
    def test_scaffold_runner_marks_incomplete(self, mock_inventory):
        from dataruns.architecture.inventory import InventoryAsset, InventoryResult, ProbeOutcome

        mock_inventory.return_value = InventoryResult(
            assets=[],
            probes=[
                ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 0}),
                ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 0}),
                ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
            ],
            evidence_coverage=0.6,
        )
        self._connect_manago()
        dcs = self._dcs_run()
        enqueued = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        out = run_architecture_assessment_job(str(enqueued.assessment.id))
        self.assertTrue(out["ok"])
        enqueued.assessment.refresh_from_db()
        enqueued.data_run.refresh_from_db()
        self.assertEqual(
            enqueued.assessment.status,
            ArchitectureAssessment.Status.SUCCEEDED,
        )
        self.assertEqual(
            enqueued.assessment.mode,
            ArchitectureAssessment.Mode.INCOMPLETE,
        )
        self.assertEqual(enqueued.data_run.status, DataRun.Status.SUCCEEDED)
        # Phase B (0.6) + C empty (0.2) + F empty (0.2) → ~0.3333
        self.assertAlmostEqual(float(enqueued.assessment.evidence_coverage), 0.3333, places=3)
        self.assertFalse(out["graph_complete"])
        self.assertIn("WF-04", out["probes"])
        self.assertIn("WF-09", out["probes"])
        self.assertIn("WF-12", out["probes"])

    @patch("dataruns.architecture.runner.run_phase_b_inventory")
    def test_runner_persists_inventory_assets(self, mock_inventory):
        from dataruns.architecture.inventory import InventoryAsset, InventoryResult, ProbeOutcome
        from dataruns.architecture.models import (
            ArchitectureAsset,
            ArchitectureEdge,
            ArchitectureProbeResult,
        )

        mock_inventory.return_value = InventoryResult(
            assets=[
                InventoryAsset(
                    asset_id="wf:welcome",
                    asset_type="WORKFLOW",
                    name="Welcome",
                    status="active",
                    definition={
                        "trigger": "tag:vip added",
                        "tags": ["vip"],
                        "raw_keys": ["externalId", "name", "trigger", "tags"],
                    },
                ),
                InventoryAsset(
                    asset_id="tag:vip",
                    asset_type="TAG",
                    name="vip",
                    status="active",
                ),
            ],
            probes=[
                ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 1}),
                ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 1}),
                ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
            ],
            evidence_coverage=0.6,
        )
        self._connect_manago()
        dcs = self._dcs_run()
        enqueued = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        out = run_architecture_assessment_job(str(enqueued.assessment.id))
        self.assertTrue(out["ok"])
        self.assertEqual(out["asset_count"], 2)
        self.assertGreaterEqual(out["edge_count"], 1)
        self.assertEqual(
            ArchitectureAsset.objects.filter(assessment=enqueued.assessment).count(),
            2,
        )
        self.assertEqual(
            ArchitectureProbeResult.objects.filter(assessment=enqueued.assessment).count(),
            13,
        )
        self.assertGreaterEqual(
            ArchitectureEdge.objects.filter(assessment=enqueued.assessment).count(),
            1,
        )
        edge = ArchitectureEdge.objects.filter(assessment=enqueued.assessment).first()
        self.assertEqual(edge.source_asset_id, "wf:welcome")
        self.assertEqual(edge.target_asset_id, "tag:vip")
        from dataruns.architecture.models import ArchitectureAssetVerdict

        self.assertEqual(
            ArchitectureAssetVerdict.objects.filter(assessment=enqueued.assessment).count(),
            2,
        )
        self.assertEqual(out["verdict_count"], 2)
        self.assertEqual(out["mode"], ArchitectureAssessment.Mode.INCOMPLETE)
        self.assertIn("WF-12", out["probes"])
        # Welcome workflow should map to onboarding (stage_04)
        welcome = ArchitectureAsset.objects.get(
            assessment=enqueued.assessment, asset_id="wf:welcome"
        )
        self.assertEqual(welcome.lifecycle_stage, "stage_04")


class ArchitectureInventoryUnitTests(TestCase):
    def test_inventory_workflows_maps_rows(self):
        from dataruns.architecture.inventory import inventory_workflows

        with patch(
            "dataruns.architecture.inventory._fetch_workflows",
            return_value=(
                [{"externalId": "wf-1", "name": "Cart", "status": "ACTIVE"}],
                None,
            ),
        ):
            outcome = inventory_workflows(
                endpoint="https://example.test/",
                client_id="cid",
                api_secret="secret",
            )
        self.assertEqual(outcome.probe_id, "WF-01")
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(len(outcome.assets), 1)
        self.assertEqual(outcome.assets[0].asset_id, "wf:wf-1")
        self.assertEqual(outcome.assets[0].asset_type, "WORKFLOW")

    def test_inventory_tags_partial_without_segments(self):
        from dataruns.architecture.inventory import inventory_tags

        with patch(
            "dataruns.architecture.inventory._fetch_contact_tags",
            return_value=([{"tag": "vip", "numberOfTagged": 12}], None),
        ):
            outcome = inventory_tags(
                endpoint="https://example.test/",
                client_id="cid",
                api_secret="secret",
                owner="owner@example.com",
            )
        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.assets[0].asset_id, "tag:vip")
        self.assertEqual(outcome.evidence["segments"], "incomplete_no_list_api")


class ArchitectureGraphUnitTests(TestCase):
    def test_graph_builds_reads_edges_from_workflow_definition(self):
        from dataruns.architecture.graph import run_phase_c_graph
        from dataruns.architecture.inventory import InventoryAsset

        assets = [
            InventoryAsset(
                asset_id="wf:cart",
                asset_type="WORKFLOW",
                name="Cart",
                definition={
                    "trigger": "TAG_ADDED:vip",
                    "tags": ["vip"],
                    "properties": ["ltv"],
                    "raw_keys": ["trigger", "tags", "properties"],
                },
            ),
            InventoryAsset(asset_id="tag:vip", asset_type="TAG", name="vip"),
            InventoryAsset(asset_id="prop:ltv", asset_type="PROPERTY", name="ltv"),
        ]
        result = run_phase_c_graph(assets=assets)
        self.assertFalse(result.graph_complete)  # segments missing
        targets = {(e.source_asset_id, e.target_asset_id, e.edge_type) for e in result.edges}
        self.assertIn(("wf:cart", "tag:vip", "READS"), targets)
        self.assertIn(("wf:cart", "prop:ltv", "READS"), targets)
        probe_ids = {p.probe_id for p in result.probes}
        self.assertEqual(probe_ids, {"WF-04", "WF-09", "TAG-04", "PROP-04"})
        tag04 = next(p for p in result.probes if p.probe_id == "TAG-04")
        self.assertEqual(tag04.status, "partial")
        self.assertEqual(tag04.evidence["referenced_count"], 1)


class ArchitectureLatestApiTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.tenant = Tenant.objects.create(name="Acme AF API", slug="acme-af-api")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme AF API",
            domain="acme-af-api.com",
        )
        self.viewer = User.objects.create_user(
            email="viewer-af@acme.com",
            password="TestPass123!",
            name="Viewer",
            tenant=self.tenant,
            role=User.Role.VIEWER,
            email_verified=True,
            is_active=True,
        )

    def test_latest_empty_state(self):
        request = self.factory.get("/api/v1/architecture/assessments/latest/")
        force_authenticate(request, user=self.viewer)
        response = ArchitectureLatestView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["assessment"])
        self.assertEqual(response.data["ui_status"], "waiting_for_score")
        self.assertIsNone(response.data["overview"])
        self.assertIn("Architecture updates automatically", response.data["message"])

    def test_latest_returns_assessment(self):
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )
        dcs = DataRun.objects.create(
            tenant=self.tenant,
            name="DCS Score",
            status=DataRun.Status.SUCCEEDED,
            metadata={"kind": DCS_SCORE_KIND},
        )
        result = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        with patch("dataruns.architecture.runner.run_phase_b_inventory") as mock_inventory:
            from dataruns.architecture.inventory import InventoryResult, ProbeOutcome

            mock_inventory.return_value = InventoryResult(
                assets=[],
                probes=[
                    ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 0}),
                    ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 0}),
                    ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
                ],
                evidence_coverage=0.6,
            )
            run_architecture_assessment_job(str(result.assessment.id))

        request = self.factory.get("/api/v1/architecture/assessments/latest/")
        force_authenticate(request, user=self.viewer)
        response = ArchitectureLatestView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["assessment"]["assessment_id"],
            str(result.assessment.id),
        )
        self.assertEqual(response.data["assessment"]["mode"], "INCOMPLETE")
        self.assertEqual(response.data["assessment"]["status"], "succeeded")
        self.assertEqual(response.data["ui_status"], "incomplete_map")
        self.assertEqual(response.data["ui_status_label"], "Incomplete map")
        self.assertIsNotNone(response.data["overview"])
        self.assertIn("fix-first", response.data["overview"]["summary_line"])
        self.assertIsNotNone(response.data["lifecycle"])
        self.assertIn("workflows", response.data["lifecycle"]["workflow_line"])
        self.assertIsNotNone(response.data["opportunities"])
        self.assertIn("gaps", response.data["opportunities"])

    @patch("dataruns.architecture.runner.run_phase_b_inventory")
    def test_graph_api_returns_nodes_and_edges(self, mock_inventory):
        from dataruns.architecture.inventory import InventoryAsset, InventoryResult, ProbeOutcome
        from dataruns.architecture.views import ArchitectureAssessmentGraphView

        mock_inventory.return_value = InventoryResult(
            assets=[
                InventoryAsset(
                    asset_id="wf:a",
                    asset_type="WORKFLOW",
                    name="A",
                    definition={"tags": ["vip"], "trigger": "vip", "raw_keys": ["tags", "trigger"]},
                ),
                InventoryAsset(asset_id="tag:vip", asset_type="TAG", name="vip"),
            ],
            probes=[
                ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 1}),
                ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 1}),
                ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
            ],
            evidence_coverage=0.6,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )
        dcs = DataRun.objects.create(
            tenant=self.tenant,
            name="DCS Score",
            status=DataRun.Status.SUCCEEDED,
            metadata={"kind": DCS_SCORE_KIND},
        )
        enqueued = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        run_architecture_assessment_job(str(enqueued.assessment.id))

        request = self.factory.get(
            f"/api/v1/architecture/assessments/{enqueued.assessment.id}/graph/"
        )
        force_authenticate(request, user=self.viewer)
        response = ArchitectureAssessmentGraphView.as_view()(
            request, assessment_id=str(enqueued.assessment.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["node_count"], 2)
        self.assertGreaterEqual(response.data["edge_count"], 1)
        self.assertFalse(response.data["graph_complete"])
        self.assertEqual(len(response.data["nodes"]), 2)
        self.assertTrue(any(e["target_asset_id"] == "tag:vip" for e in response.data["edges"]))

    @patch("dataruns.architecture.runner.run_phase_b_inventory")
    def test_coverage_api_returns_sheet07_map(self, mock_inventory):
        from dataruns.architecture.inventory import InventoryAsset, InventoryResult, ProbeOutcome
        from dataruns.architecture.models import ArchitectureAsset
        from dataruns.architecture.views import ArchitectureAssessmentCoverageView

        mock_inventory.return_value = InventoryResult(
            assets=[
                InventoryAsset(
                    asset_id="wf:welcome",
                    asset_type="WORKFLOW",
                    name="Welcome",
                    status="active",
                    definition={"trigger": "opt-in"},
                ),
            ],
            probes=[
                ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 1}),
                ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 0}),
                ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
            ],
            evidence_coverage=0.6,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )
        dcs = DataRun.objects.create(
            tenant=self.tenant,
            name="DCS Score",
            status=DataRun.Status.SUCCEEDED,
            metadata={"kind": DCS_SCORE_KIND},
        )
        enqueued = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        run_architecture_assessment_job(str(enqueued.assessment.id))
        ArchitectureAsset.objects.filter(
            assessment=enqueued.assessment,
            asset_id="wf:welcome",
        ).update(lifecycle_stage="stage_02")

        request = self.factory.get(
            f"/api/v1/architecture/assessments/{enqueued.assessment.id}/coverage/",
            {"horizon": "quarter"},
        )
        force_authenticate(request, user=self.viewer)
        response = ArchitectureAssessmentCoverageView.as_view()(
            request, assessment_id=str(enqueued.assessment.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["stage_count"], 16)
        self.assertEqual(response.data["horizon"], "quarter")
        self.assertEqual(response.data["covered_stage_count"], 1)
        self.assertEqual(response.data["coverage_gap_count"], 15)
        self.assertEqual(len(response.data["stages"]), 16)
        self.assertEqual(len(response.data["fe_phase_cards"]), 5)
        stage2 = next(s for s in response.data["stages"] if s["stage_id"] == "stage_02")
        self.assertEqual(stage2["asset_count"], 1)
        self.assertFalse(stage2["gap"])
        acq = next(c for c in response.data["fe_phase_cards"] if c["fe_phase_key"] == "acq")
        self.assertEqual(acq["asset_count"], 1)

    @patch("dataruns.architecture.runner.run_phase_b_inventory")
    def test_gaps_api_returns_wf12_opportunities(self, mock_inventory):
        from dataruns.architecture.inventory import InventoryAsset, InventoryResult, ProbeOutcome
        from dataruns.architecture.views import ArchitectureAssessmentGapsView

        mock_inventory.return_value = InventoryResult(
            assets=[
                InventoryAsset(
                    asset_id="wf:welcome",
                    asset_type="WORKFLOW",
                    name="Welcome",
                    status="active",
                    definition={"trigger": "opt-in"},
                ),
            ],
            probes=[
                ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 1}),
                ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 0}),
                ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
            ],
            evidence_coverage=0.6,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )
        dcs = DataRun.objects.create(
            tenant=self.tenant,
            name="DCS Score",
            status=DataRun.Status.SUCCEEDED,
            metadata={"kind": DCS_SCORE_KIND},
        )
        enqueued = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        run_architecture_assessment_job(str(enqueued.assessment.id))

        request = self.factory.get(
            f"/api/v1/architecture/assessments/{enqueued.assessment.id}/gaps/"
        )
        force_authenticate(request, user=self.viewer)
        response = ArchitectureAssessmentGapsView.as_view()(
            request, assessment_id=str(enqueued.assessment.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data["gap_count"], 0)
        self.assertEqual(response.data["count"], response.data["gap_count"])
        self.assertTrue(response.data["results"])
        self.assertIn("stage_id", response.data["results"][0])


class ArchitectureVerdictUnitTests(TestCase):
    def test_fix_first_joins_consent_fail(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.verdicts import (
            DcsJoin,
            ImpairedCheck,
            assign_asset_verdicts,
        )

        assets = [
            InventoryAsset(
                asset_id="wf:a",
                asset_type="WORKFLOW",
                name="A",
                status="active",
                definition={"trigger": "purchase"},
            ),
            InventoryAsset(asset_id="tag:vip", asset_type="TAG", name="vip", status="active"),
        ]
        dcs = DcsJoin(
            checks=[ImpairedCheck(check_id="CC-07", status="FAIL")],
            source_dcs_data_run_id=1,
        )
        verdicts, _probes = assign_asset_verdicts(
            assets=assets,
            edges=[],
            dcs=dcs,
            graph_complete=False,
        )
        by_id = {v.asset_id: v for v in verdicts}
        self.assertEqual(by_id["wf:a"].verdict, "FIX_FIRST")
        self.assertEqual(by_id["wf:a"].dcs_check_ids, ["CC-07"])
        # Tag not consent-impaired directly
        self.assertNotEqual(by_id["tag:vip"].verdict, "FIX_FIRST")

    def test_retire_blocked_when_graph_incomplete(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.verdicts import DcsJoin, assign_asset_verdicts

        assets = [
            InventoryAsset(
                asset_id="tag:orphan",
                asset_type="TAG",
                name="orphan",
                status="active",
            ),
        ]
        verdicts, _ = assign_asset_verdicts(
            assets=assets,
            edges=[],
            dcs=DcsJoin(),
            graph_complete=False,
        )
        row = verdicts[0]
        self.assertEqual(row.verdict, "KEEP")
        self.assertEqual(row.failure_code, "GRAPH_GATE")

    def test_retire_allowed_when_graph_complete(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.verdicts import DcsJoin, assign_asset_verdicts

        assets = [
            InventoryAsset(
                asset_id="tag:orphan",
                asset_type="TAG",
                name="orphan",
                status="active",
            ),
        ]
        verdicts, _ = assign_asset_verdicts(
            assets=assets,
            edges=[],
            dcs=DcsJoin(),
            graph_complete=True,
        )
        self.assertEqual(verdicts[0].verdict, "RETIRE_CANDIDATE")

    def test_mode_incomplete_below_coverage_gate(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.verdicts import (
            AssetVerdictRow,
            DcsJoin,
            rollup_mode,
        )

        mode, score, _crit, detail = rollup_mode(
            evidence_coverage=0.5,
            graph_complete=True,
            verdicts=[
                AssetVerdictRow(asset_id="wf:a", verdict="KEEP"),
            ],
            assets=[InventoryAsset(asset_id="wf:a", asset_type="WORKFLOW", name="A")],
            dcs=DcsJoin(),
        )
        self.assertEqual(mode, "INCOMPLETE")
        self.assertIsNone(score)
        self.assertEqual(detail["gate"], "coverage")

    def test_mode_augment_when_healthy_and_complete(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.verdicts import (
            AssetVerdictRow,
            DcsJoin,
            rollup_mode,
        )

        assets = [
            InventoryAsset(asset_id=f"wf:{i}", asset_type="WORKFLOW", name=f"W{i}")
            for i in range(4)
        ]
        verdicts = [
            AssetVerdictRow(asset_id=a.asset_id, verdict="KEEP") for a in assets
        ]
        mode, score, crit, detail = rollup_mode(
            evidence_coverage=0.9,
            graph_complete=True,
            verdicts=verdicts,
            assets=assets,
            dcs=DcsJoin(),
        )
        self.assertEqual(mode, "AUGMENT")
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score, 70)
        self.assertEqual(crit, 0)
        self.assertEqual(detail["gate"], "weighted_score")


class ArchitectureVerdictRunnerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme AF D", slug="acme-af-d")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Acme AF D",
            domain="acme-af-d.com",
        )

    @patch("dataruns.architecture.runner.run_phase_b_inventory")
    def test_runner_loads_dcs_qa_checks_for_fix_first(self, mock_inventory):
        from dataruns.architecture.inventory import InventoryAsset, InventoryResult, ProbeOutcome
        from dataruns.architecture.models import ArchitectureAssetVerdict
        from dataruns.models import QaCheck, Run

        domain_run = Run.objects.create(
            company=self.company,
            run_type=Run.RunType.FULL,
            status=Run.Status.COMPLETED,
        )
        QaCheck.objects.create(
            run=domain_run,
            check_type="CC-07",
            result="FAIL",
            details={},
        )
        mock_inventory.return_value = InventoryResult(
            assets=[
                InventoryAsset(
                    asset_id="wf:welcome",
                    asset_type="WORKFLOW",
                    name="Welcome",
                    status="active",
                    definition={"trigger": "signup", "raw_keys": ["trigger"]},
                ),
            ],
            probes=[
                ProbeOutcome(probe_id="WF-01", status="succeeded", evidence={"count": 1}),
                ProbeOutcome(probe_id="TAG-01", status="partial", evidence={"tags_count": 0}),
                ProbeOutcome(probe_id="PROP-01", status="incomplete", evidence={"count": 0}),
            ],
            evidence_coverage=0.6,
        )
        Connector.objects.create(
            company=self.company,
            name="manago_ai",
            type="cdp",
            status="connected",
            config={},
        )
        dcs = DataRun.objects.create(
            tenant=self.tenant,
            name="DCS Score",
            status=DataRun.Status.SUCCEEDED,
            metadata={"kind": DCS_SCORE_KIND, "run_id": str(domain_run.id)},
        )
        enqueued = enqueue_architecture_assessment(
            self.company,
            source_dcs_data_run=dcs,
            queue=False,
        )
        out = run_architecture_assessment_job(str(enqueued.assessment.id))
        self.assertTrue(out["ok"])
        row = ArchitectureAssetVerdict.objects.get(
            assessment=enqueued.assessment,
            asset_id="wf:welcome",
        )
        self.assertEqual(row.verdict, "FIX_FIRST")
        self.assertEqual(row.dcs_check_ids, ["CC-07"])


class ArchitectureWf12UnitTests(TestCase):
    def test_infers_welcome_and_vip_stages(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.wf12 import infer_lifecycle_stage, run_phase_f_coverage

        assets = [
            InventoryAsset(
                asset_id="wf:welcome",
                asset_type="WORKFLOW",
                name="Welcome series",
                definition={"trigger": "opt-in"},
            ),
            InventoryAsset(asset_id="tag:vip", asset_type="TAG", name="vip"),
            InventoryAsset(
                asset_id="prop:ORDER_AVG",
                asset_type="PROPERTY",
                name="ORDER_AVG",
            ),
            InventoryAsset(
                asset_id="wf:other",
                asset_type="WORKFLOW",
                name="Misc automation",
                definition={"trigger": "unknown_event"},
            ),
        ]
        self.assertEqual(infer_lifecycle_stage(assets[0]), "stage_04")
        self.assertEqual(infer_lifecycle_stage(assets[1]), "stage_12")
        self.assertEqual(infer_lifecycle_stage(assets[2]), "stage_04")
        self.assertIsNone(infer_lifecycle_stage(assets[3]))

        result = run_phase_f_coverage(assets=assets)
        self.assertEqual(result.probes[0].probe_id, "WF-12")
        self.assertIn("stage_04", result.covered_stage_ids)
        self.assertIn("stage_12", result.covered_stage_ids)
        self.assertGreater(result.probes[0].evidence["coverage_gap_count"], 0)
        self.assertTrue(result.gaps)
        mapped = {a.asset_id: a.lifecycle_stage for a in result.assets}
        self.assertEqual(mapped["wf:welcome"], "stage_04")
        self.assertEqual(mapped["tag:vip"], "stage_12")

    def test_workflow_tags_in_definition_do_not_steal_stage(self):
        from dataruns.architecture.inventory import InventoryAsset
        from dataruns.architecture.wf12 import infer_lifecycle_stage

        # Name has no lifecycle keyword; tags/segments in definition must not map it.
        asset = InventoryAsset(
            asset_id="wf:daily",
            asset_type="WORKFLOW",
            name="Daily Automation",
            definition={
                "trigger": "schedule.daily",
                "tags": ["winback", "vip"],
                "segments": ["churn_risk"],
            },
        )
        self.assertIsNone(infer_lifecycle_stage(asset))
