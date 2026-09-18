"""실제 라우터/검색 함수를 통과하는 연결 수명과 usage 귀속 회귀."""
import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.deps import create_token
from app.errors import install_error_handlers
from app.learn.router import router, legacy_chat_regression
from app.learn.answering import AnswerComposition
from app.learn.answer_usage import AnswerUsageStartError
from app.reg.retrieve import retrieve_question
from app.team.runner import _execute
from app.team.router import create_evaluation
from app.team.schemas import RunCreateRequest
from app.usage.repository import finalize_attempt
from tests.test_answer_usage import CONTEXT
from app.contracts.usage import UsageAttempt


class Pool:
    def __init__(self):
        self.active = 0
        self.role = "STAFF"
        self.stores = []
        self.writes = []
    @asynccontextmanager
    async def acquire(self):
        self.active += 1
        try:
            yield self
        finally:
            self.active -= 1
    @asynccontextmanager
    async def transaction(self):
        assert self.active == 1
        yield
    async def fetchrow(self, sql, store_id, user_id):
        assert self.active == 1
        self.stores.append(store_id)
        return dict(member_role=self.role, member_id=3) if self.role else None
    async def fetchval(self, sql, *args):
        self.writes.append(sql)
        return 12
    async def execute(self, sql, *args):
        self.writes.append(sql)
        return "UPDATE 1"
    async def fetch(self, sql, store_id, *args):
        assert self.active == 1
        self.stores.append(store_id)
        return []


class LegacyChatRegressionTest(unittest.TestCase):
    def setUp(self):
        self.pool = Pool()
        app = FastAPI()
        app.include_router(router, prefix="/learn")
        # Explicitly isolated legacy baseline, absent from the product router.
        app.post("/evaluation/legacy-chat")(legacy_chat_regression)
        install_error_handlers(app)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.scope = patch("app.deps.get_settings", return_value=NS(
            jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256"))
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.contexts = []
        @asynccontextmanager
        async def lease(*args):
            yield "synthetic"
        async def retrieve(pool, store_id, question, **kwargs):
            self.assertEqual(pool.active, 0)
            self.assertEqual(kwargs["usage_context"].store_id, str(store_id))
            return dict(kind="hit", candidates=[dict(id=1, content="승인 원문")])
        async def compose(question, candidates, **kwargs):
            self.assertEqual(self.pool.active, 0)
            self.contexts.append(kwargs["usage_context"])
            return AnswerComposition("승인 원문", [], "CARD_ORIGINAL", "FALLBACK")
        for target, value in (("get_pool", lambda: self.pool), ("request_lease", lease), ("retrieve_question", retrieve),
                              ("compose_grounded_answer", compose),
                              ("_lock_chat_publication", AsyncMock()),
                              ("_citations_are_current", AsyncMock(return_value=True)),
                              ("_open_session", AsyncMock(return_value=4))):
            item = patch("app.learn.router." + target, value)
            item.start()
            self.addCleanup(item.stop)
    def headers(self, store=1):
        return {"Authorization": "Bearer " + create_token(dict(
            store_id=store, user_id=10, role="STAFF",
            exp=datetime.now(timezone.utc)+timedelta(minutes=5)))}
    def post(self, store=1):
        return self.client.post("/evaluation/legacy-chat", json=dict(question="합성 질문"), headers=self.headers(store))

    def test_product_chat_requires_v2_without_generation_or_writes(self):
        with patch("app.learn.router._ask_chat", AsyncMock()) as generate:
            result = self.client.post("/learn/chat", json=dict(question="합성 질문"), headers=self.headers())
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "V2_REQUIRED")
        generate.assert_not_awaited()
        self.assertFalse(self.pool.writes)
        self.pool.role = None
        self.assertEqual(self.client.post("/learn/chat", json=dict(question="질문"), headers=self.headers()).status_code, 403)

    def test_legacy_pending_cannot_bypass_v2_decision(self):
        body = dict(question_text="조건이 빠진 합성 질문", miss_reason="no_match")
        self.assertEqual(self.client.post("/learn/pending", json=body).status_code, 401)
        result = self.client.post("/learn/pending", json=body, headers=self.headers())
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "V2_REQUIRED")
        self.assertFalse(self.pool.writes)
    def test_product_scope_and_no_request_connection_held(self):
        self.assertEqual(self.post(2).status_code, 200)
        self.assertEqual(self.pool.active, 0)
        self.assertEqual(set(self.pool.stores), {2})
        context = self.contexts[0]
        self.assertEqual((context.store_id, context.cost_purpose, context.cost_phase),
                         ("2", "PRODUCT", "OPERATING"))
        self.assertTrue(context.operation_id)
    def test_auth_and_revoked_membership(self):
        self.assertEqual(self.client.post("/learn/chat", json=dict(question="질문")).status_code, 401)
        self.pool.role = None
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(self.pool.writes)
    def test_membership_is_rechecked_after_provider(self):
        async def revoke(*args, **kwargs):
            self.pool.role = None
            return AnswerComposition("원문", [], "CARD_ORIGINAL", "FALLBACK")
        with patch("app.learn.router.compose_grounded_answer", revoke):
            self.assertEqual(self.post().status_code, 403)
        self.assertFalse(self.pool.writes)
    def test_start_failure_is_retryable_error_without_pending(self):
        with patch("app.learn.router.compose_grounded_answer", AsyncMock(side_effect=AnswerUsageStartError())):
            result = self.post()
        self.assertEqual(result.status_code, 503)
        self.assertTrue(result.json()["error"]["retryable"])
        self.assertFalse(self.pool.writes)
    def test_search_timeout_does_not_become_pending(self):
        with patch("app.learn.router.retrieve_question", AsyncMock(side_effect=TimeoutError())):
            result = self.post()
        self.assertEqual(result.status_code, 504)
        self.assertEqual(result.json()["error"]["code"], "DEADLINE_EXCEEDED")
        self.assertFalse(self.pool.writes)
    def test_rate_limit_does_not_call_provider(self):
        from app.errors import ApiError
        @asynccontextmanager
        async def blocked(*args):
            raise ApiError(429,"RATE_LIMITED","잠시 후 다시 시도",retryable=True)
            yield
        with patch("app.learn.router.request_lease", blocked), \
             patch("app.learn.router.retrieve_question", AsyncMock()) as retrieve:
            self.assertEqual(self.post().status_code, 429)
            retrieve.assert_not_awaited()

    def test_stale_requeries_once_and_records_distinct_calls(self):
        with patch("app.learn.router._citations_are_current", AsyncMock(side_effect=[False, True])) as current:
            result = self.post()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(current.await_count, 2)
        self.assertEqual(len(self.contexts), 2)
        self.assertEqual(self.contexts[0].operation_id, self.contexts[1].operation_id)
        self.assertNotEqual(self.contexts[0].logical_call_id, self.contexts[1].logical_call_id)
        self.assertEqual(sum("'USER'" in sql for sql in self.pool.writes), 1)

    def test_persistent_stale_never_creates_messages_or_pending(self):
        with patch("app.learn.router._citations_are_current", AsyncMock(return_value=False)) as current:
            result = self.post()
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "STALE_KNOWLEDGE")
        self.assertEqual(current.await_count, 2)
        self.assertFalse(self.pool.writes)

    def test_stale_then_miss_is_error_not_pending(self):
        retrieve = AsyncMock(side_effect=[dict(kind="hit", candidates=[]), dict(kind="miss", reason="removed")])
        with patch("app.learn.router.retrieve_question", retrieve), \
             patch("app.learn.router._citations_are_current", AsyncMock(return_value=False)):
            result = self.post()
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "STALE_KNOWLEDGE")
        self.assertFalse(self.pool.writes)

    def test_requery_timeout_is_stale_error(self):
        retrieve = AsyncMock(side_effect=[dict(kind="hit", candidates=[]), TimeoutError()])
        with patch("app.learn.router.retrieve_question", retrieve), \
             patch("app.learn.router._citations_are_current", AsyncMock(return_value=False)):
            result = self.post()
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "STALE_KNOWLEDGE")
        self.assertFalse(self.pool.writes)

    def test_deadline_during_cleanup_preserves_completed_response(self):
        @asynccontextmanager
        async def slow_cleanup(*args):
            yield "synthetic"
            await asyncio.sleep(1)
        with patch("app.learn.router.get_settings", return_value=NS(chat_deadline_seconds=.02)), \
             patch("app.learn.router.request_lease", slow_cleanup), \
             patch("app.learn.router._ask_chat", AsyncMock(return_value={"saved": True})):
            result = self.post()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"saved": True})

    def test_outer_deadline_after_stale_remains_stale_error(self):
        async def expired(*args, attempt_state, **kwargs):
            attempt_state["stale"] = True
            await asyncio.sleep(1)
        with patch("app.learn.router.get_settings", return_value=NS(chat_deadline_seconds=.02)), \
             patch("app.learn.router._ask_chat", expired):
            result = self.post()
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "STALE_KNOWLEDGE")
        self.assertFalse(self.pool.writes)


class PoolSearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_evaluation_route_releases_setup_connection_and_binds_run(self):
        pool = Pool()
        contexts = []
        async def run_case(db, store_id, case, **kwargs):
            self.assertIs(db, pool)
            self.assertEqual(pool.active, 0)
            contexts.append(kwargs["usage_context"])
            return {}
        async def save(*args, **kwargs):
            self.assertEqual(pool.active, 1)
            return {}
        snapshot = dict(answer_model="fake", embedding_model="fake", answer_mode="extractive",
                        retrieval_threshold=.35, retrieval_strong_score=.62)
        from contextlib import ExitStack
        with ExitStack() as stack:
            patches = {
                "get_pool": lambda: pool, "settings_snapshot": lambda _: snapshot,
                "code_version": lambda: "test", "prompt_version": lambda: "test",
                "repo.list_cases": AsyncMock(return_value=[dict(case_id=5, case_key="synthetic")]),
                "repo.create_run": AsyncMock(return_value=dict(run_id=9, code_version="test", prompt_version="test")),
                "run_case": run_case, "aggregate": lambda _: {},
                "repo.insert_results": save, "repo.finish_run": save,
                "repo.list_results": AsyncMock(return_value=[]),
                "_run": lambda row: row, "RunDetail": lambda **kwargs: kwargs,
            }
            for key, value in patches.items():
                stack.enter_context(patch("app.team.router."+key, value))
            await create_evaluation(RunCreateRequest(label="synthetic"), dict(store_id=7, user_id=10))
        self.assertEqual(pool.active, 0)
        self.assertEqual(contexts[0].evaluation_run_id, "9")
        self.assertEqual(contexts[0].cost_purpose, "EVALUATION")
        self.assertEqual(contexts[0].logical_call_id, "eval:9:case:5:answer")

    async def test_embedding_finishes_before_connection_acquisition(self):
        pool = Pool()
        def embed(question):
            self.assertEqual(pool.active, 0)
            return [0.0]
        with patch("app.reg.retrieve.embed_text", embed), \
             patch("app.reg.retrieve.get_settings", return_value=NS(retrieval_threshold=.35)):
            result = await retrieve_question(pool, 7, "우유 보관")
        self.assertEqual(result["kind"], "miss")
        self.assertEqual(pool.stores, [7])
        self.assertEqual(pool.active, 0)
    async def test_evaluation_context_reaches_answer(self):
        pool = Pool()
        async def compose(*args, **kwargs):
            self.assertEqual(pool.active, 0)
            self.assertEqual(kwargs["usage_context"], CONTEXT)
            return AnswerComposition("원문", [], "CARD_ORIGINAL", "FALLBACK", model_call_status="NOT_CALLED")
        with patch("app.team.runner.retrieve_question", AsyncMock(return_value=dict(kind="hit", candidates=[]))), \
             patch("app.team.runner.compose_grounded_answer", compose):
            result = await _execute(pool, 7, "합성 질문", top_k=5, cost_per_1k=None,
                                    usage_context=CONTEXT, usage_sink=NS())
        self.assertEqual(result.actual_kind, "HIT")
    async def test_finalize_retry_is_scoped_and_bounded(self):
        pool = Pool()
        pool.execute = AsyncMock(side_effect=[TimeoutError(), "UPDATE 1"])
        attempt = UsageAttempt(context=CONTEXT, requested_model="synthetic")
        await finalize_attempt(pool, 11, attempt, known_cost=None, cost=None, price_status="NO_RATE")
        self.assertEqual(pool.execute.await_count, 2)
        sql, *args = pool.execute.call_args.args
        self.assertIn("store_id=$25", sql)
        self.assertIn("status='STARTED'", sql)
        self.assertEqual(args[-3:], [7, CONTEXT.logical_call_id, 1])
        self.assertEqual(pool.active, 0)
