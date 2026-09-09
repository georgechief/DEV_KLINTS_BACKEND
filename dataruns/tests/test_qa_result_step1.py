"""PRD-QA-01 Step 1 — WorkflowQaResult model + schema serializer."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import TestCase

from dataruns.use_cases.loader import load_use_case_pilots_from_pack
from dataruns.use_cases.constants import DEFAULT_MANIFEST_REL
from dataruns.use_cases.models import UseCasePilot, WorkflowBuildPackage, WorkflowQaResult
from dataruns.use_cases.qa_result import (
    QA_RESULT_SCHEMA_VERSION,
    QA_STATUS_FAIL,
    QA_STATUS_PASS,
    build_qa_result_payload,
    latest_qa_result_for_package,
    serialize_qa_result,
)
from tenants.models import Company, Tenant, User


class WorkflowQaResultStep1Tests(TestCase):
    def setUp(self):
        base = Path(settings.BASE_DIR)
        load_use_case_pilots_from_pack(
            manifest_path=base / DEFAULT_MANIFEST_REL,
            blueprints_dir=(base / DEFAULT_MANIFEST_REL).parent,
        )
        self.tenant = Tenant.objects.create(name="QA Step1", slug="qa-step1")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="QA Step1 Co",
            domain="qa-step1.example.com",
        )
        self.user = User.objects.create_user(
            email="qa-step1@example.com",
            password="test-pass-123",
            tenant=self.tenant,
            role=User.Role.ADMIN,
        )
        self.pilot = UseCasePilot.objects.get(use_case_id="UC-02")
        self.package = WorkflowBuildPackage.objects.create(
            company=self.company,
            pilot=self.pilot,
            payload={
                "package_id": "will-be-overridden",
                "use_case_id": "UC-02",
                "qa_requirements": {
                    "minimum_score": 80,
                    "hard_tests": [
                        "data_gates_pass",
                        "consent_branching",
                        "terminal_reachable",
                        "no_orphan_nodes",
                        "collision_policy",
                        "measurement_wired",
                        "rollback_defined",
                    ],
                },
            },
            blueprint_content_hash="a" * 64,
            package_content_hash="b" * 64,
            generated_by=self.user,
        )
        # Align payload package_id with PK (WF-01 style).
        self.package.payload["package_id"] = str(self.package.id)
        self.package.save(update_fields=["payload"])

    def test_build_qa_result_payload_has_schema_required_fields(self):
        payload = build_qa_result_payload(
            qa_run_id="11111111-1111-1111-1111-111111111111",
            company_id=self.company.id,
            package_id=self.package.id,
            use_case_id="UC-02",
            score=100,
            status="PASS",
            hard_tests=[
                {
                    "test_id": "data_gates_pass",
                    "status": "PASS",
                    "evidence_ids": ["ev-data_gates_pass-0"],
                }
            ],
            evidence=[
                {
                    "source": "build_package",
                    "locator": "gates_snapshot.checks.CC-03",
                    "value": "PASS",
                    "observed_at": "2026-08-20T04:00:00+00:00",
                }
            ],
            minimum_score=80,
        )
        for key in (
            "schema_version",
            "qa_run_id",
            "tenant_id",
            "object_id",
            "score",
            "hard_tests",
            "status",
            "evidence",
            "created_at",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["schema_version"], QA_RESULT_SCHEMA_VERSION)
        self.assertEqual(payload["tenant_id"], str(self.company.id))
        self.assertEqual(payload["object_id"], str(self.package.id))
        self.assertEqual(payload["package_id"], str(self.package.id))
        self.assertEqual(payload["use_case_id"], "UC-02")
        self.assertEqual(payload["minimum_score"], 80.0)
        self.assertEqual(payload["status"], QA_STATUS_PASS)

    def test_persist_and_serialize_round_trip(self):
        body = build_qa_result_payload(
            qa_run_id="22222222-2222-2222-2222-222222222222",
            company_id=self.company.id,
            package_id=self.package.id,
            use_case_id="UC-02",
            score=85.71428571428571,
            status="FAIL",
            hard_tests=[
                {"test_id": "data_gates_pass", "status": "FAIL", "evidence_ids": ["ev-1"]},
                {"test_id": "consent_branching", "status": "PASS", "evidence_ids": ["ev-2"]},
            ],
            evidence=[
                {
                    "source": "build_package",
                    "locator": "gates_snapshot.checks.CC-03",
                    "value": "FAIL",
                    "observed_at": "2026-08-20T04:00:00+00:00",
                }
            ],
            minimum_score=80,
        )
        record = WorkflowQaResult.objects.create(
            id=body["qa_run_id"],
            company=self.company,
            package=self.package,
            use_case_id="UC-02",
            score=body["score"],
            status=QA_STATUS_FAIL,
            payload=body,
            created_by=self.user,
        )
        serialized = serialize_qa_result(record)
        self.assertEqual(serialized["qa_run_id"], str(record.id))
        self.assertEqual(serialized["status"], QA_STATUS_FAIL)
        self.assertEqual(serialized["score"], record.score)
        self.assertEqual(serialized["package_id"], str(self.package.id))
        self.assertEqual(len(serialized["hard_tests"]), 2)

    def test_latest_qa_result_for_package_returns_newest(self):
        older = WorkflowQaResult.objects.create(
            company=self.company,
            package=self.package,
            use_case_id="UC-02",
            score=0,
            status=QA_STATUS_FAIL,
            payload={"score": 0, "status": "FAIL", "hard_tests": [], "evidence": []},
            created_by=self.user,
        )
        newer = WorkflowQaResult.objects.create(
            company=self.company,
            package=self.package,
            use_case_id="UC-02",
            score=100,
            status=QA_STATUS_PASS,
            payload={"score": 100, "status": "PASS", "hard_tests": [], "evidence": []},
            created_by=self.user,
        )
        latest = latest_qa_result_for_package(
            company_id=self.company.id,
            package_id=self.package.id,
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, newer.id)
        self.assertNotEqual(latest.id, older.id)

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            build_qa_result_payload(
                qa_run_id="33333333-3333-3333-3333-333333333333",
                company_id=self.company.id,
                package_id=self.package.id,
                use_case_id="UC-02",
                score=0,
                status="Ready",
                hard_tests=[],
                evidence=[],
                minimum_score=80,
            )
