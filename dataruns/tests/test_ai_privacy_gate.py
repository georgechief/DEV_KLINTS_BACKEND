"""PRD-AI-01 Phase A — PrivacyGate, allowlist, schemas, prompts."""

from __future__ import annotations

import json
import re

from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError

from dataruns.ai.allowlist import project, project_fix_suggestion_context
from dataruns.ai.constants import (
    ALLOWLIST_VERSION,
    MAX_MISMATCH_ROWS,
    POLICY_VERSION,
    PROMPT_FIX_SUGGESTION_V1,
    PROMPT_SYSTEM_V1,
)
from dataruns.ai.privacy_gate import (
    ensure_safe_context,
    sanitize_mismatch_list,
    scrub_text,
    text_still_has_pii,
)
from dataruns.ai.prompts import fix_suggestion_prompt_v1, load_prompt, system_prompt_v1
from dataruns.ai.schemas import FixSuggestionOutput, parse_task_output

_FORBIDDEN_LEAK_KEYS = frozenset(
    {
        "value",
        "raw",
        "sample",
        "email",
        "phone",
        "authorization",
        "password",
        "token",
        "api_key",
        "apikey",
    }
)
_EMAIL_IN_TEXT = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BEARER_IN_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")


def _assert_no_leaks(obj, *, path: str = "root") -> None:
    """Recursively assert no forbidden keys or obvious PII/secrets in gated context."""
    if isinstance(obj, str):
        assert not _EMAIL_IN_TEXT.search(obj), f"email leak at {path}: {obj!r}"
        assert not _BEARER_IN_TEXT.search(obj), f"bearer leak at {path}: {obj!r}"
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_l = str(key).lower().replace("-", "_")
            assert key_l not in _FORBIDDEN_LEAK_KEYS, f"forbidden key at {path}.{key}"
            _assert_no_leaks(value, path=f"{path}.{key}")
        return
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            _assert_no_leaks(item, path=f"{path}[{idx}]")
        return


class PrivacyGateScrubTests(SimpleTestCase):
    def test_scrub_email_and_bearer(self):
        raw = "Contact alice@brand.com Authorization: Bearer sk-live-abc123"
        out = scrub_text(raw)
        self.assertNotIn("alice@brand.com", out)
        self.assertNotIn("sk-live-abc123", out)
        self.assertIn("[redacted-email]", out)
        self.assertIn("Authorization=****", out)

    def test_scrub_shopify_token(self):
        out = scrub_text("token=shpat_abcDEF1234567890")
        self.assertNotIn("shpat_abcDEF1234567890", out)

    def test_mismatch_drops_value_raw_sample(self):
        rows = sanitize_mismatch_list(
            [
                {
                    "path": "contact.email",
                    "kind": "conflict",
                    "side": "shopify",
                    "value": "alice@brand.com",
                    "raw": {"email": "alice@brand.com"},
                    "sample": "alice@brand.com",
                }
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "contact.email")
        self.assertEqual(rows[0]["kind"], "conflict")
        self.assertNotIn("value", rows[0])
        self.assertNotIn("raw", rows[0])
        self.assertNotIn("sample", rows[0])

    def test_mismatch_list_capped(self):
        rows = sanitize_mismatch_list(
            [{"path": f"field.{i}", "kind": "missing", "side": "manago"} for i in range(40)]
        )
        self.assertEqual(len(rows), MAX_MISMATCH_ROWS)

    def test_ensure_safe_strips_mismatch_values_and_passes(self):
        result = ensure_safe_context(
            {
                "check_id": "LE-04",
                "check_name": "Duplicate Purchase Events",
                "mismatches": [
                    {
                        "path": "order.externalId",
                        "kind": "conflict",
                        "side": "shopify",
                        "value": "alice@brand.com",
                    }
                ],
            }
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.gate, "pass")
        self.assertEqual(result.reason_code, "pass")
        assert result.context is not None
        self.assertEqual(result.context["mismatches"][0]["path"], "order.externalId")
        self.assertNotIn("value", result.context["mismatches"][0])

    def test_ensure_safe_scrubs_email_in_free_text(self):
        result = ensure_safe_context(
            {
                "check_id": "CI-13",
                "detail": "mailto:merchant@example.com please reply",
            }
        )
        self.assertTrue(result.ok)
        assert result.context is not None
        self.assertNotIn("merchant@example.com", str(result.context))
        self.assertIn("[redacted-email]", result.context["detail"])

    def test_scan_denies_when_pii_still_present(self):
        """Fail-closed scanner: if scrub somehow left PII, gate denies."""
        from dataruns.ai.privacy_gate import _scan_for_leaks

        self.assertEqual(
            _scan_for_leaks({"detail": "reach me at ops@klints.test ASAP"}),
            "pii_remaining",
        )
        self.assertEqual(
            _scan_for_leaks({"auth": "Bearer sk-live-still-here"}),
            "secret_remaining",
        )
        self.assertIsNone(
            _scan_for_leaks({"detail": "About half of purchases look duplicated."})
        )
        self.assertTrue(text_still_has_pii("reach me at ops@klints.test ASAP"))
        self.assertFalse(text_still_has_pii("About half of purchases look duplicated."))

    def test_ensure_safe_denies_empty_context(self):
        denied = ensure_safe_context({})
        self.assertFalse(denied.ok)
        self.assertEqual(denied.reason_code, "empty_context")
        self.assertEqual(denied.gate, "deny")

    def test_gate_never_returns_rejected_body_on_deny(self):
        denied = ensure_safe_context(None)
        self.assertFalse(denied.ok)
        self.assertIsNone(denied.context)


class AllowlistTests(SimpleTestCase):
    def test_project_drops_unknown_keys(self):
        out = project(
            {
                "check_id": "LE-04",
                "email": "alice@brand.com",
                "staff_email": "admin@klints.io",
                "suggested_fix": "Deduplicate PURCHASE events.",
            }
        )
        self.assertIn("check_id", out)
        self.assertIn("suggested_fix", out)
        self.assertNotIn("email", out)
        self.assertNotIn("staff_email", out)

    def test_project_fix_suggestion_strips_mismatch_values(self):
        ctx = project_fix_suggestion_context(
            issue={
                "check_id": "LE-04",
                "title": "duplicate purchase events per order",
                "dimension": "02 Lifecycle Event",
                "severity": "high",
                "status": "FAIL",
                "systems_compared": "Shopify / Manago",
                "suggested_fix": "Deduplicate PURCHASE events by order externalId.",
                "fix_type": "Automated writeback",
                "fix_owner": "Klints (automated)",
                "detail": "Duplicate PURCHASE rate=50.00% clusters=8.",
                "revenue_impact": 4200.0,
                "currency": "USD",
                "mismatches": [
                    {
                        "path": "contact.email",
                        "kind": "conflict",
                        "side": "shopify",
                        "value": "alice@brand.com",
                    }
                ],
            },
            company_name="Lumera Skin",
            company_domain="localhost",
            dcs_run_id=150,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
        )
        self.assertEqual(ctx["check_id"], "LE-04")
        self.assertEqual(ctx["check_name"], "Duplicate Purchase Events Per Order")
        self.assertIn("Shopify", ctx["systems_compared"])
        self.assertEqual(ctx["revenue_impact"], 4200.0)
        self.assertEqual(ctx["currency"], "USD")
        self.assertNotIn("company_hostname", ctx)  # localhost omitted
        self.assertEqual(ctx["policy_version"], POLICY_VERSION)
        self.assertEqual(ctx["allowlist_version"], ALLOWLIST_VERSION)
        mismatches = ctx["finding_summary"]["mismatches"]
        self.assertEqual(mismatches[0]["path"], "contact.email")
        self.assertNotIn("value", mismatches[0])

        gated = ensure_safe_context(ctx)
        self.assertTrue(gated.ok)

    def test_allowlisted_only_payload_passes_gate(self):
        ctx = project_fix_suggestion_context(
            issue={
                "check_id": "ME-08",
                "title": "Baseline computability",
                "status": "FAIL",
                "severity": "medium",
                "suggested_fix": "Extend history window.",
                "fix_type": "Configuration",
                "fix_owner": "Data lead",
                "detail": "Baseline not computable; gaps=['history'].",
                "systems_compared": "Manago",
            },
            company_name="Lumera Skin",
            company_domain="lumera.example.com",
        )
        self.assertEqual(ctx.get("company_hostname"), "lumera.example.com")
        result = ensure_safe_context(ctx)
        self.assertTrue(result.ok)

    @override_settings(AI_PRIVACY_POLICY_VERSION="policy-test-v2")
    def test_policy_version_from_settings(self):
        ctx = project_fix_suggestion_context(
            issue={
                "check_id": "LE-04",
                "title": "Duplicate purchase events",
                "status": "FAIL",
                "severity": "high",
                "suggested_fix": "Deduplicate.",
                "fix_type": "Automated writeback",
                "fix_owner": "Klints",
                "detail": "Duplicate rate=50%.",
            },
            company_name="Lumera Skin",
            policy_version="policy-test-v2",
        )
        self.assertEqual(ctx["policy_version"], "policy-test-v2")

    def test_evidence_preview_maps_to_shapes_without_values(self):
        ctx = project_fix_suggestion_context(
            issue={
                "check_id": "LE-04",
                "title": "Duplicate purchase events",
                "status": "FAIL",
                "severity": "high",
                "suggested_fix": "Deduplicate.",
                "fix_type": "Automated writeback",
                "fix_owner": "Klints",
                "detail": "Duplicate rate=50%.",
                "evidence_preview": [
                    {
                        "source": "shopify",
                        "locator": "order.externalId",
                        "observed_at": "2026-01-01T00:00:00Z",
                        "value": "alice@brand.com",
                    }
                ],
            },
            company_name="Lumera Skin",
        )
        shapes = ctx["finding_summary"]["mismatches"]
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["path"], "order.externalId")
        self.assertEqual(shapes[0]["side"], "shopify")
        self.assertNotIn("value", shapes[0])
        gated = ensure_safe_context(ctx)
        self.assertTrue(gated.ok)
        assert gated.context is not None
        _assert_no_leaks(gated.context)

    def test_end_to_end_pii_in_mismatches_never_reaches_model_context(self):
        issue = {
            "check_id": "LE-04",
            "title": "Duplicate purchase events per order",
            "dimension": "02 Lifecycle Event",
            "severity": "high",
            "status": "FAIL",
            "systems_compared": "Shopify / Manago",
            "suggested_fix": "Contact alice@brand.com is wrong — dedupe by order externalId.",
            "fix_type": "Automated writeback",
            "fix_owner": "Klints (automated)",
            "detail": "Duplicate PURCHASE rate=50.00% clusters=8. Bearer sk-live-secret",
            "revenue_impact": 4200.0,
            "currency": "USD",
            "mismatches": [
                {
                    "path": "contact.email",
                    "kind": "conflict",
                    "side": "shopify",
                    "value": "alice@brand.com",
                    "raw": {"email": "alice@brand.com"},
                }
            ],
        }
        ctx = project_fix_suggestion_context(
            issue=issue,
            company_name="Lumera Skin",
            company_domain="lumera.example.com",
            dcs_run_id=150,
            prompt_version=PROMPT_FIX_SUGGESTION_V1,
        )
        gated = ensure_safe_context(ctx)
        self.assertTrue(gated.ok)
        assert gated.context is not None
        _assert_no_leaks(gated.context)
        serialized = json.dumps(gated.context)
        self.assertNotIn("alice@brand.com", serialized)
        self.assertNotIn("sk-live-secret", serialized)
        self.assertNotIn('"value"', serialized)

    def test_empty_mismatches_falls_back_to_evidence_preview(self):
        ctx = project_fix_suggestion_context(
            issue={
                "check_id": "LE-04",
                "title": "Duplicate purchase events",
                "status": "FAIL",
                "severity": "high",
                "suggested_fix": "Deduplicate.",
                "fix_type": "Automated writeback",
                "fix_owner": "Klints",
                "detail": "Duplicate rate=50%.",
                "mismatches": [],
                "evidence_preview": [
                    {
                        "source": "shopify",
                        "locator": "order.externalId",
                        "value": "alice@brand.com",
                    }
                ],
            },
            company_name="Lumera Skin",
        )
        shapes = ctx["finding_summary"]["mismatches"]
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["path"], "order.externalId")
        self.assertNotIn("value", shapes[0])


class SchemaAndPromptTests(SimpleTestCase):
    def test_fix_suggestion_schema_valid(self):
        payload = {
            "task_type": "fix_suggestion",
            "check_id": "le-04",
            "headline": "Purchases look duplicated across systems",
            "whats_wrong": "About half of purchases look duplicated.",
            "why_it_matters": "Downstream journeys may fire twice.",
            "suggestions": [
                {
                    "step": 1,
                    "title": "Confirm Source Of Truth",
                    "detail": "Decide which system owns the purchase event.",
                },
                {
                    "step": 2,
                    "title": "Deduplicate Events",
                    "detail": "Follow CheckMaster: dedupe by order externalId.",
                },
            ],
            "cautions": ["Do not bulk-delete without a sandbox proof."],
            "confidence": "medium",
        }
        model = parse_task_output("fix_suggestion", payload)
        assert isinstance(model, FixSuggestionOutput)
        self.assertEqual(model.check_id, "LE-04")
        self.assertEqual(len(model.suggestions), 2)

    def test_fix_suggestion_rejects_one_step(self):
        with self.assertRaises(ValidationError):
            FixSuggestionOutput.model_validate(
                {
                    "task_type": "fix_suggestion",
                    "check_id": "LE-04",
                    "headline": "x",
                    "whats_wrong": "y",
                    "why_it_matters": "z",
                    "suggestions": [
                        {"step": 1, "title": "Only One", "detail": "Not enough steps."}
                    ],
                    "confidence": "low",
                }
            )

    def test_prompts_load(self):
        system = system_prompt_v1()
        fix = fix_suggestion_prompt_v1()
        self.assertIn("JSON object only", system)
        self.assertIn("Do not invent", system)
        self.assertIn("REQUIRED THIS TURN", fix)
        self.assertIn("fix_suggestion", fix)
        self.assertEqual(load_prompt(PROMPT_SYSTEM_V1).strip(), system.strip())
        self.assertEqual(load_prompt(PROMPT_FIX_SUGGESTION_V1).strip(), fix.strip())
