"""PRD-HO-01 Step 1 — handoff_package schema field lock + payload builder."""

from __future__ import annotations

import uuid

from django.test import SimpleTestCase

from dataruns.use_cases.handoff_package import (
    APPROVAL_REF_HUMAN_FALLBACK,
    APPROVAL_REF_NOT_REQUIRED_FOR_STAGED,
    AUDIT_ACTION_HANDOFF_STAGED,
    BLUEPRINT_ACTIVATION_STAGED_NOT_LIVE,
    HANDOFF_FE_SIBLING_KEYS,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_PACKAGE_SCHEMA_VERSION,
    HANDOFF_STATUS_ACTIVATED,
    HANDOFF_STATUS_STAGED,
    MANIFEST_HASH_RE,
    build_artifact_refs,
    build_handoff_package_payload,
    compute_manifest_hash,
    map_activation_state_to_handoff_status,
    resolve_approval_ref,
)


class HandoffPackageStep1FieldLockTests(SimpleTestCase):
    def test_schema_version_and_required_fields_locked(self):
        self.assertEqual(HANDOFF_PACKAGE_SCHEMA_VERSION, "1.0.0")
        self.assertEqual(
            HANDOFF_PACKAGE_REQUIRED_FIELDS,
            {
                "schema_version",
                "handoff_id",
                "tenant_id",
                "package_version",
                "artifact_refs",
                "qa_ref",
                "approval_ref",
                "manifest_hash",
                "status",
                "created_at",
                "provenance",
            },
        )
        self.assertEqual(AUDIT_ACTION_HANDOFF_STAGED, "workflow.handoff_staged")

    def test_staged_not_live_maps_to_staged(self):
        self.assertEqual(
            map_activation_state_to_handoff_status(BLUEPRINT_ACTIVATION_STAGED_NOT_LIVE),
            HANDOFF_STATUS_STAGED,
        )
        self.assertEqual(
            map_activation_state_to_handoff_status(HANDOFF_STATUS_ACTIVATED),
            HANDOFF_STATUS_STAGED,
        )
        self.assertEqual(
            map_activation_state_to_handoff_status(None),
            HANDOFF_STATUS_STAGED,
        )

    def test_approval_ref_policy(self):
        self.assertEqual(
            resolve_approval_ref(package_route="HUMAN_FALLBACK"),
            APPROVAL_REF_HUMAN_FALLBACK,
        )
        self.assertEqual(
            resolve_approval_ref(package_route="MCP"),
            APPROVAL_REF_NOT_REQUIRED_FOR_STAGED,
        )
        self.assertEqual(
            resolve_approval_ref(
                package_route="HUMAN_FALLBACK",
                writeback_approval_id="wb-123",
            ),
            "wb-123",
        )

    def test_artifact_refs_include_package_id(self):
        package_id = str(uuid.uuid4())
        refs = build_artifact_refs(
            package_id=package_id,
            human_guide_ref="guide:uc-02",
            agent_spec_ref="guide:uc-02",
        )
        self.assertEqual(refs[0], package_id)
        self.assertEqual(refs.count("guide:uc-02"), 1)

    def test_manifest_hash_is_sha256_hex(self):
        digest = compute_manifest_hash({"package_id": "x", "nodes": [1, 2]})
        self.assertRegex(digest, r"^[a-f0-9]{64}$")
        self.assertTrue(MANIFEST_HASH_RE.match(digest))

    def test_build_payload_schema_shaped_only(self):
        handoff_id = uuid.uuid4()
        package_id = str(uuid.uuid4())
        qa_run_id = str(uuid.uuid4())
        manifest = compute_manifest_hash({"a": 1})
        payload = build_handoff_package_payload(
            handoff_id=handoff_id,
            tenant_id=uuid.uuid4(),
            package_version=manifest[:12],
            artifact_refs=build_artifact_refs(package_id=package_id),
            qa_ref=qa_run_id,
            approval_ref=APPROVAL_REF_HUMAN_FALLBACK,
            manifest_hash=manifest,
            status=BLUEPRINT_ACTIVATION_STAGED_NOT_LIVE,
            created_by="ops@example.com",
            source_versions={"blueprint": "abc", "package": "def", "n": 12},
        )

        self.assertEqual(set(payload.keys()), HANDOFF_PACKAGE_REQUIRED_FIELDS)
        self.assertEqual(payload["schema_version"], "1.0.0")
        self.assertEqual(payload["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(payload["qa_ref"], qa_run_id)
        self.assertEqual(payload["artifact_refs"], [package_id])
        self.assertRegex(payload["manifest_hash"], r"^[a-f0-9]{64}$")
        self.assertEqual(
            set(payload["provenance"].keys()),
            {"source_versions", "created_at", "created_by"},
        )
        self.assertEqual(payload["provenance"]["source_versions"]["n"], "12")
        # Schema forbids stuffing FE siblings into body.
        for key in HANDOFF_FE_SIBLING_KEYS:
            self.assertNotIn(key, payload)

    def test_build_payload_rejects_bad_manifest_hash(self):
        with self.assertRaises(ValueError):
            build_handoff_package_payload(
                handoff_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                package_version="v1",
                artifact_refs=["pkg"],
                qa_ref=uuid.uuid4(),
                approval_ref=APPROVAL_REF_NOT_REQUIRED_FOR_STAGED,
                manifest_hash="not-a-hash",
                created_by="system",
            )

    def test_build_payload_rejects_empty_artifact_refs(self):
        with self.assertRaises(ValueError):
            build_handoff_package_payload(
                handoff_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                package_version="v1",
                artifact_refs=["", "  "],
                qa_ref=uuid.uuid4(),
                approval_ref=APPROVAL_REF_NOT_REQUIRED_FOR_STAGED,
                manifest_hash="a" * 64,
                created_by="system",
            )

    def test_build_payload_rejects_non_dict_manifest_body(self):
        with self.assertRaises(TypeError):
            compute_manifest_hash(["not", "a", "dict"])  # type: ignore[arg-type]
