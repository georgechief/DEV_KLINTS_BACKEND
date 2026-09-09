"""PRD-HO-01 Step 2 — HandoffPackage model + migration."""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import TestCase

from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.handoff_package import (
    APPROVAL_REF_HUMAN_FALLBACK,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_STATUS_ENUM,
    HANDOFF_STATUS_STAGED,
    build_artifact_refs,
    build_handoff_package_payload,
    compute_manifest_hash,
)
from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.models import (
    HandoffPackage,
    UseCasePilot,
    WorkflowBuildPackage,
    WorkflowQaResult,
)
from tenants.models import Company, Tenant, User


class HandoffPackageStep2ModelTests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="HO Step2", slug="ho-step2")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="HO Step2 Co",
            domain="ho-step2.example.com",
        )
        self.user = User.objects.create_user(
            email="ho-step2@example.com",
            password="test-pass-123",
            tenant=self.tenant,
            role=User.Role.ANALYST,
        )
        pilot = UseCasePilot.objects.get(use_case_id="UC-02")
        package_id = uuid.uuid4()
        self.package = WorkflowBuildPackage.objects.create(
            id=package_id,
            company=self.company,
            pilot=pilot,
            payload={
                "package_id": str(package_id),
                "use_case_id": "UC-02",
                "route": "HUMAN_FALLBACK",
                "handoff_stub": {"activation_state": "STAGED_NOT_LIVE"},
                "hashes": {"package_content_hash": "a" * 64},
            },
            blueprint_content_hash="b" * 64,
            package_content_hash="a" * 64,
            generated_by=self.user,
        )
        self.qa = WorkflowQaResult.objects.create(
            company=self.company,
            package=self.package,
            use_case_id="UC-02",
            score=100.0,
            status=WorkflowQaResult.Status.PASS,
            payload={"status": "PASS", "score": 100.0},
            created_by=self.user,
        )

    def _build_payload(self, handoff_id: uuid.UUID) -> dict:
        manifest = compute_manifest_hash(self.package.payload)
        return build_handoff_package_payload(
            handoff_id=handoff_id,
            tenant_id=self.company.id,
            package_version=self.package.package_content_hash[:12],
            artifact_refs=build_artifact_refs(package_id=self.package.id),
            qa_ref=self.qa.id,
            approval_ref=APPROVAL_REF_HUMAN_FALLBACK,
            manifest_hash=manifest,
            status=HANDOFF_STATUS_STAGED,
            created_by=self.user.email,
            source_versions={
                "blueprint": self.package.blueprint_content_hash,
                "package": self.package.package_content_hash,
            },
        )

    def test_create_staged_handoff_with_schema_payload(self):
        handoff_id = uuid.uuid4()
        payload = self._build_payload(handoff_id)
        row = HandoffPackage.objects.create(
            id=handoff_id,
            company=self.company,
            package=self.package,
            qa_result=self.qa,
            use_case_id="UC-02",
            status=HandoffPackage.Status.STAGED,
            payload=payload,
            manifest_hash=payload["manifest_hash"],
            created_by=self.user,
        )

        self.assertEqual(row.handoff_id, str(handoff_id))
        self.assertEqual(row.status, HANDOFF_STATUS_STAGED)
        self.assertEqual(set(row.payload.keys()), HANDOFF_PACKAGE_REQUIRED_FIELDS)
        self.assertEqual(row.payload["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(row.qa_result_id, self.qa.id)
        self.assertEqual(row.package_id, self.package.id)
        self.assertEqual(HandoffPackage.objects.count(), 1)

    def test_unique_constraint_company_package_qa(self):
        handoff_id = uuid.uuid4()
        payload = self._build_payload(handoff_id)
        HandoffPackage.objects.create(
            id=handoff_id,
            company=self.company,
            package=self.package,
            qa_result=self.qa,
            use_case_id="UC-02",
            status=HandoffPackage.Status.STAGED,
            payload=payload,
            manifest_hash=payload["manifest_hash"],
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HandoffPackage.objects.create(
                    id=uuid.uuid4(),
                    company=self.company,
                    package=self.package,
                    qa_result=self.qa,
                    use_case_id="UC-02",
                    status=HandoffPackage.Status.STAGED,
                    payload=payload,
                    manifest_hash=payload["manifest_hash"],
                    created_by=self.user,
                )

        self.assertEqual(HandoffPackage.objects.count(), 1)

    def test_default_status_is_staged(self):
        handoff_id = uuid.uuid4()
        payload = self._build_payload(handoff_id)
        row = HandoffPackage.objects.create(
            id=handoff_id,
            company=self.company,
            package=self.package,
            qa_result=self.qa,
            use_case_id="UC-02",
            payload=payload,
            manifest_hash=payload["manifest_hash"],
        )
        self.assertEqual(row.status, HandoffPackage.Status.STAGED)

    def test_related_names(self):
        handoff_id = uuid.uuid4()
        payload = self._build_payload(handoff_id)
        HandoffPackage.objects.create(
            id=handoff_id,
            company=self.company,
            package=self.package,
            qa_result=self.qa,
            use_case_id="UC-02",
            payload=payload,
            manifest_hash=payload["manifest_hash"],
        )
        self.assertEqual(self.package.handoffs.count(), 1)
        self.assertEqual(self.qa.handoffs.count(), 1)
        self.assertEqual(self.company.handoff_packages.count(), 1)

    def test_model_status_enum_matches_pack_lock(self):
        self.assertEqual(
            {choice.value for choice in HandoffPackage.Status},
            set(HANDOFF_STATUS_ENUM),
        )
        self.assertEqual(HandoffPackage.Status.STAGED, HANDOFF_STATUS_STAGED)

    def test_payload_package_id_matches_fk(self):
        self.assertEqual(
            self.package.payload["package_id"],
            str(self.package.id),
        )
