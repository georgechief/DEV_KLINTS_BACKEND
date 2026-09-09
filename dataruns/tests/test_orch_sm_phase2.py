"""PRD-GAP-01 Slice A1 Phase 2 — orchestration task service tests."""

from __future__ import annotations

from django.test import TestCase

from dataruns.models import AuditLog
from dataruns.orchestration.models import OrchestrationTask
from dataruns.orchestration.task_constants import (
    AUDIT_ACTION_ORCH_TASK_CREATED,
    AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
    ORCH_ERROR_FORBIDDEN,
    ORCH_ERROR_INVALID_TRANSITION,
    ORCH_ERROR_NOT_FOUND,
    ORCH_ERROR_VALIDATION,
    ORCH_STATUS_AWAITING_APPROVAL,
    ORCH_STATUS_CANCELLED,
    ORCH_STATUS_DONE,
    ORCH_STATUS_FAILED,
    ORCH_STATUS_IN_PROGRESS,
    ORCH_STATUS_READY,
    ORCH_TASK_TYPE_FIX,
)
from dataruns.orchestration.task_transitions import (
    OrchTransitionError,
    OrchTransitionOutcome,
    create_orchestration_task,
    get_orchestration_task,
    transition_orchestration_task,
)
from tenants.models import Company, Tenant, User


class OrchSmPhase2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name="Orch SM P2", slug="orch-sm-p2")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="Orch SM P2 Co",
            domain="orch-sm-p2.example.com",
        )
        cls.other_tenant = Tenant.objects.create(name="Orch Other", slug="orch-other")
        cls.other_company = Company.objects.create(
            tenant=cls.other_tenant,
            name="Orch Other Co",
            domain="orch-other.example.com",
        )
        cls.admin = User.objects.create_user(
            email="orch-admin@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.analyst = User.objects.create_user(
            email="orch-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="orch-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )

    def _priority_inputs(self) -> dict[str, int]:
        return {
            "blocker_status": 2,
            "severity_risk": 1,
            "dependency_readiness": 3,
            "effort_impact": 2,
        }

    def _create_task(
        self,
        *,
        actor: User | None = None,
        status: str = ORCH_STATUS_READY,
        idempotency_suffix: str = "1",
    ) -> OrchTransitionOutcome:
        return create_orchestration_task(
            company=self.company,
            actor=actor or self.analyst,
            task_id="FIX-CC-03",
            task_type=ORCH_TASK_TYPE_FIX,
            title="Fix CC-03",
            check_id="CC-03",
            status=status,
            priority_inputs=self._priority_inputs(),
            priority_score=2.1,
            idempotency_key=f"{self.company.id}:FIX-CC-03:dcs:{idempotency_suffix}",
        )

    def test_create_happy_path(self):
        outcome = self._create_task()

        self.assertFalse(outcome.idempotent)
        self.assertEqual(outcome.record.status, ORCH_STATUS_READY)
        self.assertEqual(outcome.record.task_type, ORCH_TASK_TYPE_FIX)
        self.assertEqual(outcome.record.priority_class, "P0")

        audit = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_ORCH_TASK_CREATED,
        ).latest("created_at")
        self.assertEqual(audit.metadata["task_id"], "FIX-CC-03")
        self.assertEqual(audit.metadata["status"], ORCH_STATUS_READY)
        self.assertEqual(audit.metadata["check_id"], "CC-03")

    def test_idempotent_create_one_row_one_audit(self):
        first = self._create_task()
        second = self._create_task()

        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.record.id, second.record.id)
        self.assertEqual(OrchestrationTask.objects.filter(company=self.company).count(), 1)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_ORCH_TASK_CREATED,
            ).count(),
            1,
        )

    def test_happy_path_to_done_as_admin(self):
        created = self._create_task()
        record = created.record

        in_progress = transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_IN_PROGRESS,
            reason="Started fix",
        )
        self.assertEqual(in_progress.record.status, ORCH_STATUS_IN_PROGRESS)
        self.assertEqual(
            in_progress.record.metadata["last_transition_reason"],
            "Started fix",
        )

        awaiting = transition_orchestration_task(
            record=in_progress.record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_AWAITING_APPROVAL,
        )
        self.assertEqual(awaiting.record.status, ORCH_STATUS_AWAITING_APPROVAL)

        done = transition_orchestration_task(
            record=awaiting.record,
            company=self.company,
            actor=self.admin,
            to_status=ORCH_STATUS_DONE,
            reason="Approved",
        )
        self.assertFalse(done.idempotent)
        self.assertEqual(done.record.status, ORCH_STATUS_DONE)

        transition_audits = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
        ).order_by("created_at")
        self.assertEqual(transition_audits.count(), 3)
        self.assertEqual(
            transition_audits.last().metadata["from_status"],
            ORCH_STATUS_AWAITING_APPROVAL,
        )
        self.assertEqual(
            transition_audits.last().metadata["to_status"],
            ORCH_STATUS_DONE,
        )

    def test_forbidden_transition_raises_invalid_transition(self):
        created = self._create_task(status=ORCH_STATUS_READY)
        with self.assertRaises(OrchTransitionError) as ctx:
            transition_orchestration_task(
                record=created.record,
                company=self.company,
                actor=self.analyst,
                to_status=ORCH_STATUS_DONE,
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_INVALID_TRANSITION)
        self.assertEqual(ctx.exception.status, 409)

    def test_viewer_cannot_transition(self):
        created = self._create_task()
        with self.assertRaises(OrchTransitionError) as ctx:
            transition_orchestration_task(
                record=created.record,
                company=self.company,
                actor=self.viewer,
                to_status=ORCH_STATUS_IN_PROGRESS,
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_FORBIDDEN)
        self.assertEqual(ctx.exception.status, 403)

    def test_viewer_cannot_create(self):
        with self.assertRaises(OrchTransitionError) as ctx:
            self._create_task(actor=self.viewer)
        self.assertEqual(ctx.exception.code, ORCH_ERROR_FORBIDDEN)
        self.assertEqual(ctx.exception.status, 403)

    def test_analyst_cannot_approve_to_done(self):
        created = self._create_task()
        record = created.record

        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_IN_PROGRESS,
        )
        record.refresh_from_db()
        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_AWAITING_APPROVAL,
        )
        record.refresh_from_db()

        with self.assertRaises(OrchTransitionError) as ctx:
            transition_orchestration_task(
                record=record,
                company=self.company,
                actor=self.analyst,
                to_status=ORCH_STATUS_DONE,
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_FORBIDDEN)
        self.assertEqual(ctx.exception.status, 403)

    def test_failed_to_ready_retry(self):
        created = self._create_task()
        record = created.record

        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_IN_PROGRESS,
        )
        record.refresh_from_db()
        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_FAILED,
            reason="Execution failed",
        )
        record.refresh_from_db()

        retried = transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_READY,
        )
        self.assertEqual(retried.record.status, ORCH_STATUS_READY)

    def test_create_builds_default_provenance(self):
        outcome = self._create_task(idempotency_suffix="prov")
        provenance = outcome.record.provenance
        self.assertEqual(provenance["created_by"], self.analyst.email)
        self.assertIn("created_at", provenance)
        self.assertIn("source_versions", provenance)

    def test_create_rejects_invalid_task_type(self):
        with self.assertRaises(OrchTransitionError) as ctx:
            create_orchestration_task(
                company=self.company,
                actor=self.analyst,
                task_id="FIX-CC-04",
                task_type="NOT_A_TYPE",
                priority_inputs=self._priority_inputs(),
                idempotency_key=f"{self.company.id}:FIX-CC-04:dcs:bad-type",
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_VALIDATION)
        self.assertEqual(ctx.exception.status, 400)

    def test_create_rejects_invalid_priority_inputs(self):
        with self.assertRaises(OrchTransitionError) as ctx:
            create_orchestration_task(
                company=self.company,
                actor=self.analyst,
                task_id="FIX-CC-05",
                task_type=ORCH_TASK_TYPE_FIX,
                priority_inputs=[],
                idempotency_key=f"{self.company.id}:FIX-CC-05:dcs:bad-inputs",
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_VALIDATION)
        self.assertEqual(ctx.exception.status, 400)

    def test_same_status_non_idempotent_raises_invalid_transition(self):
        created = self._create_task(status=ORCH_STATUS_READY)
        with self.assertRaises(OrchTransitionError) as ctx:
            transition_orchestration_task(
                record=created.record,
                company=self.company,
                actor=self.analyst,
                to_status=ORCH_STATUS_READY,
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_INVALID_TRANSITION)
        self.assertEqual(ctx.exception.status, 409)

    def test_idempotent_awaiting_approval_no_duplicate_audit(self):
        created = self._create_task(idempotency_suffix="await-idem")
        record = created.record

        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_IN_PROGRESS,
        )
        record.refresh_from_db()
        first = transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_AWAITING_APPROVAL,
        )
        second = transition_orchestration_task(
            record=first.record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_AWAITING_APPROVAL,
        )

        self.assertTrue(second.idempotent)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
                metadata__to_status=ORCH_STATUS_AWAITING_APPROVAL,
            ).count(),
            1,
        )

    def test_idempotent_cancelled_no_duplicate_audit(self):
        created = self._create_task(idempotency_suffix="cancel-idem")
        record = created.record

        first = transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_CANCELLED,
            reason="No longer needed",
        )
        second = transition_orchestration_task(
            record=first.record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_CANCELLED,
        )

        self.assertTrue(second.idempotent)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
                metadata__to_status=ORCH_STATUS_CANCELLED,
            ).count(),
            1,
        )

    def test_idempotent_done_no_duplicate_audit(self):
        created = self._create_task(idempotency_suffix="done-idem")
        record = created.record

        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_IN_PROGRESS,
        )
        record.refresh_from_db()
        transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.analyst,
            to_status=ORCH_STATUS_AWAITING_APPROVAL,
        )
        record.refresh_from_db()

        first_done = transition_orchestration_task(
            record=record,
            company=self.company,
            actor=self.admin,
            to_status=ORCH_STATUS_DONE,
            reason="Approved",
        )
        first_repeat = transition_orchestration_task(
            record=first_done.record,
            company=self.company,
            actor=self.admin,
            to_status=ORCH_STATUS_DONE,
        )
        second_repeat = transition_orchestration_task(
            record=first_repeat.record,
            company=self.company,
            actor=self.admin,
            to_status=ORCH_STATUS_DONE,
        )

        self.assertFalse(first_done.idempotent)
        self.assertTrue(first_repeat.idempotent)
        self.assertTrue(second_repeat.idempotent)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
                metadata__to_status=ORCH_STATUS_DONE,
            ).count(),
            1,
        )

    def test_create_rejects_terminal_status(self):
        with self.assertRaises(OrchTransitionError) as ctx:
            create_orchestration_task(
                company=self.company,
                actor=self.analyst,
                task_id="FIX-CC-06",
                task_type=ORCH_TASK_TYPE_FIX,
                status=ORCH_STATUS_DONE,
                priority_inputs=self._priority_inputs(),
                idempotency_key=f"{self.company.id}:FIX-CC-06:dcs:terminal",
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_VALIDATION)
        self.assertEqual(ctx.exception.status, 400)

    def test_create_rejects_non_list_depends_on(self):
        with self.assertRaises(OrchTransitionError) as ctx:
            create_orchestration_task(
                company=self.company,
                actor=self.analyst,
                task_id="FIX-CC-07",
                task_type=ORCH_TASK_TYPE_FIX,
                status=ORCH_STATUS_READY,
                priority_inputs=self._priority_inputs(),
                depends_on="FIX-CC-01",
                idempotency_key=f"{self.company.id}:FIX-CC-07:dcs:bad-depends",
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_VALIDATION)
        self.assertEqual(ctx.exception.status, 400)

    def test_wrong_company_not_found(self):
        created = self._create_task()
        with self.assertRaises(OrchTransitionError) as ctx:
            transition_orchestration_task(
                record=created.record,
                company=self.other_company,
                actor=self.admin,
                to_status=ORCH_STATUS_IN_PROGRESS,
            )
        self.assertEqual(ctx.exception.code, ORCH_ERROR_NOT_FOUND)
        self.assertEqual(ctx.exception.status, 404)

    def test_get_orchestration_task_scoped_to_company(self):
        created = self._create_task()
        found = get_orchestration_task(
            company=self.company,
            task_id=created.record.id,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.id, created.record.id)
        self.assertIsNone(
            get_orchestration_task(
                company=self.other_company,
                task_id=created.record.id,
            )
        )
