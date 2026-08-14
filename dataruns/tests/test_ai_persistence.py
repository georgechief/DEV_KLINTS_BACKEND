"""PRD-AI-01 Phase B — fingerprints + AiCall/AiSuggestion persistence."""

from __future__ import annotations

from dataruns.ai.constants import (
    DEFAULT_MODEL_ID,
    DEFAULT_PROVIDER,
    POLICY_VERSION,
    PROMPT_FIX_SUGGESTION_V1,
    TASK_FIX_SUGGESTION,
)
from dataruns.ai.fingerprints import compute_fingerprint
from dataruns.ai.persistence import (
    build_envelope,
    create_ai_call,
    get_cached_suggestion,
    upsert_ai_suggestion,
)
from dataruns.ai.schemas import FixSuggestionOutput
from dataruns.dcs.constants import DCS_SCORE_KIND
from dataruns.dcs.enqueue import DCS_SCORE_DATA_RUN_NAME
from dataruns.models import AiCall, AiSuggestion, DataRun
from django.test import TestCase
from tenants.models import Company, Tenant


def _sample_fix_payload(*, check_id: str = "LE-04") -> dict:
    return {
        "task_type": "fix_suggestion",
        "check_id": check_id,
        "headline": "Purchases look duplicated across systems",
        "whats_wrong": "About half of purchases look duplicated.",
        "why_it_matters": "Journeys may fire twice.",
        "suggestions": [
            {
                "step": 1,
                "title": "Confirm Source Of Truth",
                "detail": "Decide which system owns the purchase event.",
            },
            {
                "step": 2,
                "title": "Deduplicate Events",
                "detail": "Follow CheckMaster remediation.",
            },
        ],
        "cautions": ["Do not bulk-delete without a sandbox proof."],
        "confidence": "medium",
    }


def _sample_context(*, dcs_run_id: int = 1, suggested_fix: str = "Dedupe by order id.") -> dict:
    return {
        "task_type": TASK_FIX_SUGGESTION,
        "check_id": "LE-04",
        "check_name": "Duplicate Purchase Events Per Order",
        "suggested_fix": suggested_fix,
        "fix_type": "Automated writeback",
        "fix_owner": "Klints (automated)",
        "finding_summary": {"detail": "Duplicate PURCHASE rate=50%.", "mismatch_count": 0},
        "dcs_run_id": dcs_run_id,
    }


class FingerprintTests(TestCase):
    def test_same_input_same_fingerprint(self):
        ctx = _sample_context()
        a = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=ctx,
        )
        b = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=ctx,
        )
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_fingerprint_changes_when_dcs_run_changes(self):
        base = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(dcs_run_id=10),
        )
        other = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(dcs_run_id=11),
        )
        self.assertNotEqual(base, other)

    def test_fingerprint_changes_when_remediation_changes(self):
        base = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(suggested_fix="Fix A"),
        )
        other = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(suggested_fix="Fix B"),
        )
        self.assertNotEqual(base, other)

    def test_fingerprint_changes_when_prompt_version_bumps(self):
        ctx = _sample_context()
        v1 = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version="ai01.fix_suggestion.v1",
            allowlisted_context=ctx,
        )
        v2 = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version="ai01.fix_suggestion.v2",
            allowlisted_context=ctx,
        )
        self.assertNotEqual(v1, v2)


class AiPersistenceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="AI Co", slug="ai-co")
        self.company = Company.objects.create(
            tenant=self.tenant,
            name="Lumera Skin",
            domain="lumera.example.com",
        )
        self.run = DataRun.objects.create(
            tenant=self.tenant,
            name=DCS_SCORE_DATA_RUN_NAME,
            status=DataRun.Status.SUCCEEDED,
            metadata={"kind": DCS_SCORE_KIND, "company_id": str(self.company.id)},
        )
        self.fingerprint = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(dcs_run_id=self.run.id),
        )
        self.payload = _sample_fix_payload()

    def test_create_ai_call_gate_denied_without_suggestion(self):
        call = create_ai_call(
            company=self.company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            policy_version=POLICY_VERSION,
            model=DEFAULT_MODEL_ID,
            provider=DEFAULT_PROVIDER,
            status=AiCall.Status.GATE_DENIED,
            check_id="LE-04",
            dcs_data_run=self.run,
            error_code="pii_remaining",
        )
        self.assertEqual(AiCall.objects.count(), 1)
        self.assertEqual(call.status, AiCall.Status.GATE_DENIED)
        self.assertEqual(AiSuggestion.objects.count(), 0)

    def test_upsert_creates_suggestion_on_success(self):
        call = create_ai_call(
            company=self.company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            policy_version=POLICY_VERSION,
            model=DEFAULT_MODEL_ID,
            provider=DEFAULT_PROVIDER,
            status=AiCall.Status.SUCCESS,
            check_id="LE-04",
            dcs_data_run=self.run,
            latency_ms=420,
            input_tokens=100,
            output_tokens=200,
        )
        suggestion = upsert_ai_suggestion(
            company=self.company,
            ai_call=call,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            payload=self.payload,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        self.assertEqual(AiSuggestion.objects.count(), 1)
        self.assertEqual(suggestion.headline, self.payload["headline"])
        self.assertEqual(suggestion.payload_json["check_id"], "LE-04")
        self.assertIsInstance(
            FixSuggestionOutput.model_validate(suggestion.payload_json),
            FixSuggestionOutput,
        )

    def test_get_cached_suggestion_hit(self):
        call = create_ai_call(
            company=self.company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            policy_version=POLICY_VERSION,
            model=DEFAULT_MODEL_ID,
            provider=DEFAULT_PROVIDER,
            status=AiCall.Status.SUCCESS,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        created = upsert_ai_suggestion(
            company=self.company,
            ai_call=call,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            payload=self.payload,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        cached = get_cached_suggestion(
            company=self.company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
        )
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.id, created.id)
        self.assertEqual(cached.payload_json["headline"], self.payload["headline"])

    def test_upsert_same_fingerprint_updates_row(self):
        call1 = create_ai_call(
            company=self.company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            policy_version=POLICY_VERSION,
            model=DEFAULT_MODEL_ID,
            provider=DEFAULT_PROVIDER,
            status=AiCall.Status.SUCCESS,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        first = upsert_ai_suggestion(
            company=self.company,
            ai_call=call1,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            payload=self.payload,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        call2 = create_ai_call(
            company=self.company,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            policy_version=POLICY_VERSION,
            model=DEFAULT_MODEL_ID,
            provider=DEFAULT_PROVIDER,
            status=AiCall.Status.SUCCESS,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        updated_payload = dict(self.payload)
        updated_payload["headline"] = "Updated headline after re-run"
        second = upsert_ai_suggestion(
            company=self.company,
            ai_call=call2,
            task_type=TASK_FIX_SUGGESTION,
            fingerprint=self.fingerprint,
            payload=updated_payload,
            check_id="LE-04",
            dcs_data_run=self.run,
        )
        self.assertEqual(AiSuggestion.objects.count(), 1)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.headline, "Updated headline after re-run")
        self.assertEqual(second.ai_call_id, call2.id)

    def test_new_fingerprint_creates_new_suggestion_row(self):
        fp_a = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(dcs_run_id=self.run.id, suggested_fix="A"),
        )
        fp_b = compute_fingerprint(
            task_type=TASK_FIX_SUGGESTION,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            allowlisted_context=_sample_context(dcs_run_id=self.run.id, suggested_fix="B"),
        )
        for fp in (fp_a, fp_b):
            call = create_ai_call(
                company=self.company,
                task_type=TASK_FIX_SUGGESTION,
                fingerprint=fp,
                prompt_version=PROMPT_FIX_SUGGESTION_V1,
                policy_version=POLICY_VERSION,
                model=DEFAULT_MODEL_ID,
                provider=DEFAULT_PROVIDER,
                status=AiCall.Status.SUCCESS,
                check_id="LE-04",
                dcs_data_run=self.run,
            )
            upsert_ai_suggestion(
                company=self.company,
                ai_call=call,
                task_type=TASK_FIX_SUGGESTION,
                fingerprint=fp,
                payload=self.payload,
                check_id="LE-04",
                dcs_data_run=self.run,
            )
        self.assertEqual(AiSuggestion.objects.count(), 2)

    def test_build_envelope_shape(self):
        env = build_envelope(
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
            policy_version=POLICY_VERSION,
            model=DEFAULT_MODEL_ID,
            provider=DEFAULT_PROVIDER,
            fingerprint=self.fingerprint,
            output=self.payload,
        )
        self.assertEqual(env["schema_version"], 1)
        self.assertEqual(env["prompt_version"], PROMPT_FIX_SUGGESTION_V1)
        self.assertEqual(env["fingerprint"], self.fingerprint)
        self.assertEqual(env["output"]["task_type"], "fix_suggestion")
