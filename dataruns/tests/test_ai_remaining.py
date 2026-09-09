"""PRD-AI-01 remaining tasks — explain_finding, report_narrative, nba_blurb."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from unittest.mock import patch

from dataruns.ai.complete import complete_json
from dataruns.ai.constants import (
    DEFAULT_MODEL_ID,
    PROMPT_EXPLAIN_FINDING_V1,
    PROMPT_NBA_BLURB_V1,
    PROMPT_REPORT_NARRATIVE_V1,
    TASK_EXPLAIN_FINDING,
    TASK_NBA_BLURB,
    TASK_REPORT_NARRATIVE,
)
from dataruns.ai.exceptions import AiGateDeniedError, AiJsonRetryExhaustedError, AiProviderError
from dataruns.ai.providers.base import AiProvider, ProviderResult
from dataruns.ai.providers.mock import MockAiProvider
from dataruns.ai.service import (
    get_or_create_explain_finding,
    get_or_create_nba_blurb,
    get_or_create_report_narrative,
)
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import (
    AiCall,
    AiSuggestion,
    AssessmentReport,
    CheckMaster,
    DataRun,
    DimensionMaster,
)
from dataruns.reports.compose import compose_assessment_report
from dataruns.reports.render_pdf import render_assessment_pdf
from tenants.models import Company, Tenant, User


def _seed_masters() -> None:
    dim = DimensionMaster.objects.filter(dimension_id="02").first()
    if dim is None:
        dim = DimensionMaster.objects.create(
            dimension_id="02",
            key="02 Lifecycle Event",
            name="Lifecycle Event",
            purpose="",
        )
    if not CheckMaster.objects.filter(check_id="LE-04").exists():
        CheckMaster.objects.create(
            sequence=204,
            check_id="LE-04",
            check_name="Duplicate purchase events per order",
            dimension=dim,
            check_class=CheckMaster.CheckClass.RULE_BASED,
            check_type="Consistency",
            role=CheckMaster.Role.SCORED,
            cadence="Daily",
            phase="MVP1-A",
            systems_compared="Shopify / Manago",
            numeric_weight=5,
            severity=CheckMaster.Severity.HIGH,
            root_cause_ids=[],
            suggested_fix="Deduplicate PURCHASE events by order externalId.",
            fix_type="Automated writeback",
            fix_owner="Klints (automated)",
        )


class WrongExplainCheckIdProvider(AiProvider):
    name = "wrong_explain"

    def __init__(self) -> None:
        self.attempts = 0

    def complete_json(self, **kwargs) -> ProviderResult:
        self.attempts += 1
        return ProviderResult(
            text=(
                '{"task_type":"explain_finding","check_id":"ZZ-99",'
                '"headline":"x","explanation":"y y.","systems":[]}'
            ),
            model=kwargs["model"],
            provider=self.name,
        )


class WrongNbaCheckIdProvider(AiProvider):
    name = "wrong_nba"

    def __init__(self) -> None:
        self.attempts = 0

    def complete_json(self, **kwargs) -> ProviderResult:
        self.attempts += 1
        return ProviderResult(
            text='{"task_type":"nba_blurb","check_id":"ZZ-99","blurb":"Next item."}',
            model=kwargs["model"],
            provider=self.name,
        )


class PiiExplainProvider(AiProvider):
    name = "pii_explain"

    def __init__(self) -> None:
        self.attempts = 0

    def complete_json(self, **kwargs) -> ProviderResult:
        self.attempts += 1
        return ProviderResult(
            text=(
                '{"task_type":"explain_finding","check_id":"LE-04",'
                '"headline":"x","explanation":"Contact alice@brand.com drifted.",'
                '"systems":[]}'
            ),
            model=kwargs["model"],
            provider=self.name,
        )


class RemainingCheckIdMismatchTests(SimpleTestCase):
    def test_explain_mismatch_exhausts_retries(self):
        provider = WrongExplainCheckIdProvider()
        with self.assertRaises(AiJsonRetryExhaustedError):
            complete_json(
                provider=provider,
                task_type=TASK_EXPLAIN_FINDING,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=3,
            )
        self.assertEqual(provider.attempts, 3)

    def test_nba_mismatch_exhausts_retries(self):
        provider = WrongNbaCheckIdProvider()
        with self.assertRaises(AiJsonRetryExhaustedError):
            complete_json(
                provider=provider,
                task_type=TASK_NBA_BLURB,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=3,
            )
        self.assertEqual(provider.attempts, 3)

    def test_pii_in_explain_output_fail_closed(self):
        provider = PiiExplainProvider()
        with self.assertRaises(AiJsonRetryExhaustedError) as ctx:
            complete_json(
                provider=provider,
                task_type=TASK_EXPLAIN_FINDING,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=3,
            )
        self.assertEqual(provider.attempts, 3)
        self.assertNotIn("alice@", str(ctx.exception))


@override_settings(AI_ENABLED=True, AI_PROVIDER="mock", MISTRAL_API_KEY="")
class RemainingAiServiceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="AI Remaining", slug="ai-remaining")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="lumera.example.com",
        )
        self.admin = User.objects.create_user(
            email="admin@ai-remaining.example.com",
            password="TestPass123!",
            name="Admin",
            tenant=self.tenant,
            role=User.Role.ADMIN,
            email_verified=True,
            is_active=True,
        )
        _seed_masters()
        self.run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={
                "kind": DCS_SCORE_KIND,
                "company_id": str(self.company.id),
                "headline_score": 69.28,
                "dcs_run": {
                    "run_state": "SCORED",
                    "headline_score": 69.28,
                    "check_results": [
                        {
                            "check_id": "LE-04",
                            "status": "FAIL",
                            "severity": "high",
                            "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                        }
                    ],
                },
                "check_results": [
                    {
                        "check_id": "LE-04",
                        "status": "FAIL",
                        "severity": "high",
                        "message": "Duplicate PURCHASE rate=50.00% clusters=8.",
                    }
                ],
            },
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_explain_schema_and_cache(self):
        first = get_or_create_explain_finding(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertEqual(first.suggestion.payload_json["task_type"], "explain_finding")
        self.assertEqual(first.suggestion.payload_json["check_id"], "LE-04")
        self.assertTrue(first.suggestion.payload_json["headline"])
        self.assertTrue(first.suggestion.payload_json["explanation"])
        self.assertEqual(first.prompt_version, PROMPT_EXPLAIN_FINDING_V1)
        second = get_or_create_explain_finding(
            company=self.company,
            check_id="LE-04",
            provider=MockAiProvider(),
        )
        self.assertTrue(second.cached)
        self.assertEqual(second.suggestion.id, first.suggestion.id)

    def test_nba_schema_and_plan_rank(self):
        result = get_or_create_nba_blurb(
            company=self.company,
            check_id="LE-04",
            plan_rank=1,
            provider=MockAiProvider(),
        )
        self.assertEqual(result.suggestion.payload_json["task_type"], "nba_blurb")
        self.assertEqual(result.suggestion.payload_json["check_id"], "LE-04")
        self.assertTrue(result.suggestion.payload_json["blurb"])
        self.assertEqual(result.prompt_version, PROMPT_NBA_BLURB_V1)

    def test_report_narrative_schema(self):
        result = get_or_create_report_narrative(
            company=self.company,
            dcs_run_id=self.run.id,
            provider=MockAiProvider(),
        )
        payload = result.suggestion.payload_json
        self.assertEqual(payload["task_type"], "report_narrative")
        self.assertTrue(payload["exec_summary"])
        self.assertGreaterEqual(len(payload["top_themes"]), 1)
        self.assertTrue(payload["recommended_focus"])
        self.assertEqual(result.prompt_version, PROMPT_REPORT_NARRATIVE_V1)
        self.assertEqual(result.suggestion.check_id, "")

    def test_report_compose_attaches_outside_hashed_payload(self):
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": self.run.id, "include_architecture": False},
        )
        self.assertTrue(report.ai_narratives)
        narrative = report.ai_narratives["report_narrative"]
        self.assertEqual(narrative["task_type"], "report_narrative")
        self.assertNotIn("exec_summary", str(report.payload.get("content") or {}))
        self.assertEqual(report.payload["payload_hash"], report.payload_hash)

    def test_report_compose_fail_open_when_ai_down(self):
        with patch(
            "dataruns.ai.service.get_or_create_report_narrative",
            side_effect=AiProviderError("down"),
        ):
            report = compose_assessment_report(
                company=self.company,
                user=self.admin,
                body={"dcs_run_id": self.run.id, "include_architecture": False},
            )
        self.assertEqual(report.status, AssessmentReport.Status.READY)
        self.assertFalse(report.ai_narratives)

    def test_pdf_in_brief_optional(self):
        report = compose_assessment_report(
            company=self.company,
            user=self.admin,
            body={"dcs_run_id": self.run.id, "include_architecture": False},
        )
        without_ai = render_assessment_pdf(report.payload)
        with_ai = render_assessment_pdf(
            report.payload,
            ai_narratives=report.ai_narratives,
        )
        self.assertTrue(without_ai.startswith(b"%PDF"))
        self.assertTrue(with_ai.startswith(b"%PDF"))
        self.assertNotEqual(with_ai, without_ai)
        self.assertGreater(len(with_ai), len(without_ai))

    def test_explain_api(self):
        first = self.client.post(
            "/api/v1/ai/suggestions/explain/",
            {"check_id": "LE-04", "dcs_run_id": self.run.id},
            format="json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["payload"]["task_type"], "explain_finding")
        second = self.client.post(
            "/api/v1/ai/suggestions/explain/",
            {"check_id": "LE-04", "dcs_run_id": self.run.id},
            format="json",
        )
        self.assertTrue(second.data["cached"])

    def test_nba_api(self):
        response = self.client.post(
            "/api/v1/ai/suggestions/nba/",
            {"check_id": "LE-04", "plan_rank": 1, "dcs_run_id": self.run.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["payload"]["task_type"], "nba_blurb")

    def test_report_narrative_api_attaches(self):
        with patch(
            "dataruns.ai.service.get_or_create_report_narrative",
            side_effect=AiProviderError("skip"),
        ):
            report_plain = compose_assessment_report(
                company=self.company,
                user=self.admin,
                body={"dcs_run_id": self.run.id, "include_architecture": False},
            )
        self.assertFalse(report_plain.ai_narratives)
        response = self.client.post(
            "/api/v1/ai/narratives/report/",
            {
                "dcs_run_id": self.run.id,
                "assessment_report_id": str(report_plain.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["payload"]["task_type"], "report_narrative")
        report_plain.refresh_from_db()
        self.assertTrue(report_plain.ai_narratives)

    def test_gate_denied_explain_422(self):
        from dataruns.ai.privacy_gate import GateResult

        denied = GateResult(ok=False, reason_code="pii_remaining", context=None)
        with patch("dataruns.ai.runner.ensure_safe_context", return_value=denied):
            response = self.client.post(
                "/api/v1/ai/suggestions/explain/",
                {"check_id": "LE-04"},
                format="json",
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.data["code"], "gate_denied")
        self.assertEqual(
            AiSuggestion.objects.filter(task_type=TASK_EXPLAIN_FINDING).count(),
            0,
        )
        self.assertEqual(AiCall.objects.filter(status=AiCall.Status.GATE_DENIED).count(), 1)

    def test_compose_gate_denied_still_saves_report(self):
        with patch(
            "dataruns.ai.service.get_or_create_report_narrative",
            side_effect=AiGateDeniedError(reason="pii_remaining"),
        ):
            report = compose_assessment_report(
                company=self.company,
                user=self.admin,
                body={"dcs_run_id": self.run.id, "include_architecture": False},
            )
        self.assertEqual(report.status, AssessmentReport.Status.READY)
        self.assertFalse(report.ai_narratives)
