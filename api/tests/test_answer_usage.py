"""CP-00B R 답변 호출 adapter: 실제 공급자/DB 없이 실패 순서까지 검증한다."""
import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from app.contracts.usage import UsageContext
from app.learn.answering import compose_grounded_answer
from app.learn.answer_usage import AnswerUsageStartError
from app.usage.recorder import DbUsageSink, NullSink


CONTEXT = UsageContext(store_id="7", cost_phase="OPERATING", cost_purpose="EVALUATION",
                       stage="ANSWER", logical_call_id="answer-case-1", evaluation_run_id="9")
CARDS = [dict(id=1, content="우유는 냉장고에 보관한다.")]


def response(**usage):
    return NS(text='{"answer":"우유는 냉장고에 보관한다.","card_ids":[1]}',
              usage_metadata=NS(**usage), model_version="synthetic-model",
              response_id="synthetic-response")


class Sink:
    def __init__(self):
        self.started = []
        self.finished = []
    async def start(self, attempt):
        self.started.append(attempt)
        return 1
    async def finalize(self, attempt_id, attempt, known, cost, price):
        self.finished.append(attempt)


class AnswerUsageTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, result=None, *, sink=None, context=CONTEXT, error=None, mode="grounded_llm"):
        generate = AsyncMock(return_value=result, side_effect=error)
        client = NS(aio=NS(models=NS(generate_content=generate)))
        with patch("app.learn.answering.get_settings", return_value=NS(
                answer_mode=mode, gemini_api_key="fake", gemini_model="synthetic-model")), \
             patch("google.genai.Client", return_value=client) as factory:
            value = await compose_grounded_answer("우유 보관", CARDS,
                usage_context=context, usage_sink=sink)
        if mode != "extractive":
            self.assertEqual(factory.call_args.kwargs["http_options"].retry_options.attempts, 1)
        return value, generate

    async def test_normal_attribution_and_raw_metadata(self):
        sink = Sink()
        value, generate = await self.call(response(prompt_token_count=12, candidates_token_count=3,
                                                  total_token_count=15), sink=sink)
        self.assertEqual(value.source, "GROUNDED_LLM")
        generate.assert_awaited_once()
        self.assertEqual(len(sink.started), 1)
        final = sink.finished[0]
        self.assertEqual(final.context, CONTEXT)
        self.assertEqual(final.status, "SUCCEEDED")
        self.assertEqual(final.usage_status, "COMPLETE")
        self.assertEqual(final.usage.raw["total_token_count"], 15)
        self.assertEqual(final.provider_request_id, "synthetic-response")
        self.assertGreater(final.scale.input_bytes, 0)
        self.assertNotIn("우유", final.model_dump_json())

    async def test_zero_missing_and_additional_units_are_distinct(self):
        for meta, status in ((dict(prompt_token_count=0, candidates_token_count=0), "COMPLETE"),
                             (dict(prompt_token_count=0), "PARTIAL"), ({}, "UNKNOWN"),
                             (dict(prompt_token_count=12, candidates_token_count=3,
                                   cached_content_token_count=5, thoughts_token_count=2), "PARTIAL")):
            with self.subTest(meta=meta):
                sink = Sink()
                await self.call(response(**meta), sink=sink)
                self.assertEqual(sink.finished[0].usage_status, status)
                self.assertEqual(sink.finished[0].usage.raw, meta)

    async def test_parse_failure_preserves_usage_and_records_failure(self):
        sink = Sink()
        res = response(prompt_token_count=12, candidates_token_count=3)
        res.text = "{broken"
        value, generate = await self.call(res, sink=sink)
        self.assertEqual(value.fallback_reason, "generation_failed")
        self.assertEqual(sink.finished[0].status, "FAILED")
        self.assertEqual(sink.finished[0].usage.prompt_tokens, 12)
        generate.assert_awaited_once()

    async def test_timeout_and_cancellation_are_not_success(self):
        sink = Sink()
        value, generate = await self.call(sink=sink, error=TimeoutError())
        self.assertEqual(value.model_call_status, "UNKNOWN")
        self.assertEqual(sink.finished[0].status, "FAILED")
        self.assertEqual(sink.finished[0].usage_status, "UNKNOWN")
        generate.assert_awaited_once()
        sink = Sink()
        with self.assertRaises(asyncio.CancelledError):
            await self.call(sink=sink, error=asyncio.CancelledError())
        self.assertEqual(sink.finished[0].status, "FAILED")

    async def test_start_failure_prevents_provider_and_is_not_fallback(self):
        sink = Sink()
        sink.start = AsyncMock(side_effect=RuntimeError("db unavailable"))
        with patch("google.genai.Client") as factory:
            with patch("app.learn.answering.get_settings", return_value=NS(
                    answer_mode="grounded_llm", gemini_api_key="fake", gemini_model="synthetic-model")):
                with self.assertRaises(AnswerUsageStartError):
                    await compose_grounded_answer("우유 보관", CARDS, usage_context=CONTEXT, usage_sink=sink)
            factory.return_value.aio.models.generate_content.assert_not_called()
        self.assertEqual(sink.finished, [])

    async def test_finalize_failure_never_repeats_provider(self):
        sink = Sink()
        sink.finalize = AsyncMock(side_effect=RuntimeError("db unavailable"))
        value, generate = await self.call(response(prompt_token_count=12, candidates_token_count=3), sink=sink)
        self.assertEqual(value.source, "GROUNDED_LLM")
        generate.assert_awaited_once()
        self.assertEqual(len(sink.started), 1)

    async def test_no_call_does_not_create_receipt(self):
        sink = Sink()
        value, generate = await self.call(sink=sink, mode="extractive")
        self.assertEqual(value.model_call_status, "NOT_CALLED")
        self.assertEqual(sink.started, [])
        generate.assert_not_called()

    async def test_incomplete_or_wrong_context_is_rejected(self):
        for context, sink in ((None, Sink()), (CONTEXT, None), (CONTEXT, NullSink()),
                              (CONTEXT.model_copy(update={"stage": "EMBED"}), Sink())):
            with self.subTest(context=context), self.assertRaises(ValueError):
                await self.call(context=context, sink=sink)

    async def test_db_sink_releases_connection_before_provider(self):
        class Pool:
            active = False
            @asynccontextmanager
            async def acquire(self):
                self.active = True
                try:
                    yield conn
                finally:
                    self.active = False
        pool = Pool()
        conn = NS(fetchval=AsyncMock(return_value=1), execute=AsyncMock())
        async def provider(**kwargs):
            self.assertFalse(pool.active)
            conn.fetchval.assert_awaited_once()
            return response(prompt_token_count=12, candidates_token_count=3)
        await self.call(sink=DbUsageSink(pool), error=provider)
        conn.execute.assert_awaited_once()
        self.assertEqual(conn.fetchval.call_args.args[1], 7)
        self.assertFalse(pool.active)
