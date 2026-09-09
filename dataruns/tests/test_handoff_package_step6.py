"""PRD-HO-01 Step 6 — BE case matrix sign-off (PRD §8 backend rows).

Authoritative gate for backend HO-01 before FE Steps 7–10.
FE rows (live /handoff render, Send disabled) are deferred.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from dataruns.models import AuditLog
from dataruns.use_cases.build_package import assemble_build_package_payload
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.handoff_package import (
    AUDIT_ACTION_HANDOFF_STAGED,
    HANDOFF_PACKAGE_REQUIRED_FIELDS,
    HANDOFF_STATUS_STAGED,
    HANDOFF_STAGED_AUDIT_METADATA_KEYS,
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
from tenants.models import Company, Tenant, User

_SCHEMA_KEYS = frozenset(HANDOFF_PACKAGE_REQUIRED_FIELDS)
_FE_SIBLINGS = frozenset({"use_case_id", "package_id", "qa_run_id"})


class HandoffPackageStep6BeMatrixTests(TestCase):
    """PRD §8 BE rows + adjacent BE gates required before FE bind."""

    @classmethod
    def setUpTestData(cls):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        cls.tenant = Tenant.objects.create(name="HO Step6", slug="ho-step6")
        cls.company = Company.objects.create(
            tenant=cls.tenant,
            name="HO Step6 Co",
            domain="ho-step6.example.com",
        )
        cls.other_tenant = Tenant.objects.create(name="HO Step6 Other", slug="ho-s6-o")
        cls.other_company = Company.objects.create(
            tenant=cls.other_tenant,
            name="HO Step6 Other Co",
            domain="ho-step6-other.example.com",
        )
        cls.admin = User.objects.create_user(
            email="ho-step6-admin@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ADMIN,
        )
        cls.analyst = User.objects.create_user(
            email="ho-step6-analyst@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.ANALYST,
        )
        cls.viewer = User.objects.create_user(
            email="ho-step6-viewer@example.com",
            password="pass",
            tenant=cls.tenant,
            role=User.Role.VIEWER,
        )
        cls.outsider = User.objects.create_user(
            email="ho-step6-outsider@example.com",
            password="pass",
            tenant=cls.other_tenant,
            role=User.Role.ADMIN,
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
            package_id="00000000-0000-0000-0000-000000000006",
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

    def setUp(self):
        self.client = APIClient()

    def _persist_package(self, payload: dict | None = None) -> WorkflowBuildPackage:
        body = deepcopy(payload or self.golden_payload)
        record = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload=body,
            provisional_supplemental=bool(body.get("provisional_supplemental")),
            blueprint_content_hash=self.blueprint.content_hash,
            package_content_hash=(body.get("hashes") or {}).get(
                "package_content_hash", "6" * 64
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
            payload={
                "status": status,
                "score": 100.0 if status == QA_STATUS_PASS else 40.0,
            },
            created_by=self.analyst,
        )

    def _assert_staged_api_body(
        self,
        data: dict,
        *,
        package_id: str,
        qa_run_id: str,
    ) -> None:
        self.assertTrue(_SCHEMA_KEYS.issubset(set(data.keys())))
        self.assertTrue(_FE_SIBLINGS.issubset(set(data.keys())))
        self.assertEqual(data["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(data["package_id"], package_id)
        self.assertEqual(data["qa_run_id"], qa_run_id)
        self.assertEqual(data["qa_ref"], qa_run_id)
        self.assertEqual(data["use_case_id"], "UC-02")
        self.assertEqual(data["tenant_id"], str(self.company.id))
        self.assertIn("title", data)
        self.assertTrue(str(data.get("title") or "").strip())

    # --- PRD §8 BE rows -------------------------------------------------

    def test_s8_qa_pass_auto_creates_staged_handoff(self):
        """§8: QA PASS → handoff row exists (auto) · STAGED schema-shaped."""
        package = self._persist_package()
        qa_outcome = run_qa_for_package(package=package, created_by=self.analyst)
        self.assertEqual(qa_outcome.record.status, QA_STATUS_PASS)

        handoff = HandoffPackage.objects.get(
            package=package,
            qa_result=qa_outcome.record,
        )
        self.assertEqual(handoff.status, HANDOFF_STATUS_STAGED)
        self.assertTrue(
            _SCHEMA_KEYS.issubset(set(handoff.payload.keys()))
        )
        self.assertEqual(handoff.payload["status"], HANDOFF_STATUS_STAGED)

        self.client.force_authenticate(user=self.analyst)
        latest = self.client.get(
            reverse("build-package-handoff", kwargs={"package_id": package.id})
        )
        self.assertEqual(latest.status_code, 200)
        self._assert_staged_api_body(
            latest.data,
            package_id=str(package.id),
            qa_run_id=str(qa_outcome.record.id),
        )

    def test_s8_qa_pass_post_creates_201_staged(self):
        """§8: QA PASS → handoff via POST · 201 STAGED."""
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.admin)

        created = self.client.post(url, {}, format="json")
        self.assertEqual(created.status_code, 201)
        self._assert_staged_api_body(
            created.data,
            package_id=str(package.id),
            qa_run_id=str(qa.id),
        )
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 1)

    def test_s8_second_create_same_package_qa_idempotent(self):
        """§8: Second create same package+qa → same id (200)."""
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)

        first = self.client.post(url, {}, format="json")
        second = self.client.post(url, {}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["handoff_id"], second.data["handoff_id"])
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 1)

    def test_s8_qa_fail_post_handoff_409(self):
        """§8: QA FAIL → POST handoff → 409."""
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_FAIL)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)

        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "qa_not_pass")
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 0)

    def test_s8_get_other_company_handoff_404(self):
        """§8: GET other company handoff → 404 (detail + package + list)."""
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)
        created = self.client.post(url, {}, format="json")
        handoff_id = created.data["handoff_id"]

        self.client.force_authenticate(user=self.outsider)
        detail = self.client.get(
            reverse("handoff-detail", kwargs={"handoff_id": handoff_id})
        )
        self.assertEqual(detail.status_code, 404)

        by_package = self.client.get(url)
        self.assertEqual(by_package.status_code, 404)

        listed = self.client.get(
            reverse("handoff-list"),
            {"package_id": str(package.id)},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 0)

    # --- Adjacent BE gates (acceptance / roles) -------------------------

    def test_get_by_handoff_id_and_package_id(self):
        """Acceptance: GET by handoff id / package id works (tenant-scoped)."""
        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)
        created = self.client.post(url, {}, format="json")
        handoff_id = created.data["handoff_id"]

        self.client.force_authenticate(user=self.viewer)
        by_package = self.client.get(url)
        by_id = self.client.get(
            reverse("handoff-detail", kwargs={"handoff_id": handoff_id})
        )
        self.assertEqual(by_package.status_code, 200)
        self.assertEqual(by_id.status_code, 200)
        self.assertEqual(by_package.data["handoff_id"], handoff_id)
        self.assertEqual(by_id.data["handoff_id"], handoff_id)
        self._assert_staged_api_body(
            by_id.data,
            package_id=str(package.id),
            qa_run_id=str(qa.id),
        )

    def test_audit_workflow_handoff_staged_on_create_only(self):
        """Acceptance: Audit workflow.handoff_staged (create only)."""
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.client.force_authenticate(user=self.analyst)

        created = self.client.post(url, {}, format="json")
        self.client.post(url, {}, format="json")  # idempotent
        audits = AuditLog.objects.filter(
            company=self.company,
            action=AUDIT_ACTION_HANDOFF_STAGED,
        )
        self.assertEqual(audits.count(), 1)
        audit = audits.get()
        self.assertEqual(set(audit.metadata.keys()), HANDOFF_STAGED_AUDIT_METADATA_KEYS)
        self.assertEqual(audit.metadata["handoff_id"], created.data["handoff_id"])
        self.assertEqual(audit.metadata["status"], HANDOFF_STATUS_STAGED)

    def test_roles_admin_analyst_create_viewer_read_only(self):
        package = self._persist_package()
        self._qa(package, status=QA_STATUS_PASS)
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})

        self.client.force_authenticate(user=self.viewer)
        blocked = self.client.post(url, {}, format="json")
        self.assertEqual(blocked.status_code, 403)

        self.client.force_authenticate(user=self.admin)
        created = self.client.post(url, {}, format="json")
        self.assertEqual(created.status_code, 201)

        self.client.force_authenticate(user=self.viewer)
        readable = self.client.get(url)
        self.assertEqual(readable.status_code, 200)

    def test_unauthenticated_returns_401(self):
        package = self._persist_package()
        url = reverse("build-package-handoff", kwargs={"package_id": package.id})
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 401)
        self.assertEqual(
            self.client.get(reverse("handoff-list")).status_code,
            401,
        )
        missing = str(uuid4())
        self.assertEqual(
            self.client.get(
                reverse("handoff-detail", kwargs={"handoff_id": missing})
            ).status_code,
            401,
        )

    def test_uc02_be_journey_studio_qa_pass_to_handoff_apis(self):
        """BE half of UC-02 path: package → QA PASS → staged GETs ready for FE."""
        package = self._persist_package()
        qa_outcome = run_qa_for_package(package=package, created_by=self.analyst)
        self.assertEqual(qa_outcome.record.status, QA_STATUS_PASS)

        self.client.force_authenticate(user=self.analyst)
        latest = self.client.get(
            reverse("build-package-handoff", kwargs={"package_id": package.id})
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data["status"], HANDOFF_STATUS_STAGED)
        self.assertEqual(latest.data["qa_run_id"], str(qa_outcome.record.id))

        detail = self.client.get(
            reverse(
                "handoff-detail",
                kwargs={"handoff_id": latest.data["handoff_id"]},
            )
        )
        self.assertEqual(detail.status_code, 200)

        listed = self.client.get(
            reverse("handoff-list"),
            {
                "package_id": str(package.id),
                "qa_run_id": str(qa_outcome.record.id),
            },
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)
        self.assertEqual(
            listed.data["results"][0]["handoff_id"],
            latest.data["handoff_id"],
        )

    def test_qa_auto_stage_failure_maps_to_409_not_500(self):
        """HandoffStageError during QA PASS must surface as QaRunError (HTTP 409)."""
        from unittest.mock import patch

        from dataruns.use_cases.handoff_stage import HandoffStageError
        from dataruns.use_cases.qa_run import QaRunError

        package = self._persist_package()
        with patch(
            "dataruns.use_cases.qa_run.create_or_get_staged_handoff",
            side_effect=HandoffStageError(
                code="use_case_missing",
                detail="Cannot stage handoff without use_case_id.",
                status=409,
            ),
        ):
            with self.assertRaises(QaRunError) as ctx:
                run_qa_for_package(package=package, created_by=self.analyst)
        self.assertEqual(ctx.exception.code, "use_case_missing")
        self.assertEqual(ctx.exception.status, 409)
        # Same txn: QA row must not persist when auto-stage fails.
        self.assertEqual(
            WorkflowQaResult.objects.filter(package=package).count(),
            0,
        )
        self.assertEqual(HandoffPackage.objects.filter(package=package).count(), 0)

        # HTTP QA endpoint returns 409, not 500.
        self.client.force_authenticate(user=self.analyst)
        with patch(
            "dataruns.use_cases.qa_run.create_or_get_staged_handoff",
            side_effect=HandoffStageError(
                code="use_case_missing",
                detail="Cannot stage handoff without use_case_id.",
                status=409,
            ),
        ):
            response = self.client.post(
                reverse("build-package-qa", kwargs={"package_id": package.id}),
                {},
                format="json",
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "use_case_missing")

    def test_serialize_aligns_provenance_created_at(self):
        from dataruns.use_cases.handoff_package import serialize_handoff
        from dataruns.use_cases.handoff_stage import create_or_get_staged_handoff

        package = self._persist_package()
        qa = self._qa(package, status=QA_STATUS_PASS)
        outcome = create_or_get_staged_handoff(
            package=package,
            qa_result=qa,
            created_by=self.analyst,
        )
        record = HandoffPackage.objects.select_related(
            "package", "package__pilot", "qa_result"
        ).get(pk=outcome.record.id)
        stale = {
            **(record.payload if isinstance(record.payload, dict) else {}),
            "created_at": "2000-01-01T00:00:00+00:00",
            "provenance": {
                **(
                    (record.payload or {}).get("provenance")
                    if isinstance(record.payload, dict)
                    else {}
                ),
                "created_at": "2000-01-01T00:00:00+00:00",
            },
        }
        record.payload = stale
        record.save(update_fields=["payload"])
        record.refresh_from_db()
        record = HandoffPackage.objects.select_related(
            "package", "package__pilot", "qa_result"
        ).get(pk=record.id)

        data = serialize_handoff(record)
        self.assertEqual(data["created_at"], data["provenance"]["created_at"])
        self.assertNotEqual(data["created_at"], "2000-01-01T00:00:00+00:00")
