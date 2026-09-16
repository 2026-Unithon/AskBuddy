"""W 분류/관계 계측: 공급자와 DB는 fake, 실제 recorder와 호출부를 검증한다."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from app.categories.classifier import classify_cards
from app.contracts.usage import UsageContext
from app.learn.knowledge_loop import build_knowledge_plan


class Sink:
    def __init__(self):
        self.started, self.finished = [], []

    async def start(self, value):
        self.started.append(value)
        return len(self.started)

    async def finalize(self, aid, value, known, cost, price):
        self.finished.append(value)


def context(stage="CLASSIFY", **kw):
    return UsageContext(store_id="7", cost_phase="OPERATING", cost_purpose="EVALUATION",
                        stage=stage, logical_call_id="w-call", operation_id="w-operation", **kw)


SETTINGS = NS(ingest_mode="real", gemini_api_key="fake", gemini_model="synthetic",
              answer_mode="grounded_llm", retrieval_threshold=.35)
CARDS = [dict(card_id=11, title="업무 A", content="원문 업무 내용", category_name="기타"),
         dict(card_id=12, title="업무 B", content="다른 원문", category_name="기타")]
CATEGORIES = [dict(category_id=9, category_name="기타", is_system=True)]


def response(text='{"items":[{"card_id":11,"category_name":"기타"}]}', **meta):
    return NS(text=text, usage_metadata=NS(**meta), model_version="reported-model", response_id="request-1")


class WUsageTest(unittest.IsolatedAsyncioTestCase):
    async def classify(self, res=None, *, sink=None, ctx=None, error=None, cards=CARDS):
        generate = AsyncMock(return_value=res, side_effect=error)
        client = NS(aio=NS(models=NS(generate_content=generate), aclose=AsyncMock()), close=lambda: None)
        with patch("app.categories.classifier.get_settings", return_value=SETTINGS), \
             patch("google.genai.Client", return_value=client) as factory:
            value = await classify_cards(cards, ["기타"], usage_context=ctx or context(), usage_sink=sink)
        if cards:
            self.assertEqual(factory.call_args.kwargs["http_options"].retry_options.attempts, 1)
        return value, generate, client

    async def test_batch_one_receipt_and_no_sensitive_body(self):
        sink = Sink()
        value, generate, client = await self.classify(response(prompt_token_count=12, candidates_token_count=3), sink=sink)
        self.assertEqual(value, {11: "기타", 12: "기타"})
        generate.assert_awaited_once()
        self.assertEqual(len(sink.started), 1)
        final = sink.finished[0]
        self.assertEqual(final.context, context())
        self.assertEqual(final.status, "SUCCEEDED")
        self.assertEqual(final.usage_status, "COMPLETE")
        self.assertEqual(final.reported_model, "reported-model")
        self.assertEqual(final.provider_request_id, "request-1")
        self.assertTrue(final.prompt_hash.startswith("sha256:"))
        self.assertTrue(final.config_hash.startswith("sha256:"))
        self.assertGreater(final.scale.input_bytes, 0)
        self.assertNotIn("원문", final.model_dump_json())
        client.aio.aclose.assert_awaited_once()

    async def test_zero_partial_unknown_and_extra_units(self):
        for meta, status in ((dict(prompt_token_count=0, candidates_token_count=0), "COMPLETE"),
                             (dict(prompt_token_count=0), "PARTIAL"), ({}, "UNKNOWN"),
                             (dict(prompt_token_count=12, candidates_token_count=3, thoughts_token_count=4), "PARTIAL")):
            with self.subTest(meta=meta):
                sink = Sink()
                await self.classify(response(**meta), sink=sink)
                self.assertEqual(sink.finished[0].usage_status, status)
                self.assertEqual(sink.finished[0].usage.raw, meta)

    async def test_parse_failure_keeps_usage(self):
        sink = Sink()
        with self.assertRaises(ValueError):
            await self.classify(response("{broken", prompt_token_count=12, candidates_token_count=3), sink=sink)
        self.assertEqual(sink.finished[0].status, "FAILED")
        self.assertEqual(sink.finished[0].usage.prompt_tokens, 12)

    async def test_start_failure_no_provider(self):
        sink = Sink()
        sink.start = AsyncMock(side_effect=RuntimeError("db unavailable"))
        with patch("app.categories.classifier.get_settings", return_value=SETTINGS), patch("google.genai.Client") as factory:
            with self.assertRaises(RuntimeError):
                await classify_cards(CARDS, ["기타"], usage_context=context(), usage_sink=sink)
            factory.assert_not_called()
        self.assertFalse(sink.finished)

    async def test_timeout_and_cancel_record_failed_unknown(self):
        for error in (TimeoutError(), asyncio.CancelledError()):
            sink = Sink()
            with self.assertRaises(type(error)):
                await self.classify(sink=sink, error=error)
            self.assertEqual(sink.finished[0].status, "FAILED")
            self.assertEqual(sink.finished[0].usage_status, "UNKNOWN")

    async def test_finalize_failure_no_provider_retry(self):
        sink = Sink()
        sink.finalize = AsyncMock(side_effect=RuntimeError("db unavailable"))
        _, generate, _ = await self.classify(response(prompt_token_count=12, candidates_token_count=3), sink=sink)
        generate.assert_awaited_once()
        self.assertEqual(len(sink.started), 1)

    async def test_paid_without_context_or_wrong_stage_rejected(self):
        with patch("app.categories.classifier.get_settings", return_value=SETTINGS), patch("google.genai.Client") as factory:
            with self.assertRaises(ValueError):
                await classify_cards(CARDS, ["기타"])
            with self.assertRaises(ValueError):
                await classify_cards(CARDS, ["기타"], usage_context=context("RELATION"), usage_sink=Sink())
            factory.assert_not_called()

    async def test_empty_and_mock_no_receipt(self):
        sink = Sink()
        value, generate, _ = await self.classify(sink=sink, cards=[])
        self.assertEqual(value, {})
        generate.assert_not_awaited()
        with patch("app.categories.classifier.get_settings", return_value=NS(ingest_mode="mock")):
            await classify_cards(CARDS, ["기타"], usage_context=context(), usage_sink=sink)
        self.assertFalse(sink.started)

    async def relation(self, res=None, *, error=None, sink=None, ctx=None, candidates=None):
        db = NS(fetch=AsyncMock(return_value=CATEGORIES))
        generate = AsyncMock(return_value=res, side_effect=error)
        client = NS(aio=NS(models=NS(generate_content=generate), aclose=AsyncMock()), close=lambda: None)
        with patch("app.learn.knowledge_loop.get_settings", return_value=SETTINGS), \
             patch("app.learn.knowledge_loop.find_owner_answer_candidates", AsyncMock(return_value=candidates or [])), \
             patch("google.genai.Client", return_value=client):
            result = await build_knowledge_plan(db, 7, "업무 질문", "점주 원문 답변",
                usage_context=ctx or context("RELATION", question_id="13"), usage_sink=sink)
        return result, generate

    async def test_relation_success_and_parse_failure_review(self):
        for text, published in (('{"relation_type":"NEW","category_name":"기타","reason":"신규"}', True), ("{broken", False)):
            sink = Sink()
            result, generate = await self.relation(response(text, prompt_token_count=10, candidates_token_count=2), sink=sink)
            self.assertEqual(result.auto_publish, published)
            self.assertEqual(sink.finished[0].context.question_id, "13")
            self.assertEqual(sink.finished[0].context.stage, "RELATION")
            self.assertEqual(sink.finished[0].status, "SUCCEEDED" if published else "FAILED")
            self.assertEqual(sink.finished[0].usage.prompt_tokens, 10)
            generate.assert_awaited_once()

    async def test_relation_start_failure_not_review_success(self):
        sink = Sink()
        sink.start = AsyncMock(side_effect=RuntimeError("db unavailable"))
        with self.assertRaises(RuntimeError):
            await self.relation(response(), sink=sink)

    async def test_relation_cross_store_rejected_before_queries(self):
        sink = Sink()
        with self.assertRaises(ValueError):
            await self.relation(sink=sink, ctx=context("RELATION").model_copy(update={"store_id": "8"}))
        self.assertFalse(sink.started)

    async def test_relation_timeout_review_and_identical_skips_model(self):
        sink = Sink()
        result, generate = await self.relation(sink=sink, error=TimeoutError())
        self.assertFalse(result.auto_publish)
        self.assertEqual(sink.finished[0].usage_status, "UNKNOWN")
        generate.assert_awaited_once()
        sink = Sink()
        result, generate = await self.relation(sink=sink, candidates=[dict(id=11, version_id=12,
            content="점주 원문 답변", title="업무", category_id=9, category_name="기타")])
        self.assertEqual(result.relation_type, "IDENTICAL")
        generate.assert_not_awaited()
        self.assertFalse(sink.started)

    async def test_candidate_embedding_inherits_operation_and_purpose(self):
        from app.learn.knowledge_loop import find_owner_answer_candidates
        db = NS(fetch=AsyncMock(return_value=[]))
        ctx = context("RELATION", question_id="13")
        with patch("app.learn.knowledge_loop.recorded_embeddings", AsyncMock(return_value=[[.1]])) as embed:
            await find_owner_answer_candidates(db, 7, "원문 질문", "원문 답변",
                                              usage_context=ctx, usage_sink=Sink())
        child = embed.call_args.kwargs["context"]
        self.assertEqual(child.stage, "EMBED")
        self.assertEqual(child.operation_id, ctx.operation_id)
        self.assertEqual(child.cost_purpose, "EVALUATION")
        self.assertEqual(child.question_id, "13")
        self.assertNotEqual(child.logical_call_id, ctx.logical_call_id)

    async def test_worker_does_not_hold_connection_during_classification(self):
        from app.categories.worker import process_reclassification_job
        pool = NS(fetchrow=AsyncMock(return_value=dict(target_category_version=2)),
                  fetchval=AsyncMock(return_value=2), execute=AsyncMock(),
                  fetch=AsyncMock(side_effect=[[dict(category_id=9, category_name="기타")],
                      [dict(CARDS[0], assignment_type="AUTOMATIC", card_updated_at_snapshot="snapshot")]]))
        async def classify(cards, names, **kw):
            self.assertEqual(kw["usage_context"].store_id, "7")
            self.assertEqual(kw["usage_context"].stage, "CLASSIFY")
            self.assertEqual(kw["usage_context"].operation_id, "reclass:23")
            # reclassification_jobs의 ID를 ingest_jobs용 job_id에 넣지 않는다.
            self.assertIsNone(kw["usage_context"].job_id)
            self.assertFalse(hasattr(pool, "acquire"))
            return {11: "기타"}
        with patch("app.categories.worker.get_pool", return_value=pool), \
             patch("app.categories.worker.classify_cards", side_effect=classify) as model:
            await process_reclassification_job(7, 23)
        model.assert_awaited_once()

    async def test_provider_sees_started_before_call_and_cleanup_keeps_response(self):
        sink = Sink()
        async def provider(**kw):
            self.assertEqual(sink.started[0].status, "STARTED")
            return response(prompt_token_count=2, candidates_token_count=1)
        client = NS(aio=NS(models=NS(generate_content=AsyncMock(side_effect=provider)),
                           aclose=AsyncMock(side_effect=RuntimeError("cleanup"))))
        with patch("app.categories.classifier.get_settings", return_value=SETTINGS), \
             patch("google.genai.Client", return_value=client):
            result = await classify_cards(CARDS, ["기타"], usage_context=context(), usage_sink=sink)
        self.assertEqual(result[11], "기타")
        self.assertEqual(sink.finished[0].status, "SUCCEEDED")

    async def test_new_attempt_receipts_do_not_merge(self):
        sink = Sink()
        for attempt in (1, 2):
            await self.classify(response(), sink=sink, ctx=context().model_copy(update={"attempt_no": attempt}))
        self.assertEqual([v.context.attempt_no for v in sink.started], [1, 2])
