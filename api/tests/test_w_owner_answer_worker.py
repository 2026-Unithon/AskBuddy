"""점주 답변 반영 worker 의 결정·트랜잭션 경계를 검증한다 (W, Task 5).

R 인계 함수·관계 분석·publish_cards·DB 보조 함수는 patch 한다. 여기서 보는 것은
**relation 별로 어떤 결과를 어느 트랜잭션에서 R 에 알리는가** 다. 실제 DB 는
Task 7 통합 스크립트가 돈다.
"""
from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.cards import owner_answer_worker as worker
from app.errors import ApiError
from app.learn.knowledge_loop import KnowledgePlan
from app.publish.approval import CardChange, PublishCardsResult

STORE = 7
MOD = "app.cards.owner_answer_worker"
CLAIM = dict(event_id="41", owner_answer_id="501", claim_token="tok", attempt=1, stale=False)


class FakeConn:
    def __init__(self, log: list):
        self.log = log
        self.in_tx = 0

    def is_in_transaction(self):
        return self.in_tx > 0

    @asynccontextmanager
    async def transaction(self):
        self.in_tx += 1
        self.log.append("tx_begin")
        try:
            yield
        except BaseException:
            self.log.append("tx_rollback")
            raise
        finally:
            self.in_tx -= 1
        self.log.append("tx_commit")

    async def execute(self, *args):
        self.log.append("execute")


class FakePool:
    def __init__(self, log: list):
        self.log = log

    @asynccontextmanager
    async def acquire(self):
        yield FakeConn(self.log)


def _plan(relation, *, target=None, auto_publish=False):
    return KnowledgePlan(
        relation_type=relation, target_card_id=target,
        target_version_id=(target * 10 if target else None),
        category_id=3, category_name="음료", proposed_title="질문", proposed_content="답",
        reason="이유", auto_publish=auto_publish)


def _context(proposal=None):
    return dict(source=dict(answer_id=501, question_text="질문", answer_text="답",
                            question_id=9),
                owner=dict(member_id=2, user_id=20), proposal=proposal)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log: list = []
        self.pool = FakePool(self.log)
        self.finished: list = []

        async def finish(conn, *, store_id, event_id, claim_token, result):
            assert store_id == STORE and event_id == 41 and claim_token == "tok"
            self.finished.append((result, conn.is_in_transaction(), list(self.log)))
            self.log.append(f"finish:{result.status}")

        self.patches = [
            patch(f"{MOD}.claim_owner_event", AsyncMock(return_value=dict(CLAIM))),
            patch(f"{MOD}.heartbeat_owner_event", AsyncMock(return_value=True)),
            patch(f"{MOD}.finish_owner_event", side_effect=finish),
            patch(f"{MOD}._load_context", AsyncMock(return_value=_context())),
            patch(f"{MOD}._insert_proposal",
                  AsyncMock(side_effect=lambda conn, **kw: dict(
                      proposal_id=70, status=kw["status"], relation_type=kw["plan"].relation_type,
                      result_card_id=kw.get("result_card_id"),
                      result_version_id=kw.get("result_version_id")))),
            patch(f"{MOD}._linked_target", AsyncMock(return_value=(550, 12))),
            patch(f"{MOD}._set_proposal", AsyncMock()),
            patch(f"{MOD}._flag_target_review", AsyncMock()),
            patch(f"{MOD}._lock_publication", AsyncMock()),
            patch(f"{MOD}._owner_answer_card", AsyncMock(return_value=None)),
            patch(f"{MOD}.create_owner_answer_card", AsyncMock(return_value=(90, 900))),
            patch(f"{MOD}.DbUsageSink", lambda pool: object()),
        ]
        self.mocks = [p.start() for p in self.patches]
        self.claim, self.heartbeat = self.mocks[0], self.mocks[1]
        self.load, self.insert = self.mocks[3], self.mocks[4]
        self.linked_target = self.mocks[5]
        self.create = self.mocks[10]

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _plan_mock(self, plan):
        return patch(f"{MOD}.build_knowledge_plan", AsyncMock(return_value=plan))

    async def _run(self):
        return await worker.process_next_owner_event(self.pool, store_id=STORE)

    # --- claim ---
    async def test_claim_none_returns_none(self):
        self.claim.return_value = None
        self.assertIsNone(await self._run())
        self.assertEqual(self.finished, [])

    async def test_stale_claim_returns_stale_without_finish(self):
        self.claim.return_value = dict(event_id="41", owner_answer_id="501", stale=True)
        self.assertEqual(await self._run(), "STALE")
        self.assertEqual(self.finished, [])

    # --- relation 4종 ---
    async def test_identical_current_card_is_linked(self):
        with self._plan_mock(_plan("IDENTICAL", target=55)):
            self.assertEqual(await self._run(), "LINKED")
        result, in_tx, _ = self.finished[0]
        self.assertEqual((result.status, result.card_id, result.knowledge_revision),
                         ("LINKED", "55", "12"))
        self.assertTrue(in_tx)
        kwargs = self.insert.await_args.kwargs
        self.assertEqual((kwargs["status"], kwargs["result_card_id"], kwargs["result_version_id"]),
                         ("LINKED", 55, 550))

    async def test_identical_not_in_current_publication_demotes_to_review(self):
        self.linked_target.return_value = None
        with self._plan_mock(_plan("IDENTICAL", target=55)):
            self.assertEqual(await self._run(), "REVIEW")
        self.assertEqual(self.finished[0][0].status, "REVIEW")
        self.assertEqual(self.insert.await_args.kwargs["status"], "PENDING_REVIEW")

    async def test_supplement_and_conflict_go_to_review(self):
        for relation in ("SUPPLEMENT", "CONFLICT"):
            self.finished.clear()
            with self._plan_mock(_plan(relation, target=55)):
                self.assertEqual(await self._run(), "REVIEW")
            result, in_tx, _ = self.finished[0]
            self.assertEqual(result.status, "REVIEW")
            self.assertTrue(in_tx)
            self.assertEqual(self.insert.await_args.kwargs["status"], "PENDING_REVIEW")

    async def test_new_publishes_and_finishes_only_inside_hook(self):
        async def publish(pool, **kw):
            self.assertEqual(self.finished, [])     # hook 전에는 finish 가 없다
            self.assertEqual(kw["changes"], [CardChange(90, 900, 900)])
            self.assertEqual(kw["idempotency_key"], "owner-answer:501")
            self.assertEqual((kw["member_id"], kw["actor_user_id"]), (2, 20))
            self.assertEqual(kw["usage_context"].stage, "EMBED")
            conn = FakeConn(self.log)
            async with conn.transaction():
                self.log.append("publish_tx")
                await kw["in_transaction"](conn, 300, 13)
            return PublishCardsResult(status="PUBLISHED", snapshot_id=300, knowledge_revision=13)

        with self._plan_mock(_plan("NEW", auto_publish=True)), \
                patch(f"{MOD}.publish_cards", side_effect=publish):
            self.assertEqual(await self._run(), "PUBLISHED")
        self.assertEqual(len(self.finished), 1)
        result, in_tx, before = self.finished[0]
        self.assertEqual((result.status, result.card_id, result.knowledge_revision),
                         ("PUBLISHED", "90", "13"))
        self.assertTrue(in_tx)
        self.assertIn("publish_tx", before)
        self.assertEqual(self.insert.await_args.kwargs["status"], "ANALYZED")
        self.create.assert_awaited_once()

    async def test_new_without_auto_publish_goes_to_review(self):
        with self._plan_mock(_plan("NEW", auto_publish=False)), \
                patch(f"{MOD}.publish_cards", AsyncMock()) as publish:
            self.assertEqual(await self._run(), "REVIEW")
        publish.assert_not_awaited()
        self.create.assert_not_awaited()

    async def test_no_provenance_becomes_review(self):
        with self._plan_mock(_plan("NEW", auto_publish=True)), \
                patch(f"{MOD}.publish_cards",
                      AsyncMock(return_value=PublishCardsResult(status="NO_PROVENANCE"))):
            self.assertEqual(await self._run(), "REVIEW")
        result, in_tx, _ = self.finished[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertTrue(in_tx)

    async def test_stale_publish_is_retryable_failure(self):
        with self._plan_mock(_plan("NEW", auto_publish=True)), \
                patch(f"{MOD}.publish_cards",
                      AsyncMock(return_value=PublishCardsResult(status="STALE"))):
            self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.status, result.retryable, result.error.code),
                         ("FAILED", True, "STALE_PUBLICATION"))

    async def test_invalid_content_publish_is_non_retryable_failure(self):
        """빈·과대 답변 원문은 색인 장애가 아니라 되풀이해도 같은 실패다(final fix #3)."""
        with self._plan_mock(_plan("NEW", auto_publish=True)), \
                patch(f"{MOD}.publish_cards",
                      AsyncMock(return_value=PublishCardsResult(status="INVALID_CONTENT"))):
            self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.status, result.retryable, result.error.code),
                         ("FAILED", False, "INVALID_CONTRACT"))

    async def test_existing_analyzed_proposal_reuses_card(self):
        self.load.return_value = _context(dict(proposal_id=70, status="ANALYZED",
                                               relation_type="NEW", result_card_id=None,
                                               result_version_id=None))
        self.mocks[9].return_value = (90, 900)
        plan = AsyncMock()
        with patch(f"{MOD}.build_knowledge_plan", plan), \
                patch(f"{MOD}.publish_cards",
                      AsyncMock(return_value=PublishCardsResult(
                          status="ALREADY_APPLIED", snapshot_id=300, knowledge_revision=13))):
            self.assertEqual(await self._run(), "PUBLISHED")
        plan.assert_not_awaited()
        self.create.assert_not_awaited()
        self.assertEqual(self.finished[0][0].status, "PUBLISHED")

    async def test_existing_linked_proposal_finishes_without_plan(self):
        self.load.return_value = _context(dict(proposal_id=70, status="LINKED",
                                               relation_type="IDENTICAL", result_card_id=55,
                                               result_version_id=550))
        plan = AsyncMock()
        with patch(f"{MOD}.build_knowledge_plan", plan):
            self.assertEqual(await self._run(), "LINKED")
        plan.assert_not_awaited()
        self.assertEqual(self.finished[0][0].card_id, "55")

    # --- 실패 ---
    async def test_exception_finishes_failed_in_separate_tx(self):
        with patch(f"{MOD}.build_knowledge_plan", AsyncMock(side_effect=RuntimeError("x"))):
            self.assertEqual(await self._run(), "FAILED")
        result, in_tx, _ = self.finished[0]
        self.assertEqual((result.status, result.error.code), ("FAILED", "INTERNAL_ERROR"))
        self.assertFalse(result.retryable)

        self.assertTrue(in_tx)

    async def test_missing_candidate_index_is_retryable_failure_not_new(self):
        with patch(f"{MOD}.build_knowledge_plan", AsyncMock(side_effect=ApiError(
                503, 'INDEX_UNAVAILABLE', 'missing active index', retryable=True))):
            self.assertEqual(await self._run(), 'FAILED')
        result = self.finished[0][0]
        self.assertEqual(result.error.code, 'INDEX_UNAVAILABLE')
        self.assertTrue(result.retryable)
        self.create.assert_not_awaited()

    async def test_hook_failure_rolls_back_publish_then_finishes_failed(self):
        async def finish(conn, *, store_id, event_id, claim_token, result):
            if result.status == "PUBLISHED":
                raise ApiError(409, "STALE_KNOWLEDGE", "stale", retryable=True)
            self.finished.append((result, conn.is_in_transaction(), list(self.log)))

        async def publish(pool, **kw):
            conn = FakeConn(self.log)
            async with conn.transaction():
                await kw["in_transaction"](conn, 300, 13)
            return PublishCardsResult(status="PUBLISHED", snapshot_id=300, knowledge_revision=13)

        with self._plan_mock(_plan("NEW", auto_publish=True)), \
                patch(f"{MOD}.publish_cards", side_effect=publish), \
                patch(f"{MOD}.finish_owner_event", side_effect=finish):
            self.assertEqual(await self._run(), "FAILED")
        self.assertIn("tx_rollback", self.log)
        result = self.finished[0][0]
        self.assertEqual((result.error.code, result.retryable), ("STALE_KNOWLEDGE", True))

    async def test_heartbeat_lost_stops_without_finish(self):
        self.heartbeat.return_value = False
        plan = AsyncMock()
        with patch(f"{MOD}.build_knowledge_plan", plan):
            self.assertEqual(await self._run(), "FAILED")
        plan.assert_not_awaited()
        self.assertEqual(self.finished, [])

    async def test_failed_finish_error_is_logged_not_raised(self):
        async def finish(conn, **kw):
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "lease lost")

        with patch(f"{MOD}.build_knowledge_plan", AsyncMock(side_effect=RuntimeError("x"))), \
                patch(f"{MOD}.finish_owner_event", side_effect=finish):
            self.assertEqual(await self._run(), "FAILED")

    async def test_missing_owner_membership_is_non_retryable_failure(self):
        ctx = _context()
        ctx["owner"] = None
        self.load.return_value = ctx
        with self._plan_mock(_plan("NEW", auto_publish=True)):
            self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.error.code, result.retryable), ("NOT_FOUND", False))


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_loop_drains_each_store_and_stops(self):
        stop = asyncio.Event()
        outcomes = {1: ["PUBLISHED", None], 2: [None]}
        calls = []

        async def process(pool, *, store_id):
            calls.append(store_id)
            result = outcomes[store_id].pop(0)
            if not any(outcomes.values()):
                stop.set()
            return result

        with patch(f"{MOD}._stores_with_pending", AsyncMock(return_value=[1, 2])), \
                patch(f"{MOD}.process_next_owner_event", side_effect=process):
            await asyncio.wait_for(worker.run_owner_answer_worker(object(), stop=stop), 2)
        self.assertEqual(calls, [1, 1, 2])

    async def test_loop_logs_exception_and_continues(self):
        stop = asyncio.Event()
        results = [RuntimeError("db"), []]

        async def scan(pool):
            value = results.pop(0)
            if not results:
                stop.set()
            if isinstance(value, Exception):
                raise value
            return value

        with patch(f"{MOD}._stores_with_pending", side_effect=scan) as scans, \
                patch(f"{MOD}.get_settings") as settings:
            settings.return_value.w_owner_answer_worker_interval_sec = 0
            await asyncio.wait_for(worker.run_owner_answer_worker(object(), stop=stop), 2)
        self.assertEqual(scans.await_count, 2)


class SetProposalSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_parameter_is_cast_consistently(self):
        """$3 을 varchar 컬럼 대입과 text IN 비교에 같이 쓰면 실제 Postgres 가
        AmbiguousParameterError 로 거절한다(Task 7 실제 DB 검증에서 발견). 모든 사용처에
        같은 캐스트가 붙어 있어야 한다."""
        import re

        class Db:
            sql = None

            async def execute(self, sql, *args):
                Db.sql = sql

        await worker._set_proposal(Db(), store_id=STORE, proposal_id=1, status="PUBLISHED")
        uses = re.findall(r"\$3(?:::\w+)?", Db.sql)
        self.assertGreaterEqual(len(uses), 2)
        self.assertEqual(set(uses), {"$3::varchar"})


class CreateOwnerAnswerCardTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_draft_without_publishing(self):
        from app.learn.knowledge_apply import create_owner_answer_card

        class Db:
            def __init__(self):
                self.sql = []
                self.values = iter([3, 90, 900])   # 카테고리, card_id, draft_version_id

            async def fetchval(self, sql, *args):
                self.sql.append(sql)
                return next(self.values)

            async def execute(self, sql, *args):
                self.sql.append(sql)

        db = Db()
        self.assertEqual(await create_owner_answer_card(
            db, store_id=STORE, category_id=3, title="t", content="c",
            answer_id=501, actor_id=20), (90, 900))
        joined = "\n".join(db.sql)
        self.assertIn("false, 'AUTOMATIC'", joined)
        self.assertNotIn("is_verified = true", joined)
        self.assertNotIn("published_version_id", joined)
        self.assertIn("change_source = 'OWNER_ANSWER'", joined)
        self.assertIn("update owner_answers set card_id", joined)


class SqlConn(FakeConn):
    """_linked_target 의 실제 SQL 을 흉내 낸다. 공개판·카드 상태를 바꿔 가며 본다."""

    def __init__(self, log, card):
        super().__init__(log)
        self.card = card

    async def fetchrow(self, sql, *args):
        if "from knowledge_publications" in sql:
            self.log.append("lock_publication" if "for update" in sql else "read_publication")
            return dict(current_snapshot_id=300, knowledge_revision=12)
        if "from knowledge_cards" in sql:
            self.log.append("read_card")
            return self.card
        raise AssertionError(sql)


class SqlPool(FakePool):
    def __init__(self, log, card):
        super().__init__(log)
        self.card = card

    @asynccontextmanager
    async def acquire(self):
        yield SqlConn(self.log, self.card)


APPROVED = dict(review_status="APPROVED", is_verified=True, published_version_id=550)


class LinkedPreconditionTests(unittest.IsolatedAsyncioTestCase):
    """R 의 publication_evidence 와 같은 조건을 LINKED 전에 확인한다 (Fix round 1)."""

    async def asyncSetUp(self):
        self.log: list = []
        self.finished: list = []

        async def finish(conn, *, store_id, event_id, claim_token, result):
            self.finished.append(result)
            self.log.append(f"finish:{result.status}")

        async def insert(conn, **kw):
            self.log.append(f"insert:{kw['status']}")
            return dict(proposal_id=70, status=kw["status"], relation_type="IDENTICAL",
                        result_card_id=kw.get("result_card_id"),
                        result_version_id=kw.get("result_version_id"))

        self.plan = AsyncMock(return_value=_plan("IDENTICAL", target=55))
        self.set_proposal = AsyncMock()
        self.patches = [
            patch(f"{MOD}.claim_owner_event", AsyncMock(return_value=dict(CLAIM))),
            patch(f"{MOD}.heartbeat_owner_event", AsyncMock(return_value=True)),
            patch(f"{MOD}.finish_owner_event", side_effect=finish),
            patch(f"{MOD}._load_context", AsyncMock(return_value=_context())),
            patch(f"{MOD}._insert_proposal", side_effect=insert),
            patch(f"{MOD}._set_proposal", self.set_proposal),
            patch(f"{MOD}._flag_target_review", AsyncMock()),
            patch(f"{MOD}.current_manifest", AsyncMock(return_value={55: 550})),
            patch(f"{MOD}.build_knowledge_plan", self.plan),
            patch(f"{MOD}.DbUsageSink", lambda pool: object()),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()

    async def _run(self, card):
        return await worker.process_next_owner_event(SqlPool(self.log, card), store_id=STORE)

    async def test_approved_current_card_links_after_publication_lock(self):
        self.assertEqual(await self._run(dict(APPROVED)), "LINKED")
        self.assertEqual(self.finished[0].status, "LINKED")
        self.assertLess(self.log.index("lock_publication"), self.log.index("insert:LINKED"))

    async def test_card_in_manifest_but_not_servable_demotes_to_review(self):
        for broken in (dict(APPROVED, review_status="NEEDS_REVIEW"),
                       dict(APPROVED, is_verified=False),
                       dict(APPROVED, published_version_id=551),
                       None):
            self.log.clear()
            self.finished.clear()
            self.plan.reset_mock()
            self.assertEqual(await self._run(broken), "REVIEW", broken)
            self.assertEqual([r.status for r in self.finished], ["REVIEW"])
            self.assertEqual(self.plan.await_count, 1)
            self.assertIn("insert:PENDING_REVIEW", self.log)
            self.assertLess(self.log.index("lock_publication"),
                            self.log.index("insert:PENDING_REVIEW"))

    async def test_recorded_linked_card_no_longer_servable_reports_review(self):
        with patch(f"{MOD}._load_context", AsyncMock(return_value=_context(dict(
                proposal_id=70, status="LINKED", relation_type="IDENTICAL",
                result_card_id=55, result_version_id=550)))):
            self.assertEqual(await self._run(dict(APPROVED, review_status="PENDING")), "REVIEW")
        self.plan.assert_not_awaited()
        self.assertEqual([r.status for r in self.finished], ["REVIEW"])
        self.assertEqual(self.set_proposal.await_args.kwargs["status"], "PENDING_REVIEW")

    async def test_recorded_published_card_checked_the_same_way(self):
        with patch(f"{MOD}._load_context", AsyncMock(return_value=_context(dict(
                proposal_id=70, status="PUBLISHED", relation_type="NEW",
                result_card_id=55, result_version_id=550)))):
            self.assertEqual(await self._run(dict(APPROVED)), "PUBLISHED")
            self.finished.clear()
            self.assertEqual(await self._run(dict(APPROVED, is_verified=False)), "REVIEW")
        self.assertEqual([r.status for r in self.finished], ["REVIEW"])


if __name__ == "__main__":
    unittest.main()
