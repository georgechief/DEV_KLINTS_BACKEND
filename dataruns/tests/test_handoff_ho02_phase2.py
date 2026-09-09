"""PRD-HO-02 Phase 2 — handoff_activation service tests."""

from __future__ import annotations

import uuid
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from dataruns.capabilities.contract import CAP_STATUS_DISCOVERY_REQUIRED, PACKAGE_ROUTE_HUMAN_FALLBACK
from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.handoff_activation import (
    HandoffActivationError,
    approve_handoff_for_activation,
    build_activation_guide,
    build_approve_response,
    build_capability_honesty,
    build_confirm_response,
    confirm_handoff_activated,
    get_handoff_for_activation,
    reject_handoff,
)
from dataruns.use_cases.handoff_package import (
    ACTIVATION_PATH_HUMAN_MANAGO_UI,
    AUDIT_ACTION_HANDOFF_ACTIVATED,
    AUDIT_ACTION_HANDOFF_APPROVED,
    AUDIT_ACTION_HANDOFF_REJECTED,
    HANDOFF_ERROR_FORBIDDEN,
    HANDOFF_ERROR_INVALID_TRANSITION,
    HANDOFF_ERROR_MANIFEST_MISMATCH,
    HANDOFF_ERROR_NOT_STAGED,
    HANDOFF_ERROR_QA_NOT_PASS,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_STATUS_ACTIVATED,
    HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
    HANDOFF_STATUS_REJECTED,
)
from dataruns.use_cases.handoff_stage import create_or_get_staged_handoff
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import (
    HandoffPackage,
    UseCasePilot,
    WorkflowBuildPackage,
    WorkflowQaResult,
)
from dataruns.use_cases.qa_result import QA_STATUS_FAIL, QA_STATUS_PASS
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from tenants.models import Company, Tenant, User


class HandoffHo02Phase2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="HO02 P2", slug="ho02-p2")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="HO02 P2 Co",
            domain="ho02-p2.example.com",
        )
        cls.admin = User.objects.create_user(
            email="ho02-admin@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.analyst = User.objects.create_user(
            email="ho02-analyst@example.com",
            password="pass",
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
            package_id="00000000-0000-0000-0000-000000000005",
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
            generated_by=cls.analyst,
        )

    def _persist_package(self) -> WorkflowBuildPackage:
        body = deepcopy(self.golden_payload)
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=body,
            provisional_supplemental=True,
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(body.get("hashes") or {}).get(
                "package_content_hash", "f" * 64
            ),
            generated_by=self.analyst,
        )
        body["package_id"] = str(record.id)
        record.payload = body
        record.save(update_fields=["payload"])
        return record

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
            payload={"status": status},
            created_by=self.analyst,
        )

    def _staged_handoff(self) -> HandoffPackage:
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.analyst,
        )
        return HandoffPackage.objects.select_related(
            "package",
            "package__pilot",
            "qa_result",
            "company",
        ).get(pk=outcome.record.id)

    def test_approve_staged_transitions_and_audits(self):
        record = self._staged_handoff()
        manifest_hash = record.manifest_hash

        outcome = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=manifest_hash,
            notes="ready to activate",
        )

        self.assertFalse(outcome.idempotent)
        self.assertEqual(outcome.record.status, HANDOFF_STATUS_APPROVED_FOR_ACTIVATION)
        self.assertEqual(
            outcome.record.payload["status"],
            HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
        )
        self.assertTrue(
            str(outcome.record.payload["approval_ref"]).startswith(
                "HUMAN_ACTIVATION_APPROVED:"
            )
        )
        self.assertEqual(
            outcome.record.activation_meta["path"],
            ACTIVATION_PATH_HUMAN_MANAGO_UI,
        )
        self.assertEqual(outcome.record.activation_meta["notes"], "ready to activate")

        guide = outcome.activation_guide or {}
        self.assertEqual(guide["path"], ACTIVATION_PATH_HUMAN_MANAGO_UI)
        self.assertIn("human_guide", guide)
        self.assertEqual(guide["use_case_id"], "UC-02")

        capability = outcome.capability or {}
        self.assertEqual(
            capability["mcp_publish_status"],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )
        self.assertEqual(capability["route"], PACKAGE_ROUTE_HUMAN_FALLBACK)

        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_APPROVED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["status"], HANDOFF_STATUS_APPROVED_FOR_ACTIVATION)
        self.assertEqual(audit.metadata["path"], ACTIVATION_PATH_HUMAN_MANAGO_UI)

    def test_approve_idempotent_no_duplicate_audit(self):
        record = self._staged_handoff()
        manifest_hash = record.manifest_hash

        first = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=manifest_hash,
        )
        second = approve_handoff_for_activation(
            record=first.record,
            actor=self.admin,
            manifest_hash=manifest_hash,
        )

        self.assertTrue(second.idempotent)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_APPROVED,
            ).count(),
            1,
        )

    def test_approve_manifest_mismatch(self):
        record = self._staged_handoff()
        with self.assertRaises(HandoffActivationError) as ctx:
            approve_handoff_for_activation(
                record=record,
                actor=self.admin,
                manifest_hash="a" * 64,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_MANIFEST_MISMATCH)

    def test_approve_forbidden_for_analyst(self):
        record = self._staged_handoff()
        with self.assertRaises(HandoffActivationError) as ctx:
            approve_handoff_for_activation(
                record=record,
                actor=self.analyst,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_FORBIDDEN)
        self.assertEqual(ctx.exception.status, 403)

    def test_approve_qa_not_pass(self):
        record = self._staged_handoff()
        record.qa_result.status = QA_STATUS_FAIL
        record.qa_result.save(update_fields=["status"])

        with self.assertRaises(HandoffActivationError) as ctx:
            approve_handoff_for_activation(
                record=record,
                actor=self.admin,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_QA_NOT_PASS)

    def test_approve_from_rejected_invalid(self):
        record = self._staged_handoff()
        reject_handoff(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            reason="no",
        )
        record.refresh_from_db()
        with self.assertRaises(HandoffActivationError) as ctx:
            approve_handoff_for_activation(
                record=record,
                actor=self.admin,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_NOT_STAGED)

    def test_reject_from_staged_and_approved(self):
        record = self._staged_handoff()
        outcome = reject_handoff(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            reason="not ready",
        )
        self.assertEqual(outcome.record.status, HANDOFF_STATUS_REJECTED)
        self.assertEqual(
            outcome.record.payload["status"],
            HANDOFF_STATUS_REJECTED,
        )
        self.assertEqual(outcome.record.activation_meta["rejection_reason"], "not ready")
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_REJECTED,
            ).count(),
            1,
        )

        approved_record = self._staged_handoff()
        approve_handoff_for_activation(
            record=approved_record,
            actor=self.admin,
            manifest_hash=approved_record.manifest_hash,
        )
        approved_record.refresh_from_db()
        rejected = reject_handoff(
            record=approved_record,
            actor=self.admin,
            manifest_hash=approved_record.manifest_hash,
            reason="changed mind",
        )
        self.assertEqual(rejected.record.status, HANDOFF_STATUS_REJECTED)

    def test_reject_from_activated_invalid(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        confirmed = confirm_handoff_activated(
            record=approved.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        with self.assertRaises(HandoffActivationError) as ctx:
            reject_handoff(
                record=confirmed.record,
                actor=self.admin,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_INVALID_TRANSITION)

    def test_confirm_activated_flow(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        outcome = confirm_handoff_activated(
            record=approved.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            manago_workflow_external_id="wf-ext-99",
        )

        self.assertFalse(outcome.idempotent)
        self.assertEqual(outcome.record.status, HANDOFF_STATUS_ACTIVATED)
        self.assertEqual(
            outcome.record.payload["status"],
            HANDOFF_STATUS_ACTIVATED,
        )
        self.assertEqual(
            outcome.record.activation_meta["manago_workflow_external_id"],
            "wf-ext-99",
        )
        self.assertTrue(
            str(outcome.record.activation_meta["activation_ref"]).startswith(
                "HUMAN_ACTIVATION_CONFIRMED:"
            )
        )
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_ACTIVATED,
            ).count(),
            1,
        )

    def test_confirm_idempotent_no_duplicate_audit(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        first = confirm_handoff_activated(
            record=approved.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        second = confirm_handoff_activated(
            record=first.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        self.assertTrue(second.idempotent)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_ACTIVATED,
            ).count(),
            1,
        )

    def test_confirm_from_staged_not_allowed(self):
        record = self._staged_handoff()
        with self.assertRaises(HandoffActivationError) as ctx:
            confirm_handoff_activated(
                record=record,
                actor=self.admin,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_NOT_STAGED)

    def test_build_activation_guide_and_capability_helpers(self):
        record = self._staged_handoff()
        guide = build_activation_guide(record)
        capability = build_capability_honesty(record)
        self.assertEqual(guide["package_id"], str(record.package_id))
        self.assertIn("human_guide", guide)
        self.assertEqual(
            capability["mcp_publish_status"],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )

    def test_reject_allowed_when_qa_no_longer_pass(self):
        record = self._staged_handoff()
        record.qa_result.status = QA_STATUS_FAIL
        record.qa_result.save(update_fields=["status"])

        outcome = reject_handoff(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            reason="qa regressed",
        )
        self.assertEqual(outcome.record.status, HANDOFF_STATUS_REJECTED)
        self.assertEqual(outcome.record.activation_meta["rejection_reason"], "qa regressed")

    def test_approve_idempotent_skips_qa_regression_check(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        approved.record.qa_result.status = QA_STATUS_FAIL
        approved.record.qa_result.save(update_fields=["status"])

        second = approve_handoff_for_activation(
            record=approved.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        self.assertTrue(second.idempotent)

    def test_reject_idempotent_no_duplicate_audit(self):
        record = self._staged_handoff()
        first = reject_handoff(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            reason="once",
        )
        second = reject_handoff(
            record=first.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            reason="again",
        )
        self.assertTrue(second.idempotent)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_REJECTED,
            ).count(),
            1,
        )

    def test_confirm_without_prior_approve_meta_invalid(self):
        record = self._staged_handoff()
        record.status = HandoffPackage.Status.APPROVED_FOR_ACTIVATION
        record.activation_meta = {}
        record.save(update_fields=["status", "activation_meta"])

        with self.assertRaises(HandoffActivationError) as ctx:
            confirm_handoff_activated(
                record=record,
                actor=self.admin,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_INVALID_TRANSITION)

    def test_build_approve_and_confirm_response_helpers(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        approve_body = build_approve_response(approved)
        self.assertEqual(approve_body["handoff_id"], str(record.id))
        self.assertIn("activation_guide", approve_body)
        self.assertIn("capability", approve_body)

        confirmed = confirm_handoff_activated(
            record=approved.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        confirm_body = build_confirm_response(confirmed)
        self.assertEqual(confirm_body["status"], HANDOFF_STATUS_ACTIVATED)
        self.assertIn("activation_meta", confirm_body)

    def test_get_handoff_for_activation_scoped_to_company(self):
        record = self._staged_handoff()
        found = get_handoff_for_activation(
            company=self.company,
            handoff_id=record.id,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.id, record.id)

        other_tenant = Tenant.objects.create(name="Other", slug="ho02-other")
        other_company = Company.objects.create(
            tenant=other_tenant,
            name="Other Co",
            domain="other.example.com",
        )
        self.assertIsNone(
            get_handoff_for_activation(
                company=other_company,
                handoff_id=record.id,
            )
        )

    def test_confirm_qa_not_pass_after_approve(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        approved.record.qa_result.status = QA_STATUS_FAIL
        approved.record.qa_result.save(update_fields=["status"])

        with self.assertRaises(HandoffActivationError) as ctx:
            confirm_handoff_activated(
                record=approved.record,
                actor=self.admin,
                manifest_hash=record.manifest_hash,
            )
        self.assertEqual(ctx.exception.code, HANDOFF_ERROR_QA_NOT_PASS)

    def test_payload_required_fields_preserved_after_full_transition(self):
        record = self._staged_handoff()
        approved = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        for key in HANDOFF_PACKAGE_REQUIRED_FIELDS:
            self.assertIn(key, approved.record.payload)

        confirmed = confirm_handoff_activated(
            record=approved.record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
        )
        for key in HANDOFF_PACKAGE_REQUIRED_FIELDS:
            self.assertIn(key, confirmed.record.payload)

    def test_approve_stores_approval_token_id(self):
        record = self._staged_handoff()
        token_id = str(uuid.uuid4())
        outcome = approve_handoff_for_activation(
            record=record,
            actor=self.admin,
            manifest_hash=record.manifest_hash,
            approval_token_id=token_id,
        )
        self.assertEqual(
            outcome.record.activation_meta["approval_token_id"],
            token_id,
        )
