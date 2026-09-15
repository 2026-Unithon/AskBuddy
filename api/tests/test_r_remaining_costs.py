import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from decimal import Decimal
from app.reg.embeddings import recorded_embeddings
from app.team.usage_metrics import summarize_read_usage
from app.team.operating_cost import operating_scenarios
from tests.test_answer_usage import Sink, CONTEXT


class EmbeddingTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, *, data=None, usage=None, error=None, stage="QUERY", close_error=None):
        sink = Sink()
        def create(**kwargs):
            self.assertEqual(len(sink.started), 1)
            self.assertEqual(sink.finished, [])
            if error:
                raise error
            return NS(data=data if data is not None else [NS(index=1, embedding=[2.0]), NS(index=0, embedding=[1.0])],
                      usage=usage, model="synthetic", _request_id="request")
        client = NS(embeddings=NS(create=Mock(side_effect=create)), close=Mock(side_effect=close_error))
        with patch("app.reg.embeddings.get_settings", return_value=NS(
                openai_api_key="fake", embedding_model="synthetic", embedding_dim=1,
                embedding_timeout_seconds=30, query_embedding_timeout_seconds=.8)), \
             patch("app.reg.embeddings.OpenAI", return_value=client) as factory:
            try:
                result = await recorded_embeddings(["합성 하나", "합성 둘"],
                    context=CONTEXT.model_copy(update=dict(stage=stage)), sink=sink)
            except Exception:
                self.assertEqual(sink.finished[0].status, "FAILED")
                raise
            self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
            self.assertEqual(factory.call_args.kwargs["timeout"], .8 if stage=="QUERY" else 30)
            client.close.assert_called_once()
        return result, sink
    async def test_batch_order_one_receipt_and_nullable_usage(self):
        result, sink = await self.call(usage=NS(prompt_tokens=0,total_tokens=0))
        self.assertEqual(result, [[1.0],[2.0]])
        self.assertEqual(len(sink.finished), 1)
        self.assertEqual(sink.finished[0].usage.prompt_tokens, 0)
        self.assertEqual(sink.finished[0].usage_status, "COMPLETE")
        _, missing = await self.call()
        self.assertEqual(missing.finished[0].usage_status, "UNKNOWN")
    async def test_invalid_response_and_timeout_fail(self):
        for kwargs in (dict(data=[NS(index=0,embedding=[1]),NS(index=0,embedding=[1])]),
                       dict(data=[NS(index=0,embedding=[1,2]),NS(index=1,embedding=[1])]),
                       dict(error=TimeoutError())):
            with self.subTest(kwargs=kwargs), self.assertRaises((RuntimeError,TimeoutError)):
                await self.call(usage=NS(prompt_tokens=12), **kwargs)
    async def test_W_embedding_keeps_separate_time_budget(self):
        result,sink=await self.call(stage="EMBED",usage=NS(prompt_tokens=12,total_tokens=12))
        self.assertEqual(sink.finished[0].context.stage,"EMBED")
        self.assertEqual(len(result),2)

    async def test_cleanup_failure_preserves_response_and_usage(self):
        result, sink = await self.call(usage=NS(prompt_tokens=12, total_tokens=12),
                                      close_error=RuntimeError("cleanup failed"))
        self.assertEqual(result, [[1.0], [2.0]])
        self.assertEqual(sink.finished[0].usage.prompt_tokens, 12)
        self.assertEqual(sink.finished[0].status, "SUCCEEDED")

    async def test_cleanup_failure_does_not_mask_provider_error(self):
        with self.assertRaisesRegex(TimeoutError, "provider timeout"):
            await self.call(error=TimeoutError("provider timeout"),
                            close_error=RuntimeError("cleanup failed"))


class CostTest(unittest.TestCase):
    def test_receipts_are_deduplicated_and_missing_price_blocks_total(self):
        row = dict(usage_attempt_id=1, stage="QUERY", status="SUCCEEDED", usage_status="COMPLETE",
                   known_cost_usd=Decimal('.002'), cost_usd=Decimal('.002'))
        self.assertEqual(summarize_read_usage([row,row])["total_cost_usd"], '0.002')
        other = dict(row, usage_attempt_id=2, status="STARTED", usage_status="UNKNOWN", cost_usd=None, known_cost_usd=None)
        result = summarize_read_usage([row,other])
        self.assertIsNone(result["total_cost_usd"])
        self.assertEqual(result["unknown_attempt_count"], 1)
        self.assertIsNone(summarize_read_usage([])["total_cost_usd"])
    def test_scenario_first_month_stable_extra_turns_and_unknown(self):
        missing = operating_scenarios(read_cost_per_turn_usd='.001')
        self.assertEqual(len(missing["rows"]), 36)
        self.assertTrue(all(r['decision']=='UNDETERMINED' for r in missing['rows']))
        report = operating_scenarios(read_cost_per_turn_usd='.001',
            additional_ai_by_month={m:0 for m in (1,3,6,12)},
            storage_and_transfer_by_month={m:1 for m in (1,3,6,12)}, usd_krw=1000,
            rate_version="synthetic", fx_version="synthetic")
        first = report['rows'][0]
        self.assertEqual(first['base_questions'],450)
        self.assertEqual(Decimal(first['total_operating_krw']),Decimal(1450))
        self.assertEqual(report['rows'][3]['base_questions'],27)
        self.assertEqual(Decimal(report['rows'][2]['user_turns']),1350)
        for value in ('NaN', '-1', 'Infinity'):
            with self.assertRaises(ValueError):
                operating_scenarios(read_cost_per_turn_usd=value)
