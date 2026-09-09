"""PRD-GAP-01 Slice A1 — pack schema + plan data alignment (Phases 1–4)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import DataRun
from dataruns.orchestration.candidates import build_fix_task_dict
from dataruns.orchestration.models import OrchestrationTask
from dataruns.orchestration.plan import build_plan
from dataruns.orchestration.scoring import build_priority_explain
from dataruns.orchestration.task_constants import (
    ORCH_ALLOWED_STATUS_TRANSITIONS,
    ORCH_STATUS_ENUM,
    ORCH_TASK_SCHEMA_VERSION,
    ORCH_TASK_TYPE_ENUM,
    ORCH_TERMINAL_STATUSES,
    build_default_provenance,
    is_allowed_orch_transition,
    serialize_orch_task,
)
from dataruns.orchestration.task_transitions import (
    OrchTransitionError,
    create_orchestration_task,
)
from tenants.models import Company, Tenant, User

PACK_SCHEMA_REL = (
    "Klints_MVP1_Rohan_Build_Pack_v1.2_20260718"
    "/03_Machine_Contracts/orchestration_task.schema.json"
)

PRD_TRANSITIONS = {
    ("PENDING", "READY"),
    ("PENDING", "BLOCKED"),
    ("PENDING", "CANCELLED"),
    ("BLOCKED", "READY"),
    ("BLOCKED", "CANCELLED"),
    ("READY", "IN_PROGRESS"),
    ("READY", "CANCELLED"),
    ("IN_PROGRESS", "AWAITING_APPROVAL"),
    ("IN_PROGRESS", "DONE"),
    ("IN_PROGRESS", "FAILED"),
    ("AWAITING_APPROVAL", "IN_PROGRESS"),
    ("AWAITING_APPROVAL", "DONE"),
    ("AWAITING_APPROVAL", "FAILED"),
    ("AWAITING_APPROVAL", "CANCELLED"),
    ("FAILED", "READY"),
    ("FAILED", "CANCELLED"),
}


def _load_pack_schema() -> dict:
    path = Path(settings.BASE_DIR) / PACK_SCHEMA_REL
    return json.loads(path.read_text(encoding="utf-8"))


class OrchSmPackSchemaAlignmentTests(SimpleTestCase):
    def test_pack_status_enum_matches_constants(self):
        schema = _load_pack_schema()
        pack_statuses = set(schema["properties"]["status"]["enum"])
        self.assertEqual(pack_statuses, set(ORCH_STATUS_ENUM))
        self.assertEqual(len(pack_statuses), 8)

    def test_pack_task_type_enum_matches_constants(self):
        schema = _load_pack_schema()
        pack_types = set(schema["properties"]["task_type"]["enum"])
        self.assertEqual(pack_types, set(ORCH_TASK_TYPE_ENUM))
        self.assertEqual(len(pack_types), 11)

    def test_pack_schema_version_matches_constants(self):
        schema = _load_pack_schema()
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            ORCH_TASK_SCHEMA_VERSION,
        )

    def test_prd_transition_graph_matches_implementation(self):
        self.assertEqual(ORCH_ALLOWED_STATUS_TRANSITIONS, PRD_TRANSITIONS)
        self.assertEqual(len(PRD_TRANSITIONS), 16)
        for terminal in ORCH_TERMINAL_STATUSES:
            for status in ORCH_STATUS_ENUM:
                if status == terminal:
                    continue
                self.assertFalse(
                    is_allowed_orch_transition(from_status=terminal, to_status=status),
                    msg=f"{terminal} -> {status}",
                )

    def test_serialize_includes_all_pack_required_fields(self):
        schema = _load_pack_schema()
        required = set(schema["required"])
        # API adds id/title/check_id/priority_class — pack required must be subset of serialize keys
        fake_record = OrchestrationTask(
            id=uuid.uuid4(),
            task_id="FIX-CC-03",
            task_type="FIX",
            status="READY",
            check_id="CC-03",
            priority_class="P0",
            priority_inputs={
                "blocker_status": 1,
                "severity_risk": 1,
                "dependency_readiness": 1,
                "effort_impact": 1,
            },
            priority_score=1.0,
            depends_on=[],
            wave=0,
            capability_dependencies=[],
            approval={},
            idempotency_key="co:FIX-CC-03:dcs:1",
            provenance=build_default_provenance(),
        )
        fake_record.company_id = "00000000-0000-0000-0000-000000000001"
        body = serialize_orch_task(fake_record)
        missing = required - set(body.keys())
        self.assertEqual(missing, set(), msg=f"missing pack required keys: {sorted(missing)}")


class OrchSmPlanDataAlignmentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Pack Align Co", slug="pack-align")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Pack Align Co",
            domain="pack-align.example.com",
        )
        self.analyst = User.objects.create_user(
            email="pack-align@example.com",
            password="pass",
            tenant=self.tenant,
            role=User.Role.ANALYST,
        )

    def _seed_dcs_issue(self) -> DataRun:
        return DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 62.0,
                "dcs_run": {
                    "run_state": "CONDITIONALLY_READY",
                    "headline_score": 62.0,
                    "check_results": [
                        {
                            "check_id": "CC-03",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "Consent mismatch",
                            "provenance": {
                                "revenue_impact": 500.0,
                                "revenue_currency": "USD",
                            },
                        }
                    ],
                },
                "check_results": [
                    {
                        "check_id": "CC-03",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Consent mismatch",
                        "provenance": {
                            "revenue_impact": 500.0,
                            "revenue_currency": "USD",
                        },
                    }
                ],
            },
        )

    def test_plan_fix_task_fields_compatible_with_persisted_create(self):
        run = self._seed_dcs_issue()
        plan = build_plan(company=self.company)
        self.assertIsNone(plan["reason"])
        self.assertEqual(len(plan["tasks"]), 1)

        plan_task = plan["tasks"][0]
        self.assertEqual(plan_task["task_id"], "FIX-CC-03")
        self.assertEqual(plan_task["task_type"], "FIX")
        self.assertEqual(plan_task["status"], "READY")
        self.assertEqual(plan_task["check_id"], "CC-03")
        self.assertEqual(
            plan_task["idempotency_key"],
            f"{self.company.id}:FIX-CC-03:dcs:{run.id}",
        )

        outcome = create_orchestration_task(
            company=self.company,
            actor=self.analyst,
            task_id=plan_task["task_id"],
            task_type=plan_task["task_type"],
            status=plan_task["status"],
            title=plan_task["title"],
            check_id=plan_task["check_id"],
            priority_inputs=plan_task["priority_inputs"],
            priority_score=plan_task["priority_score"],
            priority_class=plan_task["priority_class"],
            idempotency_key=plan_task["idempotency_key"],
            source_refs={"dcs_data_run_id": run.id},
        )
        body = serialize_orch_task(outcome.record)

        self.assertEqual(body["task_id"], plan_task["task_id"])
        self.assertEqual(body["task_type"], plan_task["task_type"])
        self.assertEqual(body["status"], plan_task["status"])
        self.assertEqual(body["check_id"], plan_task["check_id"])
        self.assertEqual(body["idempotency_key"], plan_task["idempotency_key"])
        self.assertEqual(body["priority_inputs"], plan_task["priority_inputs"])
        self.assertEqual(body["priority_score"], plan_task["priority_score"])
        self.assertEqual(body["priority_class"], plan_task["priority_class"])
        self.assertEqual(body["tenant_id"], str(self.company.id))
        self.assertEqual(body["source_refs"]["dcs_data_run_id"], run.id)

    def test_build_fix_task_dict_idempotency_matches_plan_pattern(self):
        issue = {
            "check_id": "CC-03",
            "title": "Fix CC-03",
            "revenue_impact": 100.0,
            "currency": "USD",
        }
        inputs = {
            "blocker_status": 2,
            "severity_risk": 1,
            "dependency_readiness": 2,
            "effort_impact": 1,
        }
        explain = build_priority_explain(inputs)
        task = build_fix_task_dict(
            issue=issue,
            company_id=self.company.id,
            data_run_id=99,
            priority_inputs=inputs,
            priority_score=1.5,
            priority_class="P0",
            priority_explain=explain,
        )
        self.assertEqual(task["task_id"], "FIX-CC-03")
        self.assertEqual(
            task["idempotency_key"],
            f"{self.company.id}:FIX-CC-03:dcs:99",
        )

    def test_create_rejects_non_dict_approval(self):
        with self.assertRaises(OrchTransitionError) as ctx:
            create_orchestration_task(
                company=self.company,
                actor=self.analyst,
                task_id="FIX-CC-04",
                task_type="FIX",
                status="READY",
                priority_inputs={
                    "blocker_status": 0,
                    "severity_risk": 0,
                    "dependency_readiness": 0,
                    "effort_impact": 0,
                },
                approval="not-a-dict",
                idempotency_key=f"{self.company.id}:FIX-CC-04:dcs:bad-approval",
            )
        self.assertEqual(ctx.exception.code, "validation_error")
        self.assertEqual(ctx.exception.status, 400)
