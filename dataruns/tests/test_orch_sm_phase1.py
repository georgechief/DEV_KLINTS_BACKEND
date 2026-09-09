"""PRD-GAP-01 Slice A1 Phase 1 — OrchestrationTask schema + constants."""

from __future__ import annotations

from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from dataruns.orchestration.models import OrchestrationTask
from dataruns.orchestration.task_constants import (
    AUDIT_ACTION_ORCH_TASK_CREATED,
    AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
    ORCH_ALLOWED_STATUS_TRANSITIONS,
    ORCH_STATUS_AWAITING_APPROVAL,
    ORCH_STATUS_BLOCKED,
    ORCH_STATUS_CANCELLED,
    ORCH_STATUS_DONE,
    ORCH_STATUS_FAILED,
    ORCH_STATUS_IN_PROGRESS,
    ORCH_STATUS_PENDING,
    ORCH_STATUS_READY,
    ORCH_STATUS_ENUM,
    ORCH_TASK_SCHEMA_VERSION,
    ORCH_TASK_TYPE_ENUM,
    ORCH_TASK_TYPE_FIX,
    ORCH_ERROR_FORBIDDEN,
    ORCH_ERROR_INVALID_TRANSITION,
    ORCH_ERROR_NOT_FOUND,
    ORCH_ERROR_VALIDATION,
    ORCH_TERMINAL_STATUSES,
    build_default_provenance,
    build_orch_task_audit_metadata,
    is_allowed_orch_transition,
    is_orch_idempotent_transition,
    is_orch_terminal_status,
    normalize_orch_priority_inputs,
    normalize_orch_status,
    normalize_orch_task_type,
    serialize_orch_task,
)
from tenants.models import Company, Tenant


class OrchSmPhase1ConstantTests(SimpleTestCase):
    def test_audit_actions_locked(self):
        self.assertEqual(
            AUDIT_ACTION_ORCH_TASK_CREATED,
            "workflow.orchestration_task_created",
        )
        self.assertEqual(
            AUDIT_ACTION_ORCH_TASK_TRANSITIONED,
            "workflow.orchestration_task_transitioned",
        )

    def test_status_and_task_type_enums(self):
        self.assertEqual(len(ORCH_STATUS_ENUM), 8)
        self.assertEqual(len(ORCH_TASK_TYPE_ENUM), 11)
        self.assertIn(ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_ENUM)
        self.assertIn(ORCH_TASK_TYPE_FIX, ORCH_TASK_TYPE_ENUM)

    def test_error_code_constants(self):
        self.assertEqual(ORCH_ERROR_INVALID_TRANSITION, "invalid_transition")
        self.assertEqual(ORCH_ERROR_FORBIDDEN, "forbidden")
        self.assertEqual(ORCH_ERROR_NOT_FOUND, "not_found")
        self.assertEqual(ORCH_ERROR_VALIDATION, "validation_error")

    def test_every_allowed_edge_permitted(self):
        for from_status, to_status in ORCH_ALLOWED_STATUS_TRANSITIONS:
            self.assertTrue(
                is_allowed_orch_transition(
                    from_status=from_status,
                    to_status=to_status,
                ),
                msg=f"{from_status} -> {to_status} must be allowed",
            )

    def test_allowed_transitions_locked(self):
        expected = {
            (ORCH_STATUS_PENDING, ORCH_STATUS_READY),
            (ORCH_STATUS_PENDING, ORCH_STATUS_BLOCKED),
            (ORCH_STATUS_PENDING, ORCH_STATUS_CANCELLED),
            (ORCH_STATUS_BLOCKED, ORCH_STATUS_READY),
            (ORCH_STATUS_BLOCKED, ORCH_STATUS_CANCELLED),
            (ORCH_STATUS_READY, ORCH_STATUS_IN_PROGRESS),
            (ORCH_STATUS_READY, ORCH_STATUS_CANCELLED),
            (ORCH_STATUS_IN_PROGRESS, ORCH_STATUS_AWAITING_APPROVAL),
            (ORCH_STATUS_IN_PROGRESS, ORCH_STATUS_DONE),
            (ORCH_STATUS_IN_PROGRESS, ORCH_STATUS_FAILED),
            (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_IN_PROGRESS),
            (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_DONE),
            (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_FAILED),
            (ORCH_STATUS_AWAITING_APPROVAL, ORCH_STATUS_CANCELLED),
            (ORCH_STATUS_FAILED, ORCH_STATUS_READY),
            (ORCH_STATUS_FAILED, ORCH_STATUS_CANCELLED),
        }
        self.assertEqual(ORCH_ALLOWED_STATUS_TRANSITIONS, expected)
        self.assertFalse(
            is_allowed_orch_transition(
                from_status=ORCH_STATUS_PENDING,
                to_status=ORCH_STATUS_DONE,
            )
        )
        self.assertFalse(
            is_allowed_orch_transition(
                from_status=ORCH_STATUS_DONE,
                to_status=ORCH_STATUS_READY,
            )
        )
        self.assertTrue(
            is_allowed_orch_transition(
                from_status=ORCH_STATUS_FAILED,
                to_status=ORCH_STATUS_READY,
            )
        )

    def test_terminal_and_idempotent_helpers(self):
        self.assertTrue(is_orch_terminal_status(ORCH_STATUS_DONE))
        self.assertTrue(is_orch_terminal_status(ORCH_STATUS_CANCELLED))
        self.assertFalse(is_orch_terminal_status(ORCH_STATUS_READY))
        self.assertTrue(
            is_orch_idempotent_transition(
                current_status=ORCH_STATUS_DONE,
                target_status=ORCH_STATUS_DONE,
            )
        )
        self.assertTrue(
            is_orch_idempotent_transition(
                current_status=ORCH_STATUS_AWAITING_APPROVAL,
                target_status=ORCH_STATUS_AWAITING_APPROVAL,
            )
        )
        self.assertFalse(
            is_orch_idempotent_transition(
                current_status=ORCH_STATUS_READY,
                target_status=ORCH_STATUS_READY,
            )
        )

    def test_normalize_status_and_task_type(self):
        self.assertEqual(normalize_orch_status("ready"), ORCH_STATUS_READY)
        self.assertEqual(normalize_orch_task_type("fix"), ORCH_TASK_TYPE_FIX)
        with self.assertRaises(ValueError):
            normalize_orch_status("NOT_A_STATUS")
        with self.assertRaises(ValueError):
            normalize_orch_task_type("NOT_A_TYPE")

    def test_build_default_provenance(self):
        prov = build_default_provenance(created_by="admin@example.com")
        self.assertEqual(prov["created_by"], "admin@example.com")
        self.assertIn("created_at", prov)
        self.assertEqual(
            prov["source_versions"]["orchestration_task"],
            ORCH_TASK_SCHEMA_VERSION,
        )

    def test_build_audit_metadata_create(self):
        meta = build_orch_task_audit_metadata(
            record_task_id="FIX-CC-03",
            task_type=ORCH_TASK_TYPE_FIX,
            status=ORCH_STATUS_READY,
            idempotency_key="co:FIX-CC-03:dcs:1",
            check_id="CC-03",
        )
        self.assertEqual(meta["task_id"], "FIX-CC-03")
        self.assertEqual(meta["check_id"], "CC-03")

    def test_build_audit_metadata_transition(self):
        meta = build_orch_task_audit_metadata(
            record_task_id="FIX-CC-03",
            task_type=ORCH_TASK_TYPE_FIX,
            status=ORCH_STATUS_DONE,
            idempotency_key="co:FIX-CC-03:dcs:1",
            from_status=ORCH_STATUS_AWAITING_APPROVAL,
            to_status=ORCH_STATUS_DONE,
            reason="Approved",
        )
        self.assertEqual(meta["from_status"], ORCH_STATUS_AWAITING_APPROVAL)
        self.assertEqual(meta["to_status"], ORCH_STATUS_DONE)
        self.assertEqual(meta["reason"], "Approved")

    def test_transition_audit_metadata_requires_to_status(self):
        with self.assertRaises(ValueError):
            build_orch_task_audit_metadata(
                record_task_id="FIX-CC-03",
                task_type=ORCH_TASK_TYPE_FIX,
                status=ORCH_STATUS_DONE,
                idempotency_key="co:FIX-CC-03:dcs:1",
                from_status=ORCH_STATUS_AWAITING_APPROVAL,
            )

    def test_transition_matrix_edge_count(self):
        self.assertEqual(len(ORCH_ALLOWED_STATUS_TRANSITIONS), 16)

    def test_no_transition_from_terminal_states(self):
        for terminal in ORCH_TERMINAL_STATUSES:
            for target in ORCH_STATUS_ENUM:
                if target == terminal:
                    continue
                self.assertFalse(
                    is_allowed_orch_transition(
                        from_status=terminal,
                        to_status=target,
                    ),
                    msg=f"{terminal} -> {target} must be forbidden",
                )

    def test_normalize_priority_inputs_rejects_non_dict(self):
        with self.assertRaises(ValueError):
            normalize_orch_priority_inputs([])

    def test_serialize_rejects_non_model(self):
        with self.assertRaises(TypeError):
            serialize_orch_task({"task_id": "FIX-CC-03"})


class OrchSmPhase1ModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Orch SM Co", slug="orch-sm")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Orch SM Co",
            domain="orch-sm.example.com",
        )

    def test_model_create_with_defaults(self):
        record = OrchestrationTask.objects.create(
            company=self.company,
            task_id="FIX-CC-03",
            task_type=ORCH_TASK_TYPE_FIX,
            status=ORCH_STATUS_READY,
            title="Fix CC-03",
            check_id="CC-03",
            priority_inputs={
                "blocker_status": 2,
                "severity_risk": 1,
                "dependency_readiness": 3,
                "effort_impact": 2,
            },
            priority_score=2.1,
            priority_class="P0",
            depends_on=[],
            wave=0,
            capability_dependencies=[],
            approval={},
            idempotency_key=f"{self.company.id}:FIX-CC-03:dcs:1",
            provenance=build_default_provenance(created_by="system"),
        )
        self.assertEqual(record.status, ORCH_STATUS_READY)
        self.assertEqual(record.task_type, ORCH_TASK_TYPE_FIX)

    def test_model_default_status_pending(self):
        record = OrchestrationTask.objects.create(
            company=self.company,
            task_id="FIX-CC-01",
            task_type=ORCH_TASK_TYPE_FIX,
            priority_inputs={
                "blocker_status": 0,
                "severity_risk": 0,
                "dependency_readiness": 0,
                "effort_impact": 0,
            },
            priority_score=0.0,
            idempotency_key=f"{self.company.id}:FIX-CC-01:dcs:0",
            provenance=build_default_provenance(),
        )
        self.assertEqual(record.status, ORCH_STATUS_PENDING)

    def test_serialize_includes_pack_keys(self):
        record = OrchestrationTask.objects.create(
            company=self.company,
            task_id="FIX-CC-03",
            task_type=ORCH_TASK_TYPE_FIX,
            status=ORCH_STATUS_READY,
            check_id="CC-03",
            priority_inputs={
                "blocker_status": 0,
                "severity_risk": 0,
                "dependency_readiness": 3,
                "effort_impact": 0,
            },
            priority_score=0.6,
            idempotency_key=f"{self.company.id}:FIX-CC-03:dcs:2",
            provenance=build_default_provenance(),
        )
        body = serialize_orch_task(record)
        for key in (
            "schema_version",
            "task_id",
            "tenant_id",
            "task_type",
            "status",
            "depends_on",
            "priority_inputs",
            "priority_score",
            "wave",
            "capability_dependencies",
            "approval",
            "idempotency_key",
            "provenance",
        ):
            self.assertIn(key, body)
        self.assertEqual(body["schema_version"], ORCH_TASK_SCHEMA_VERSION)
        self.assertEqual(body["task_id"], "FIX-CC-03")
        self.assertEqual(body["tenant_id"], str(self.company.id))
        self.assertEqual(body["check_id"], "CC-03")

    def test_idempotency_key_unique_per_company(self):
        key = f"{self.company.id}:FIX-CC-03:dcs:3"
        OrchestrationTask.objects.create(
            company=self.company,
            task_id="FIX-CC-03",
            task_type=ORCH_TASK_TYPE_FIX,
            status=ORCH_STATUS_READY,
            priority_inputs={
                "blocker_status": 0,
                "severity_risk": 0,
                "dependency_readiness": 0,
                "effort_impact": 0,
            },
            priority_score=0.0,
            idempotency_key=key,
            provenance=build_default_provenance(),
        )
        with self.assertRaises(IntegrityError):
            OrchestrationTask.objects.create(
                company=self.company,
                task_id="FIX-CC-03",
                task_type=ORCH_TASK_TYPE_FIX,
                status=ORCH_STATUS_PENDING,
                priority_inputs={
                    "blocker_status": 0,
                    "severity_risk": 0,
                    "dependency_readiness": 0,
                    "effort_impact": 0,
                },
                priority_score=0.0,
                idempotency_key=key,
                provenance=build_default_provenance(),
            )
