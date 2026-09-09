"""PRD-HO-01 Step 5 — audit wire gate (PRD §7).

Locks: action, metadata keys, create-only (no double-audit), QA auto path,
HTTP POST path, no audit on read / FAIL.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.handoff_package import (
    AUDIT_ACTION_HANDOFF_STAGED,
    HANDOFF_STATUS_STAGED,
    HANDOFF_STAGED_AUDIT_METADATA_KEYS,
    build_handoff_staged_audit_metadata,
)
from dataruns.use_cases.handoff_stage import (
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
from dataruns.use_cases.qa_run import run_qa_for_package
from dataruns.use_cases.recommend import (
    RecommendationContext,
    _gates_from_blueprint,
    build_gates_snapshot,
)
from dataruns.use_cases.views import (
    BuildPackageHandoffView,
    HandoffDetailView,
    HandoffListView,
)
from tenants.models import Company, Tenant, User


class HandoffPackageStep5AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="HO Step5", slug="ho-step5")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="HO Step5 Co",
            domain="ho-step5.example.com",
        )
        cls.user = User.objects.create_user(
            email="ho-step5@example.com",
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
            generated_by=cls.user,
        )
        cls.factory = APIRequestFactory()

    def _persist_package(self, payload: dict | None = None) -> WorkflowBuildPackage:
        body = deepcopy(payload or self.golden_payload)
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=body,
            provisional_supplemental=bool(body.get("provisional_supplemental")),
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(body.get("hashes") or {}).get(
                "package_content_hash", "f" * 64
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
            payload={"status": status, "score": 100.0 if status == QA_STATUS_PASS else 40.0},
            created_by=self.user,
        )

    def _assert_staged_audit(
        self,
        audit: AuditLog,
        *,
        handoff_id: str,
        package_id: str,
        qa_run_id: str,
        performed_by: str | None = None,
        actor_user_id: str | None = None,
    ) -> None:
        self.assertEqual(audit.action, AUDIT_ACTION_HANDOFF_STAGED)
        self.assertEqual(audit.tone, AuditLog.Tone.REVENUE)
        self.assertEqual(
            set(audit.metadata.keys()),
            HANDOFF_STAGED_AUDIT_METADATA_KEYS,
        )
        self.assertEqual(audit.metadata["handoff_id"], handoff_id)
        self.assertEqual(audit.metadata["package_id"], package_id)
        self.assertEqual(audit.metadata["qa_run_id"], qa_run_id)
        self.assertEqual(audit.metadata["use_case_id"], "UC-02")
        self.assertEqual(audit.metadata["status"], HANDOFF_STATUS_STAGED)
        self.assertIn("STAGED", audit.summary)
        self.assertIn("UC-02", audit.summary)
        if performed_by is not None:
            self.assertEqual(audit.performed_by, performed_by)
        if actor_user_id is not None:
            self.assertEqual(str(audit.actor_user_id), actor_user_id)

    def test_metadata_builder_locks_prd_keys(self):
        self.assertEqual(AUDIT_ACTION_HANDOFF_STAGED, "workflow.handoff_staged")
        meta = build_handoff_staged_audit_metadata(
            handoff_id="11111111-1111-1111-1111-111111111111",
            package_id="22222222-2222-2222-2222-222222222222",
            qa_run_id="33333333-3333-3333-3333-333333333333",
            use_case_id="uc-02",
        )
        self.assertEqual(set(meta.keys()), HANDOFF_STAGED_AUDIT_METADATA_KEYS)
        self.assertEqual(meta["use_case_id"], "UC-02")
        self.assertEqual(meta["status"], HANDOFF_STATUS_STAGED)
        with self.assertRaises(ValueError):
            build_handoff_staged_audit_metadata(
                handoff_id="11111111-1111-1111-1111-111111111111",
                package_id="22222222-2222-2222-2222-222222222222",
                qa_run_id="33333333-3333-3333-3333-333333333333",
                use_case_id="  ",
            )

    def test_create_audits_once_with_full_metadata(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        self.assertTrue(outcome.created)

        audits = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        )
        self.assertEqual(audits.count(), 1)
        self._assert_staged_audit(
            audits.get(),
            handoff_id=str(outcome.record.id),
            package_id=str(package.id),
            qa_run_id=str(qa.id),
            performed_by=self.user.email,
            actor_user_id=str(self.user.id),
        )

        # Idempotent re-get: no second audit.
        again = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        self.assertFalse(again.created)
        self.assertEqual(audits.count(), 1)

    def test_system_actor_when_created_by_none(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=None,
        )
        self.assertTrue(outcome.created)
        audit = AuditLog.objects.get(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        )
        self.assertEqual(audit.performed_by, "system")
        self.assertIsNone(audit.actor_user_id)

    def test_qa_pass_auto_stages_and_audits(self):
        package = self._persist_package()
        outcome = run_qa_for_package(package=package, created_by=self.user)
        self.assertEqual(outcome.record.status, QA_STATUS_PASS)
        handoff = HandoffPackage.objects.get(
            package=package,
            qa_result=outcome.record,
        )
        audit = AuditLog.objects.get(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        )
        self._assert_staged_audit(
            audit,
            handoff_id=str(handoff.id),
            package_id=str(package.id),
            qa_run_id=str(outcome.record.id),
            performed_by=self.user.email,
            actor_user_id=str(self.user.id),
        )

    def test_qa_fail_writes_no_handoff_audit(self):
        payload = deepcopy(self.golden_payload)
        payload["gates_snapshot"] = {
            "checks": {"CC-03": "FAIL"},
            "provisional_supplemental": True,
        }
        package = self._persist_package(payload)
        outcome = run_qa_for_package(package=package, created_by=self.user)
        self.assertEqual(outcome.record.status, QA_STATUS_FAIL)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            0,
        )

    def test_http_post_audits_get_does_not(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        path = f"/api/v1/build-packages/{package.id}/handoff/"

        post_req = self.factory.post(path, {}, format="json")
        force_authenticate(post_req, user=self.user)
        created = BuildPackageHandoffView.as_view()(
            post_req, package_id=str(package.id)
        )
        self.assertEqual(created.status_code, 201)
        handoff_id = created.data["handoff_id"]

        audits = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        )
        self.assertEqual(audits.count(), 1)
        self._assert_staged_audit(
            audits.get(),
            handoff_id=handoff_id,
            package_id=str(package.id),
            qa_run_id=str(qa.id),
            performed_by=self.user.email,
            actor_user_id=str(self.user.id),
        )

        # Idempotent POST → still one audit.
        again_req = self.factory.post(path, {}, format="json")
        force_authenticate(again_req, user=self.user)
        again = BuildPackageHandoffView.as_view()(
            again_req, package_id=str(package.id)
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(audits.count(), 1)

        # Reads must not append audit.
        get_pkg = self.factory.get(path)
        force_authenticate(get_pkg, user=self.user)
        BuildPackageHandoffView.as_view()(get_pkg, package_id=str(package.id))

        get_detail = self.factory.get(f"/api/v1/handoffs/{handoff_id}/")
        force_authenticate(get_detail, user=self.user)
        HandoffDetailView.as_view()(get_detail, handoff_id=handoff_id)

        get_list = self.factory.get(f"/api/v1/handoffs/?package_id={package.id}")
        force_authenticate(get_list, user=self.user)
        HandoffListView.as_view()(get_list)

        self.assertEqual(audits.count(), 1)

    def test_race_loser_does_not_double_audit(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        winner = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.user,
        )
        self.assertTrue(winner.created)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            1,
        )

        real_existing = (
            HandoffPackage.objects.filter(
                company_id=package.company_id,
                package_id=package.id,
                qa_result_id=qa.id,
            ).first()
        )
        # First lookup misses (enter create), IntegrityError → second lookup finds winner.
        with patch(
            "dataruns.use_cases.handoff_stage._existing_handoff",
            side_effect=[None, real_existing],
        ):
            raced = create_or_get_staged_handoff(
                package=package,
                qa_result=qa,
                created_by=self.user,
            )
        self.assertFalse(raced.created)
        self.assertEqual(raced.record.id, winner.record.id)
        self.assertEqual(
            AuditLog.objects.filter(
                company=self.company,
                action=AUDIT_ACTION_HANDOFF_STAGED,
            ).count(),
            1,
        )

    def test_stage_helper_audits_same_contract(self):
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = stage_handoff_for_package(package=package, created_by=self.user)
        self.assertTrue(outcome.created)
        audit = AuditLog.objects.get(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        )
        self._assert_staged_audit(
            audit,
            handoff_id=str(outcome.record.id),
            package_id=str(package.id),
            qa_run_id=str(qa.id),
        )
