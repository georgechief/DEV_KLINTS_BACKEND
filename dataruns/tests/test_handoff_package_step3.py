"""PRD-HO-01 Step 3 — stage handoff on QA PASS + idempotent create."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.handoff_package import (
    AUDIT_ACTION_HANDOFF_STAGED,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_STATUS_STAGED,
)
from dataruns.use_cases.handoff_stage import (
    HandoffStageError,
    create_or_get_staged_handoff,
    stage_handoff_for_package,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import (
    HandoffPackage,
    UseCasePilot,
    WorkflowBuildPackage,
    WorkflowQaResult,
)
from dataruns.use_cases.qa_result import QA_STATUS_FAIL, QA_STATUS_PASS
from dataruns.use_cases.qa_run import (
    AUDIT_ACTION_QA_RUN_COMPLETED,
    run_qa_for_package,
)
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from tenants.models import Company, Tenant, User


class HandoffPackageStep3StageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="HO Step3", slug="ho-step3")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="HO Step3 Co",
            domain="ho-step3.example.com",
        )
        cls.user = User.objects.create_user(
            email="ho-step3@example.com",
            password="test-pass-123",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.pilot = (
            UseCasePilot.objects.select_related("blueprint").get(use_case_id="UC-02")
        )
        cls.blueprint = cls.pilot.blueprint
        body = cls.blueprint.body if isinstance(cls.blueprint.body, dict) else {}
        gates = _gates_from_blueprint(body)
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
            package_id="00000000-0000-0000-0000-000000000003",
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

    def _persist_package(self, payload: dict | None = None) -> WorkflowBuildPackage:
        body = deepcopy(payload or self.golden_payload)
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=body,
            provisional_supplemental=bool(body.get("provisional_supplemental")),
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(body.get("hashes") or {}).get(
                "package_content_hash", "c" * 64
            ),
            generated_by=self.user,
        )
        body["package_id"] = str(record.id)
        record.payload = body
        record.save(update_fields=["payload"])
        return (
            WorkflowBuildPackage.objects.select_related("pilot", "pilot__blueprint")
            .get(pk=record.pk)
        )

    def _qa(
        self,
        package: WorkflowBuildPackage,
        *,
        status: str = QA_STATUS_PASS,
    ) -> WorkflowQaResult:
        return WorkflowQaResult.objects.create(
            company=self.company,
            package=package,
            use_case_id="UC-02",
            score=100.0 if status == QA_STATUS_PASS else 40.0,
            status=status,
            payload={"status": status, "score": 100.0},
            created_by=self.user,
        )

    def test_create_staged_on_pass(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        self.assertTrue(outcome.created)
        self.assertEqual(outcome.record.status, HANDOFF_STATUS_STAGED)
        self.assertEqual(set(outcome.payload.keys()), HANDOFF_PACKAGE_REQUIRED_FIELDS)
        self.assertEqual(outcome.payload["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(outcome.payload["qa_ref"], str(qa.id))
        self.assertEqual(HandoffPackage.objects.count(), 1)

        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["handoff_id"], str(outcome.record.id))
        self.assertEqual(audit.metadata["package_id"], str(package.id))
        self.assertEqual(audit.metadata["qa_run_id"], str(qa.id))
        self.assertEqual(audit.metadata["status"], HANDOFF_STATUS_STAGED)

    def test_idempotent_same_package_qa(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        first = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        second = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.record.id, second.record.id)
        self.assertEqual(HandoffPackage.objects.count(), 1)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            1,
        )

    def test_fail_qa_raises_409(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_FAIL)
        with self.assertRaises(HandoffStageError) as ctx:
            create_or_get_staged_handoff(
                package=package,
                qa_result=qa,
                created_by=self.user,
            )
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "qa_not_pass")
        self.assertEqual(HandoffPackage.objects.count(), 0)

    def test_stage_for_package_missing_qa_raises_409(self):
        package = self._persist_package()
        with self.assertRaises(HandoffStageError) as ctx:
            stage_handoff_for_package(package=package, created_by=self.user)
        self.assertEqual(ctx.exception.code, "qa_missing")
        self.assertEqual(ctx.exception.status, 409)

    def test_stage_for_package_uses_latest_pass(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = stage_handoff_for_package(package=package, created_by=self.user)
        self.assertTrue(outcome.created)
        self.assertEqual(outcome.record.qa_result_id, qa.id)

    def test_qa_pass_auto_creates_handoff(self):
        package = self._persist_package()
        outcome = run_qa_for_package(package=package, created_by=self.user)
        self.assertEqual(outcome.record.status, QA_STATUS_PASS)
        handoff = HandoffPackage.objects.filter(
            package=package,
            qa_result=outcome.record,
        ).first()
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff.status, HANDOFF_STATUS_STAGED)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_QA_RUN_COMPLETED,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            1,
        )

    def test_qa_fail_does_not_create_handoff(self):
        payload = deepcopy(self.golden_payload)
        payload["gates_snapshot"] = {
            "checks": {"CC-03": "FAIL"},
            "provisional_supplemental": True,
        }
        package = self._persist_package(payload)
        outcome = run_qa_for_package(package=package, created_by=self.user)
        self.assertEqual(outcome.record.status, QA_STATUS_FAIL)
        self.assertEqual(HandoffPackage.objects.count(), 0)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            0,
        )

    def test_rerun_pass_creates_second_handoff_for_new_qa(self):
        package = self._persist_package()
        first = run_qa_for_package(package=package, created_by=self.user)
        second = run_qa_for_package(package=package, created_by=self.user)
        self.assertNotEqual(first.record.id, second.record.id)
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 2)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            2,
        )

    def test_qa_package_mismatch_raises_409(self):
        package_a = self._persist_package()
        package_b = self._persist_package()
        qa = self._qa(package_a, status=QA_STATUS_PASS)
        with self.assertRaises(HandoffStageError) as ctx:
            create_or_get_staged_handoff(
                package=package_b,
                qa_result=qa,
                created_by=self.user,
            )
        self.assertEqual(ctx.exception.code, "qa_package_mismatch")
        self.assertEqual(ctx.exception.status, 409)

    def test_latest_fail_blocks_stage_for_package(self):
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)
        fail_qa = self._qa(package, status=QA_STATUS_FAIL)
        # Ensure FAIL is strictly latest (created_at ties + UUID order are nondeterministic).
        WorkflowQaResult.objects.filter(pk=fail_qa.pk).update(
            created_at=timezone.now() + timedelta(seconds=5)
        )
        with self.assertRaises(HandoffStageError) as ctx:
            stage_handoff_for_package(package=package, created_by=self.user)
        self.assertEqual(ctx.exception.code, "qa_not_pass")

    def test_explicit_pass_qa_run_id_ok_even_if_newer_fail(self):
        package = self._persist_package()
        pass_qa = self._qa(package, status=QA_STATUS_PASS)
        fail_qa = self._qa(package, status=QA_STATUS_FAIL)
        WorkflowQaResult.objects.filter(pk=fail_qa.pk).update(
            created_at=timezone.now() + timedelta(seconds=5)
        )
        outcome = stage_handoff_for_package(
            package=package,
            created_by=self.user,
            qa_run_id=pass_qa.id,
        )
        self.assertTrue(outcome.created)
        self.assertEqual(outcome.record.qa_result_id, pass_qa.id)

    def test_payload_created_at_matches_column(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        self.assertEqual(
            outcome.record.payload["created_at"],
            outcome.payload["created_at"],
        )
        self.assertEqual(
            outcome.payload["provenance"]["created_at"],
            outcome.payload["created_at"],
        )
        self.assertIn(str(package.id), outcome.payload["artifact_refs"])
        self.assertEqual(outcome.payload["approval_ref"], "HUMAN_FALLBACK")
