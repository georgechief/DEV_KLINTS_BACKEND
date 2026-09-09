"""PRD-QA-01 Step 4 — QA run orchestrator (score §6, persist, audit)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import UseCasePilot, WorkflowBuildPackage, WorkflowQaResult
from dataruns.use_cases.qa_evaluators import HARD_TEST_IDS, HardTestResult, STATUS_FAIL, STATUS_PASS
from dataruns.use_cases.qa_result import QA_STATUS_FAIL, QA_STATUS_PASS
from dataruns.use_cases.qa_run import (
    AUDIT_ACTION_QA_RUN_COMPLETED,
    QaRunError,
    compute_qa_score,
    resolve_qa_requirements,
    run_qa_for_package,
)
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from tenants.models import Company, Tenant, User


class QaRunStep4Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="QA Run", slug="qa-run")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="QA Run Co",
            domain="qa-run.example.com",
        )
        cls.user = User.objects.create_user(
            email="qa-run@example.com",
            password="test-pass-123",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.pilot = (
            UseCasePilot.objects.select_related("blueprint").get(use_case_id="UC-02")
        )
        cls.blueprint = cls.pilot.blueprint
        cls.body = cls.blueprint.body if isinstance(cls.blueprint.body, dict) else {}
        gates = _gates_from_blueprint(cls.body)
        ctx = RecommendationContext(
            headline_score=85.0,
            score_ready=True,
            dcs_data_run_id=1,
            check_results={"CC-03": "PASS"},
            af_mode="AUGMENT",
            af_assessment_id=None,
            gap_stage_ids=[],
            as_of=timezone.now(),
        )
        gates_snapshot = build_gates_snapshot(
            gates=gates,
            ctx=ctx,
            provisional_supplemental=True,
        )
        cls.golden_payload = assemble_build_package_payload(
            package_id="00000000-0000-0000-0000-000000000004",
            pilot=cls.pilot,
            blueprint=cls.blueprint,
            company=cls.company,
            ctx_snapshot={
                "dcs_data_run_id": 1,
                "af_assessment_id": None,
                "af_mode": "AUGMENT",
                "headline_score": 85.0,
            },
            gates=gates,
            gates_snapshot=gates_snapshot,
            provisional_supplemental=True,
            generated_by=cls.user,
        )

    def _persist_package(self, payload: dict) -> WorkflowBuildPackage:
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=payload,
            provisional_supplemental=bool(payload.get("provisional_supplemental")),
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(payload.get("hashes") or {}).get(
                "package_content_hash", "c" * 64
            ),
            generated_by=self.user,
        )
        payload = dict(payload)
        payload["package_id"] = str(record.id)
        record.payload = payload
        record.save(update_fields=["payload"])
        return (
            WorkflowBuildPackage.objects.select_related("pilot", "pilot__blueprint")
            .get(pk=record.pk)
        )

    # --- pure score §6 ---

    def test_compute_score_all_pass(self):
        results = [
            HardTestResult(test_id=t, status=STATUS_PASS) for t in HARD_TEST_IDS
        ]
        score, status, fails = compute_qa_score(results, minimum_score=80)
        self.assertEqual(score, 100.0)
        self.assertEqual(status, QA_STATUS_PASS)
        self.assertEqual(fails, [])

    def test_compute_score_one_fail_still_overall_fail_even_if_ge_80(self):
        results = [
            HardTestResult(test_id=t, status=STATUS_PASS) for t in HARD_TEST_IDS
        ]
        results[0] = HardTestResult(test_id="data_gates_pass", status=STATUS_FAIL)
        score, status, fails = compute_qa_score(results, minimum_score=80)
        self.assertEqual(score, round(100 * 6 / 7))
        self.assertGreaterEqual(score, 80)
        self.assertEqual(status, QA_STATUS_FAIL)
        self.assertEqual(fails, ["data_gates_pass"])

    def test_compute_score_empty_is_fail(self):
        score, status, fails = compute_qa_score([], minimum_score=80)
        self.assertEqual(score, 0.0)
        self.assertEqual(status, QA_STATUS_FAIL)
        self.assertEqual(fails, [])

    def test_compute_score_all_pass_but_below_minimum_fails(self):
        results = [
            HardTestResult(test_id=t, status=STATUS_PASS) for t in HARD_TEST_IDS
        ]
        score, status, fails = compute_qa_score(results, minimum_score=101)
        self.assertEqual(score, 100.0)
        self.assertEqual(status, QA_STATUS_FAIL)
        self.assertEqual(fails, [])

    def test_resolve_qa_requirements_missing_raises(self):
        with self.assertRaises(QaRunError) as ctx:
            resolve_qa_requirements({"use_case_id": "UC-02"})
        self.assertEqual(ctx.exception.code, "qa_requirements_missing")
        self.assertEqual(ctx.exception.status, 409)

    def test_resolve_qa_requirements_null_minimum_defaults(self):
        ids, minimum = resolve_qa_requirements(
            {
                "qa_requirements": {
                    "minimum_score": None,
                    "hard_tests": list(HARD_TEST_IDS),
                }
            }
        )
        self.assertEqual(ids, list(HARD_TEST_IDS))
        self.assertEqual(minimum, 80.0)

    def test_resolve_empty_hard_tests_stays_empty(self):
        ids, minimum = resolve_qa_requirements(
            {"qa_requirements": {"minimum_score": 80, "hard_tests": []}}
        )
        self.assertEqual(ids, [])
        self.assertEqual(minimum, 80.0)

    def test_resolve_missing_hard_tests_key_uses_evaluator_default(self):
        ids, _ = resolve_qa_requirements(
            {"qa_requirements": {"minimum_score": 80}}
        )
        self.assertIsNone(ids)

    def test_resolve_malformed_hard_tests_raises_409(self):
        with self.assertRaises(QaRunError) as ctx:
            resolve_qa_requirements(
                {"qa_requirements": {"minimum_score": 80, "hard_tests": "bad"}}
            )
        self.assertEqual(ctx.exception.code, "qa_requirements_invalid")
        self.assertEqual(ctx.exception.status, 409)

    def test_empty_hard_tests_run_scores_fail(self):
        payload = deepcopy(self.golden_payload)
        payload["qa_requirements"] = {"minimum_score": 80, "hard_tests": []}
        package = self._persist_package(payload)
        outcome = run_qa_for_package(package=package, created_by=self.user)
        self.assertEqual(outcome.payload["status"], QA_STATUS_FAIL)
        self.assertEqual(outcome.payload["score"], 0.0)
        self.assertEqual(outcome.payload["hard_tests"], [])

    def test_uc02_golden_run_passes_and_audits(self):
        package = self._persist_package(deepcopy(self.golden_payload))
        outcome = run_qa_for_package(package=package, created_by=self.user)

        self.assertEqual(outcome.payload["status"], QA_STATUS_PASS)
        self.assertEqual(outcome.payload["score"], 100.0)
        self.assertEqual(outcome.payload["minimum_score"], 80.0)
        self.assertEqual(len(outcome.payload["hard_tests"]), 7)
        self.assertTrue(
            all(row["status"] == "PASS" for row in outcome.payload["hard_tests"])
        )
        self.assertTrue(outcome.payload["evidence"])
        for ev in outcome.payload["evidence"]:
            self.assertNotIn("id", ev)

        self.assertEqual(WorkflowQaResult.objects.filter(package=package).count(), 1)
        self.assertEqual(outcome.record.status, QA_STATUS_PASS)
        # Stored payload created_at must match the column (auto_now_add), not a
        # pre-create wall clock that Django would ignore on insert.
        self.assertEqual(
            outcome.record.payload["created_at"],
            outcome.payload["created_at"],
        )

        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_QA_RUN_COMPLETED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["package_id"], str(package.id))
        self.assertEqual(audit.metadata["qa_run_id"], str(outcome.record.id))
        self.assertEqual(audit.metadata["score"], 100.0)
        self.assertEqual(audit.metadata["status"], "PASS")
        self.assertEqual(audit.metadata["hard_fail_ids"], [])
        self.assertEqual(audit.tone, AuditLog.Tone.REVENUE)

    def test_hard_fail_forces_fail_even_when_score_ge_minimum(self):
        payload = deepcopy(self.golden_payload)
        payload["gates_snapshot"] = {
            "checks": {"CC-03": "FAIL", "CC-06": "not_evaluated"},
            "provisional_supplemental": True,
        }
        package = self._persist_package(payload)
        outcome = run_qa_for_package(package=package, created_by=self.user)

        self.assertEqual(outcome.payload["status"], QA_STATUS_FAIL)
        self.assertGreaterEqual(outcome.payload["score"], 80)
        fail_ids = [
            row["test_id"]
            for row in outcome.payload["hard_tests"]
            if row["status"] == "FAIL"
        ]
        self.assertIn("data_gates_pass", fail_ids)

        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_QA_RUN_COMPLETED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["status"], "FAIL")
        self.assertIn("data_gates_pass", audit.metadata["hard_fail_ids"])
        self.assertEqual(audit.tone, AuditLog.Tone.RISK)

    def test_supplemental_fail_forces_data_gates_fail_even_when_provisional(self):
        # DCS-09 Step 9: crafted package with supplemental FAIL still fails QA.
        payload = deepcopy(self.golden_payload)
        payload["gates_snapshot"] = {
            "checks": {"CC-03": "PASS", "CC-06": "FAIL", "CI-08": "PASS"},
            "provisional_supplemental": True,
        }
        package = self._persist_package(payload)
        outcome = run_qa_for_package(package=package, created_by=self.user)

        self.assertEqual(outcome.payload["status"], QA_STATUS_FAIL)
        fail_ids = [
            row["test_id"]
            for row in outcome.payload["hard_tests"]
            if row["status"] == "FAIL"
        ]
        self.assertIn("data_gates_pass", fail_ids)

    def test_rerun_appends_history(self):
        package = self._persist_package(deepcopy(self.golden_payload))
        first = run_qa_for_package(package=package, created_by=self.user)
        second = run_qa_for_package(package=package, created_by=self.user)
        self.assertNotEqual(first.record.id, second.record.id)
        self.assertEqual(WorkflowQaResult.objects.filter(package=package).count(), 2)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_QA_RUN_COMPLETED,
            ).count(),
            2,
        )

    def test_missing_qa_requirements_raises_before_persist(self):
        package = self._persist_package({"use_case_id": "UC-02", "title": "broken"})
        with self.assertRaises(QaRunError):
            run_qa_for_package(package=package, created_by=self.user)
        self.assertEqual(WorkflowQaResult.objects.filter(package=package).count(), 0)
        self.assertFalse(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_QA_RUN_COMPLETED,
            ).exists()
        )
