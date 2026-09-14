"""공통 receipt 연결 전에도 누락과 측정된 0을 구분해야 한다."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.learn.answering import _usage_of, compose_grounded_answer
from app.team.metrics import aggregate, percentile
from app.team.runner import estimate_cost
from tests import test_evaluations as baseline


class UsageTest(unittest.IsolatedAsyncioTestCase):
    def test_partial_tokens_are_unknown(self):
        response = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=0))
        self.assertEqual(_usage_of(response), {"prompt_tokens": 0, "completion_tokens": None})
        self.assertIsNone(estimate_cost(0, None, {"input": 1, "output": 1}))
        self.assertIsNone(estimate_cost(0, 0, {"input": 1}))
        self.assertEqual(estimate_cost(0, 0, {"input": 1, "output": 1}), 0)
        self.assertEqual(estimate_cost(5, 5, {"input": 0, "output": 0}), 0)
        for rate in (float("nan"), float("inf"), -1):
            self.assertIsNone(estimate_cost(1, 1, {"input": rate, "output": 1}))

    async def test_parsing_failure_preserves_response_usage(self):
        response = SimpleNamespace(text="{broken", usage_metadata=SimpleNamespace(
            prompt_token_count=12, candidates_token_count=3))
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content=AsyncMock(return_value=response))))
        with patch("app.learn.answering.get_settings", return_value=SimpleNamespace(
            answer_mode="grounded_llm", gemini_api_key="fake", gemini_model="fake")), \
            patch("google.genai.Client", return_value=client):
            result = await compose_grounded_answer("합성 질문", [dict(id=1, content="승인 원문")])
        self.assertEqual(result.fallback_reason, "generation_failed")
        self.assertEqual(result.usage, {"prompt_tokens": 12, "completion_tokens": 3})
        self.assertEqual(result.model_call_status, "OBSERVED")

    def test_nearest_rank_exact_integer_is_not_rounded_up(self):
        self.assertEqual(percentile(list(range(1, 101)), .95), 95)
        self.assertEqual(percentile([1, 2], .5), 1)

    def test_partial_cost_is_not_total(self):
        rows = baseline.AggregateTest()._rows()
        result = aggregate(rows)
        self.assertIsNone(result["cost_usd_total"])
        self.assertEqual(result["cost_usd_known_total"], .001)
        self.assertEqual(result["cost_missing_count"], 2)
        for row in rows:
            row["cost_usd"] = 0
        result = aggregate(rows)
        self.assertEqual(result["cost_usd_total"], 0)
        self.assertEqual(result["cost_observation_status"], "COMPLETE")
