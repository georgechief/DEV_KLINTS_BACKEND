"""PRD-HO-02 Phase 1 — activation_meta schema + constants."""

from __future__ import annotations

import uuid

from django.test import SimpleTestCase, TestCase

from dataruns.capabilities.contract import CAP_ID_MCP_WORKFLOW_PUBLISH, CAP_STATUS_DISCOVERY_REQUIRED
from dataruns.use_cases.handoff_package import (
    ACTIVATION_CAPABILITY_CHECKED,
    ACTIVATION_META_APPROVED_AT,
    ACTIVATION_META_CAPABILITY_STATUS_AT_SEND,
    ACTIVATION_PATH_HUMAN_MANAGO_UI,
    AUDIT_ACTION_HANDOFF_ACTIVATED,
    AUDIT_ACTION_HANDOFF_APPROVED,
    AUDIT_ACTION_HANDOFF_REJECTED,
    HANDOFF_ALLOWED_STATUS_TRANSITIONS,
    HANDOFF_ERROR_MANIFEST_MISMATCH,
    HANDOFF_ERROR_NOT_STAGED,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_STATUS_ACTIVATED,
    HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
    HANDOFF_STATUS_REJECTED,
    HANDOFF_STATUS_STAGED,
    build_activation_approval_ref,
    build_activation_meta_for_approve,
    build_activation_meta_for_confirm,
    build_activation_meta_for_reject,
    build_handoff_activation_audit_metadata,
    is_allowed_handoff_transition,
    is_handoff_idempotent_transition,
    is_handoff_terminal_status,
    normalize_activation_meta,
    normalize_handoff_status,
    resolve_mcp_publish_status_at_send,
    serialize_handoff,
    sync_handoff_payload_status,
)
from dataruns.use_cases.models import HandoffPackage
from tenants.models import Company, Tenant


class HandoffHo02Phase1ConstantTests(SimpleTestCase):
    def test_audit_actions_locked(self):
        self.assertEqual(
            AUDIT_ACTION_HANDOFF_APPROVED,
            "workflow.handoff_approved_for_activation",
        )
        self.assertEqual(
            AUDIT_ACTION_HANDOFF_REJECTED,
            "workflow.handoff_rejected",
        )
        self.assertEqual(
            AUDIT_ACTION_HANDOFF_ACTIVATED,
            "workflow.handoff_activated",
        )

    def test_allowed_transitions(self):
        expected = {
            (HANDOFF_STATUS_STAGED, HANDOFF_STATUS_APPROVED_FOR_ACTIVATION),
            (HANDOFF_STATUS_STAGED, HANDOFF_STATUS_REJECTED),
            (HANDOFF_STATUS_APPROVED_FOR_ACTIVATION, HANDOFF_STATUS_ACTIVATED),
            (HANDOFF_STATUS_APPROVED_FOR_ACTIVATION, HANDOFF_STATUS_REJECTED),
        }
        self.assertEqual(HANDOFF_ALLOWED_STATUS_TRANSITIONS, expected)
        self.assertFalse(
            is_allowed_handoff_transition(
                from_status=HANDOFF_STATUS_REJECTED,
                to_status=HANDOFF_STATUS_STAGED,
            )
        )
        self.assertFalse(
            is_allowed_handoff_transition(
                from_status=HANDOFF_STATUS_ACTIVATED,
                to_status=HANDOFF_STATUS_STAGED,
            )
        )

    def test_idempotent_and_terminal_helpers(self):
        self.assertTrue(is_handoff_terminal_status(HANDOFF_STATUS_ACTIVATED))
        self.assertFalse(is_handoff_terminal_status(HANDOFF_STATUS_STAGED))
        self.assertTrue(
            is_handoff_idempotent_transition(
                current_status=HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
                target_status=HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
            )
        )
        self.assertTrue(
            is_handoff_idempotent_transition(
                current_status=HANDOFF_STATUS_ACTIVATED,
                target_status=HANDOFF_STATUS_ACTIVATED,
            )
        )
        self.assertFalse(
            is_handoff_idempotent_transition(
                current_status=HANDOFF_STATUS_STAGED,
                target_status=HANDOFF_STATUS_STAGED,
            )
        )

    def test_error_code_constants(self):
        self.assertEqual(HANDOFF_ERROR_NOT_STAGED, "handoff_not_staged")
        self.assertEqual(HANDOFF_ERROR_MANIFEST_MISMATCH, "manifest_mismatch")

    def test_capability_checked_constant(self):
        self.assertEqual(ACTIVATION_CAPABILITY_CHECKED, CAP_ID_MCP_WORKFLOW_PUBLISH)

    def test_resolve_mcp_publish_status_at_send(self):
        self.assertEqual(
            resolve_mcp_publish_status_at_send(),
            CAP_STATUS_DISCOVERY_REQUIRED,
        )

    def test_build_activation_meta_for_approve_shape(self):
        uid = uuid.uuid4()
        meta = build_activation_meta_for_approve(user_id=uid, notes="ready")
        self.assertEqual(meta["path"], ACTIVATION_PATH_HUMAN_MANAGO_UI)
        self.assertEqual(meta["capability_checked"], CAP_ID_MCP_WORKFLOW_PUBLISH)
        self.assertEqual(
            meta[ACTIVATION_META_CAPABILITY_STATUS_AT_SEND],
            CAP_STATUS_DISCOVERY_REQUIRED,
        )
        self.assertEqual(meta["approved_by_user_id"], str(uid))
        self.assertEqual(meta["notes"], "ready")
        self.assertIsNone(meta["activated_at"])

    def test_build_activation_meta_for_confirm_requires_prior_approve(self):
        uid = uuid.uuid4()
        approved = build_activation_meta_for_approve(user_id=uid)
        confirmed = build_activation_meta_for_confirm(
            existing_meta=approved,
            user_id=uid,
            manago_workflow_external_id="wf-123",
        )
        self.assertIsNotNone(confirmed[ACTIVATION_META_APPROVED_AT])
        self.assertIsNotNone(confirmed["activated_at"])
        self.assertEqual(confirmed["manago_workflow_external_id"], "wf-123")
        self.assertTrue(
            str(confirmed["activation_ref"]).startswith("HUMAN_ACTIVATION_CONFIRMED:")
        )

    def test_build_activation_meta_for_reject(self):
        uid = uuid.uuid4()
        meta = build_activation_meta_for_reject(
            existing_meta={},
            user_id=uid,
            reason="not ready",
        )
        self.assertEqual(meta["rejected_by_user_id"], str(uid))
        self.assertEqual(meta["rejection_reason"], "not ready")

    def test_normalize_handoff_status(self):
        self.assertEqual(normalize_handoff_status("staged"), HANDOFF_STATUS_STAGED)
        with self.assertRaises(ValueError):
            normalize_handoff_status("INVALID")

    def test_activation_audit_metadata_requires_path(self):
        uid = uuid.uuid4()
        meta = build_handoff_activation_audit_metadata(
            handoff_id=uid,
            package_id=uuid.uuid4(),
            qa_run_id=uuid.uuid4(),
            use_case_id="UC-02",
            status=HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
            manifest_hash="a" * 64,
        )
        self.assertEqual(meta["path"], ACTIVATION_PATH_HUMAN_MANAGO_UI)
        self.assertEqual(meta["use_case_id"], "UC-02")

    def test_build_activation_approval_ref(self):
        uid = uuid.uuid4()
        self.assertTrue(
            build_activation_approval_ref(user_id=uid).startswith(
                "HUMAN_ACTIVATION_APPROVED:"
            )
        )


class HandoffHo02Phase1ModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="HO02 Co", slug="ho02-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="HO02 Co",
            domain="ho02.test",
        )

    def test_handoff_package_has_activation_meta_field(self):
        field = HandoffPackage._meta.get_field("activation_meta")
        self.assertEqual(field.get_internal_type(), "JSONField")

    def test_serialize_includes_activation_meta_when_present(self):
        handoff_id = uuid.uuid4()
        record = HandoffPackage(
            id=handoff_id,
            company=self.company,
            use_case_id="UC-02",
            status=HandoffPackage.Status.APPROVED_FOR_ACTIVATION,
            payload={
                "schema_version": "1.0.0",
                "handoff_id": str(handoff_id),
                "tenant_id": str(self.company.id),
                "package_version": "abc123",
                "artifact_refs": [str(uuid.uuid4())],
                "qa_ref": str(uuid.uuid4()),
                "approval_ref": "HUMAN_FALLBACK",
                "manifest_hash": "b" * 64,
                "status": HANDOFF_STATUS_APPROVED_FOR_ACTIVATION,
                "created_at": "2026-08-31T00:00:00+00:00",
                "provenance": {
                    "source_versions": {},
                    "created_at": "2026-08-31T00:00:00+00:00",
                    "created_by": "admin@test.com",
                },
            },
            manifest_hash="b" * 64,
            activation_meta={
                "path": ACTIVATION_PATH_HUMAN_MANAGO_UI,
                "approved_at": "2026-08-31T00:00:00+00:00",
            },
        )
        out = serialize_handoff(record)
        self.assertEqual(
            out["activation_meta"]["path"],
            ACTIVATION_PATH_HUMAN_MANAGO_UI,
        )

    def test_serialize_always_includes_activation_meta_key(self):
        handoff_id = uuid.uuid4()
        record = HandoffPackage(
            id=handoff_id,
            company=self.company,
            use_case_id="UC-02",
            status=HandoffPackage.Status.STAGED,
            payload={
                "schema_version": "1.0.0",
                "handoff_id": str(handoff_id),
                "tenant_id": str(self.company.id),
                "package_version": "abc123",
                "artifact_refs": [str(uuid.uuid4())],
                "qa_ref": str(uuid.uuid4()),
                "approval_ref": "HUMAN_FALLBACK",
                "manifest_hash": "d" * 64,
                "status": HANDOFF_STATUS_STAGED,
                "created_at": "2026-08-31T00:00:00+00:00",
                "provenance": {
                    "source_versions": {},
                    "created_at": "2026-08-31T00:00:00+00:00",
                    "created_by": "admin@test.com",
                },
            },
            manifest_hash="d" * 64,
            activation_meta={},
        )
        out = serialize_handoff(record)
        self.assertIn("activation_meta", out)
        self.assertEqual(out["activation_meta"], {})
        self.assertNotIn("activation_guide", out)
        for key in HANDOFF_PACKAGE_REQUIRED_FIELDS:
            self.assertIn(key, out)

    def test_sync_handoff_payload_status_updates_body(self):
        handoff_id = uuid.uuid4()
        record = HandoffPackage(
            id=handoff_id,
            company=self.company,
            use_case_id="UC-02",
            status=HandoffPackage.Status.APPROVED_FOR_ACTIVATION,
            payload={"status": HANDOFF_STATUS_STAGED, "approval_ref": "OLD"},
            manifest_hash="c" * 64,
            activation_meta={},
        )
        sync_handoff_payload_status(
            record,
            approval_ref=build_activation_approval_ref(user_id=uuid.uuid4()),
        )
        self.assertEqual(record.payload["status"], HANDOFF_STATUS_APPROVED_FOR_ACTIVATION)
        self.assertTrue(
            str(record.payload["approval_ref"]).startswith(
                "HUMAN_ACTIVATION_APPROVED:"
            )
        )
        self.assertEqual(normalize_activation_meta(None), {})
