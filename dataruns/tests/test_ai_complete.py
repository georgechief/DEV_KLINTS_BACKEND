"""check_id mismatch triggers JSON retry."""

from __future__ import annotations

from django.test import SimpleTestCase

from dataruns.ai.complete import complete_json
from dataruns.ai.constants import DEFAULT_MODEL_ID, TASK_FIX_SUGGESTION
from dataruns.ai.exceptions import AiJsonRetryExhaustedError
from dataruns.ai.providers.base import AiProvider, ProviderResult


class WrongCheckIdProvider(AiProvider):
    name = "wrong_check"

    def __init__(self) -> None:
        self.attempts = 0

    def complete_json(self, **kwargs) -> ProviderResult:
        self.attempts += 1
        return ProviderResult(
            text=(
                '{"task_type":"fix_suggestion","check_id":"ZZ-99","headline":"x",'
                '"whats_wrong":"y","why_it_matters":"z","suggestions":'
                '[{"step":1,"title":"A","detail":"a"},'
                '{"step":2,"title":"B","detail":"b"}],'
                '"cautions":[],"confidence":"low"}'
            ),
            model=kwargs["model"],
            provider=self.name,
        )


class CheckIdMismatchRetryTests(SimpleTestCase):
    def test_mismatch_exhausts_retries(self):
        provider = WrongCheckIdProvider()
        with self.assertRaises(AiJsonRetryExhaustedError):
            complete_json(
                provider=provider,
                task_type=TASK_FIX_SUGGESTION,
                system_prompt="system",
                user_prompt="user",
                context={"check_id": "LE-04"},
                model=DEFAULT_MODEL_ID,
                max_retries=3,
            )
        self.assertEqual(provider.attempts, 3)
