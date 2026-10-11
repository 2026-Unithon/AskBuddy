"""점주 답변 반영 worker 의 결정·트랜잭션 경계를 검증한다 (Phase A Task 6).

R 인계 함수·사실 수집(owner_text)·publish_cards·DB 보조 함수는 patch 한다. 여기서 보는 것은
**이어진 카드 판정별로 어떤 결과를 어느 트랜잭션에서 R 에 알리는가** 다. 실제 DB 는
verify_w_fact_only (b)·verify_w_publication_flow §9 가 돈다.
"""
from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.cards import owner_answer_worker as worker
from app.errors import ApiError
from app.ingest.owner_text import AnswerCard
from app.publish.approval import CardChange, PublishCardsResult

STORE = 7
MOD = "app.cards.owner_answer_worker"
OT = "app.ingest.owner_text"
SOURCE = 300
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
        self.held = 0   # 지금 빌려 간 연결 수

    @asynccontextmanager
    async def acquire(self):
        self.held += 1
        try:
            yield FakeConn(self.log)
        finally:
            self.held -= 1


def card(cid, *, draft, published=None, status="PENDING", reason=None):
    return AnswerCard(card_id=cid, draft_version_id=draft, published_version_id=published,
                      review_status=status, needs_review_reason=reason)


NEW_A = card(90, draft=900)
NEW_B = card(91, draft=910)
LINKED = card(55, draft=550, published=550, status="APPROVED")
CHANGED = card(55, draft=551, published=550, status="APPROVED", reason="NEW_FACTS")


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

        async def ensure(conn, store_id, **kw):
            # 자료 보장은 트랜잭션 안에서만 부를 수 있다(실제 함수가 RuntimeError)
            assert conn.is_in_transaction() and store_id == STORE
            self.log.append("ensure")
            return SOURCE, self.source_status

        async def ingest(pool, **kw):
            self.ingest_held = self.pool.held
            self.log.append("ingest")
            return self.fact_count

        self.source_status = "PROCESSING"
        self.fact_count = 2
        self.ingest_held = None
        self.patches = [
            patch(f"{MOD}.claim_owner_event", AsyncMock(return_value=dict(CLAIM))),
            patch(f"{MOD}.heartbeat_owner_event", AsyncMock(return_value=True)),
            patch(f"{MOD}.finish_owner_event", side_effect=finish),
            patch(f"{MOD}._load_context", AsyncMock(return_value=_context())),
            patch(f"{MOD}._insert_proposal",
                  AsyncMock(side_effect=lambda conn, **kw: dict(
                      proposal_id=70, status=kw["status"], relation_type=kw["relation"],
                      result_card_id=kw.get("result_card_id"),
                      result_version_id=kw.get("result_version_id")))),
            patch(f"{MOD}._linked_target", AsyncMock(return_value=(550, 12))),
            patch(f"{MOD}._set_proposal", AsyncMock()),
            patch(f"{MOD}._flag_target_review", AsyncMock()),
            patch(f"{MOD}._lock_publication", AsyncMock()),
            patch(f"{MOD}._card_text", AsyncMock(return_value=("카드 제목", "카드 본문", 4))),
            patch(f"{MOD}.resolve_owner_answer_category", AsyncMock(return_value=8)),
            patch(f"{OT}.ensure_owner_answer_source", side_effect=ensure),
            patch(f"{OT}.ingest_owner_text", side_effect=ingest),
            patch(f"{OT}.answer_cards", AsyncMock(return_value=[NEW_A])),
            patch(f"{OT}.answer_fact_count", AsyncMock(side_effect=lambda *a, **k: self.fact_count)),
            patch(f"{OT}.owner_answer_source", AsyncMock(return_value=SOURCE)),
        ]
        self.mocks = [p.start() for p in self.patches]
        (self.claim, self.heartbeat, _, self.load, self.insert, self.linked_target,
         self.set_proposal, self.flag, _, self.card_text, self.resolve, self.ensure,
         self.ingest, self.cards, _, self.source) = self.mocks

    def tearDown(self):
        for p in self.patches:
            p.stop()

    async def _run(self):
        return await worker.process_next_owner_event(self.pool, store_id=STORE)

    def _publish_ok(self, check=None):
        async def publish(pool, **kw):
            self.assertEqual(self.finished, [])     # hook 전에는 finish 가 없다
            if check is not None:
                check(kw)
            conn = FakeConn(self.log)
            async with conn.transaction():
                self.log.append("publish_tx")
                await kw["in_transaction"](conn, 300, 13)
            return PublishCardsResult(status="PUBLISHED", snapshot_id=300, knowledge_revision=13)
        return patch(f"{MOD}.publish_cards", side_effect=publish)

    # --- claim ---
    async def test_claim_none_returns_none(self):
        self.claim.return_value = None
        self.assertIsNone(await self._run())
        self.assertEqual(self.finished, [])

    async def test_stale_claim_returns_stale_without_finish(self):
        self.claim.return_value = dict(event_id="41", owner_answer_id="501", stale=True)
        self.assertEqual(await self._run(), "STALE")
        self.assertEqual(self.finished, [])

    # --- 사실 수집 ---
    async def test_collects_facts_through_owner_text_without_holding_connection(self):
        self.cards.return_value = [LINKED]
        self.assertEqual(await self._run(), "LINKED")
        kw = self.ensure.call_args.kwargs
        self.assertEqual((kw["owner_answer_id"], kw["actor_id"], kw["question"], kw["answer"]),
                         (501, 20, "질문", "답"))
        kw = self.ingest.call_args.kwargs
        self.assertEqual((kw["store_id"], kw["source_id"], kw["question"], kw["answer"]),
                         (STORE, SOURCE, "질문", "답"))
        self.assertIsInstance(kw["run_tag"], int)
        # 추출·조립(모델 호출) 중에는 풀 연결을 쥐지 않는다
        self.assertEqual(self.ingest_held, 0)
        self.assertLess(self.log.index("ensure"), self.log.index("ingest"))

    async def test_done_source_skips_ingest(self):
        self.source_status = "DONE"
        self.cards.return_value = [LINKED]
        self.assertEqual(await self._run(), "LINKED")
        self.ingest.assert_not_called()
        self.cards.assert_awaited()

    async def test_relation_analysis_is_gone(self):
        self.assertFalse(hasattr(worker, "build_knowledge_plan"))
        self.assertFalse(hasattr(worker, "create_owner_answer_card"))
        self.assertFalse(hasattr(worker, "_record_plan"))

    # --- 판정별 결과 ---
    async def test_identical_current_card_is_linked(self):
        self.cards.return_value = [LINKED]
        self.assertEqual(await self._run(), "LINKED")
        result, in_tx, _ = self.finished[0]
        self.assertEqual((result.status, result.card_id, result.knowledge_revision),
                         ("LINKED", "55", "12"))
        self.assertTrue(in_tx)
        kw = self.insert.await_args.kwargs
        self.assertEqual((kw["status"], kw["relation"], kw["result_card_id"],
                          kw["result_version_id"], kw["target_card_id"], kw["target_version_id"]),
                         ("LINKED", "IDENTICAL", 55, 550, 55, 550))
        self.assertEqual(kw["reason"], "OWNER_ANSWER_LINKED")

    async def test_identical_not_in_current_publication_demotes_to_review(self):
        self.cards.return_value = [LINKED]
        self.linked_target.return_value = None
        self.assertEqual(await self._run(), "REVIEW")
        self.assertEqual(self.finished[0][0].status, "REVIEW")
        self.assertEqual(self.insert.await_args.kwargs["status"], "PENDING_REVIEW")
        self.assertEqual(self.flag.await_args.kwargs,
                         dict(store_id=STORE, card_id=55, relation="IDENTICAL"))

    async def test_changed_published_card_is_supplement_review(self):
        self.cards.return_value = [CHANGED, NEW_A]
        self.assertEqual(await self._run(), "REVIEW")
        result, in_tx, _ = self.finished[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertTrue(in_tx)
        kw = self.insert.await_args.kwargs
        self.assertEqual((kw["status"], kw["relation"], kw["target_card_id"],
                          kw["target_version_id"], kw["reason"]),
                         ("PENDING_REVIEW", "SUPPLEMENT", 55, 550, "OWNER_ANSWER_REVIEW"))
        # 제목·본문은 첫 카드의 초안 판, 카테고리는 그 카드의 것
        self.assertEqual((kw["title"], kw["content"], kw["category_id"]),
                         ("카드 제목", "카드 본문", 4))
        self.assertEqual(self.card_text.await_args.kwargs["card"], CHANGED)
        self.assertEqual([c.kwargs["card_id"] for c in self.flag.await_args_list], [55, 90])
        self.assertTrue(all(c.kwargs["relation"] == "SUPPLEMENT"
                            for c in self.flag.await_args_list))

    async def test_no_facts_goes_to_review_with_question_and_answer(self):
        self.fact_count = 0
        self.cards.return_value = []
        with patch(f"{MOD}.publish_cards", AsyncMock()) as publish:
            self.assertEqual(await self._run(), "REVIEW")
        publish.assert_not_awaited()
        kw = self.insert.await_args.kwargs
        self.assertEqual((kw["status"], kw["relation"], kw["reason"], kw["title"],
                          kw["content"], kw["category_id"], kw["target_card_id"]),
                         ("PENDING_REVIEW", "NEW", "NO_FACTS", "질문", "답", 8, None))
        self.assertEqual(self.resolve.await_args.kwargs, dict(store_id=STORE, category_id=None))
        self.flag.assert_not_awaited()

    async def test_facts_without_cards_is_pending_review(self):
        self.cards.return_value = []
        self.assertEqual(await self._run(), "REVIEW")
        self.assertEqual(self.insert.await_args.kwargs["reason"], "FACTS_PENDING")

    async def test_new_card_needing_review_goes_to_review(self):
        self.cards.return_value = [card(90, draft=900, status="NEEDS_REVIEW",
                                        reason="NO_PROVENANCE")]
        with patch(f"{MOD}.publish_cards", AsyncMock()) as publish:
            self.assertEqual(await self._run(), "REVIEW")
        publish.assert_not_awaited()
        kw = self.insert.await_args.kwargs
        self.assertEqual((kw["relation"], kw["status"]), ("NEW", "PENDING_REVIEW"))

    async def test_new_publishes_all_cards_and_finishes_only_inside_hook(self):
        self.cards.return_value = [NEW_A, NEW_B]

        def check(kw):
            self.assertEqual(kw["changes"], [CardChange(90, 900, 900), CardChange(91, 910, 910)])
            self.assertEqual(kw["idempotency_key"], "owner-answer:501")
            self.assertEqual((kw["member_id"], kw["actor_user_id"]), (2, 20))
            self.assertEqual(kw["usage_context"].stage, "EMBED")

        with self._publish_ok(check) as publish:
            self.assertEqual(await self._run(), "PUBLISHED")
        publish.assert_awaited_once()
        self.assertEqual(len(self.finished), 1)
        result, in_tx, before = self.finished[0]
        self.assertEqual((result.status, result.card_id, result.knowledge_revision),
                         ("PUBLISHED", "90", "13"))
        self.assertTrue(in_tx)
        self.assertIn("publish_tx", before)
        self.assertEqual(self.insert.await_args.kwargs["status"], "ANALYZED")
        self.assertEqual(self.set_proposal.await_args.kwargs,
                         dict(store_id=STORE, proposal_id=70, status="PUBLISHED",
                              result_card_id=90, result_version_id=900))

    async def test_no_provenance_becomes_review(self):
        with patch(f"{MOD}.publish_cards",
                   AsyncMock(return_value=PublishCardsResult(status="NO_PROVENANCE"))):
            self.assertEqual(await self._run(), "REVIEW")
        result, in_tx, _ = self.finished[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertTrue(in_tx)
        self.assertEqual(self.set_proposal.await_args.kwargs["status"], "PENDING_REVIEW")

    async def test_stale_publish_is_retryable_failure(self):
        with patch(f"{MOD}.publish_cards",
                   AsyncMock(return_value=PublishCardsResult(status="STALE"))):
            self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.status, result.retryable, result.error.code),
                         ("FAILED", True, "STALE_PUBLICATION"))

    async def test_invalid_content_publish_is_non_retryable_failure(self):
        with patch(f"{MOD}.publish_cards",
                   AsyncMock(return_value=PublishCardsResult(status="INVALID_CONTENT"))):
            self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.status, result.retryable, result.error.code),
                         ("FAILED", False, "INVALID_CONTRACT"))

    # --- 재시도 ---
    async def test_existing_analyzed_proposal_rereads_cards_and_publishes(self):
        self.load.return_value = _context(dict(proposal_id=70, status="ANALYZED",
                                               relation_type="NEW", result_card_id=None,
                                               result_version_id=None))
        with patch(f"{MOD}.publish_cards",
                   AsyncMock(return_value=PublishCardsResult(
                       status="ALREADY_APPLIED", snapshot_id=300,
                       knowledge_revision=13))) as publish:
            self.assertEqual(await self._run(), "PUBLISHED")
        self.ensure.assert_not_called()
        self.ingest.assert_not_called()
        self.insert.assert_not_awaited()
        self.assertEqual(self.source.await_args.kwargs, dict(owner_answer_id=501))
        self.assertEqual(publish.await_args.kwargs["changes"], [CardChange(90, 900, 900)])
        self.assertEqual(self.finished[0][0].status, "PUBLISHED")

    async def test_existing_analyzed_proposal_now_needing_review_reports_review(self):
        self.load.return_value = _context(dict(proposal_id=70, status="ANALYZED",
                                               relation_type="NEW", result_card_id=None,
                                               result_version_id=None))
        self.cards.return_value = [card(90, draft=900, status="NEEDS_REVIEW",
                                        reason="NO_PROVENANCE")]
        with patch(f"{MOD}.publish_cards", AsyncMock()) as publish, \
                patch(f"{MOD}._retarget_proposal", AsyncMock()) as retarget:
            self.assertEqual(await self._run(), "REVIEW")
        publish.assert_not_awaited()
        # 상태만이 아니라 관계·대상·사유도 새 판정으로 맞춘다(Task 6 minor 1)
        outcome = retarget.await_args.kwargs["outcome"]
        self.assertEqual((retarget.await_args.kwargs["proposal_id"], outcome.kind,
                          outcome.relation), (70, "REVIEW", "NEW"))
        self.set_proposal.assert_not_awaited()
        self.assertTrue(self.finished[0][1])

    async def test_resume_demoted_to_supplement_retargets_proposal(self):
        self.load.return_value = _context(dict(proposal_id=70, status="ANALYZED",
                                               relation_type="NEW", result_card_id=None,
                                               result_version_id=None))
        self.cards.return_value = [CHANGED]
        with patch(f"{MOD}.publish_cards", AsyncMock()), \
                patch(f"{MOD}._retarget_proposal", AsyncMock()) as retarget:
            self.assertEqual(await self._run(), "REVIEW")
        outcome = retarget.await_args.kwargs["outcome"]
        self.assertEqual((outcome.relation, outcome.target.card_id), ("SUPPLEMENT", 55))

    async def test_existing_analyzed_proposal_without_source_fails(self):
        self.load.return_value = _context(dict(proposal_id=70, status="ANALYZED",
                                               relation_type="NEW", result_card_id=None,
                                               result_version_id=None))
        self.source.return_value = None
        self.assertEqual(await self._run(), "FAILED")
        self.assertEqual(self.finished[0][0].error.code, "INVALID_REFERENCE")

    async def test_existing_linked_proposal_finishes_without_collecting(self):
        self.load.return_value = _context(dict(proposal_id=70, status="LINKED",
                                               relation_type="IDENTICAL", result_card_id=55,
                                               result_version_id=550))
        self.assertEqual(await self._run(), "LINKED")
        self.ensure.assert_not_called()
        self.ingest.assert_not_called()
        self.assertEqual(self.finished[0][0].card_id, "55")

    # --- 실패 ---
    async def test_exception_finishes_failed_in_separate_tx(self):
        self.ingest.side_effect = RuntimeError("x")
        self.assertEqual(await self._run(), "FAILED")
        result, in_tx, _ = self.finished[0]
        self.assertEqual((result.status, result.error.code), ("FAILED", "INTERNAL_ERROR"))
        self.assertFalse(result.retryable)
        self.assertTrue(in_tx)

    async def test_api_error_during_ingest_keeps_its_retryable_code(self):
        self.ingest.side_effect = ApiError(503, "INDEX_UNAVAILABLE", "missing active index",
                                           retryable=True)
        self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual(result.error.code, "INDEX_UNAVAILABLE")
        self.assertTrue(result.retryable)
        self.insert.assert_not_awaited()

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

        with patch(f"{MOD}.publish_cards", side_effect=publish), \
                patch(f"{MOD}.finish_owner_event", side_effect=finish):
            self.assertEqual(await self._run(), "FAILED")
        self.assertIn("tx_rollback", self.log)
        result = self.finished[0][0]
        self.assertEqual((result.error.code, result.retryable), ("STALE_KNOWLEDGE", True))

    async def test_new_publish_extends_lease_after_prepare(self):
        """색인 준비 뒤 heartbeat 로 점유를 연장한다. 준비가 길면 lease 가 끝났을 수 있다."""
        async def publish(pool, **kw):
            before = self.heartbeat.await_count
            self.assertTrue(await kw["after_prepare"]())
            self.assertEqual(self.heartbeat.await_count, before + 1)
            self.assertEqual(self.heartbeat.await_args.kwargs,
                             dict(store_id=STORE, event_id=41, claim_token="tok"))
            conn = FakeConn(self.log)
            async with conn.transaction():
                await kw["in_transaction"](conn, 300, 13)
            return PublishCardsResult(status="PUBLISHED", snapshot_id=300, knowledge_revision=13)

        with patch(f"{MOD}.publish_cards", side_effect=publish):
            self.assertEqual(await self._run(), "PUBLISHED")

    async def test_new_publish_lease_lost_after_prepare_stops_without_finish(self):
        async def publish(pool, **kw):
            # 준비 뒤 heartbeat 가 점유 상실을 알린다 → publish_cards 는 LEASE_LOST
            self.heartbeat.return_value = False
            if not await kw["after_prepare"]():
                return PublishCardsResult(status="LEASE_LOST")
            raise AssertionError("after_prepare 가 False 를 돌려줘야 한다")

        with patch(f"{MOD}.publish_cards", side_effect=publish):
            self.assertEqual(await self._run(), "FAILED")
        # 다른 worker 몫이다. FAILED 보고도 하지 않는다
        self.assertEqual(self.finished, [])

    async def test_heartbeat_lost_stops_without_finish(self):
        self.heartbeat.return_value = False
        self.assertEqual(await self._run(), "FAILED")
        self.ensure.assert_not_called()
        self.ingest.assert_not_called()
        self.assertEqual(self.finished, [])

    async def test_heartbeat_lost_after_ingest_stops_without_recording(self):
        beats = iter([True, True, False])
        self.heartbeat.side_effect = lambda *a, **k: next(beats)
        self.assertEqual(await self._run(), "FAILED")
        self.ingest.assert_called_once()
        self.insert.assert_not_awaited()
        self.assertEqual(self.finished, [])

    async def test_failed_finish_error_is_logged_not_raised(self):
        async def finish(conn, **kw):
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "lease lost")

        self.ingest.side_effect = RuntimeError("x")
        with patch(f"{MOD}.finish_owner_event", side_effect=finish):
            self.assertEqual(await self._run(), "FAILED")

    async def test_missing_owner_membership_is_non_retryable_failure(self):
        ctx = _context()
        ctx["owner"] = None
        self.load.return_value = ctx
        self.assertEqual(await self._run(), "FAILED")
        result = self.finished[0][0]
        self.assertEqual((result.error.code, result.retryable), ("NOT_FOUND", False))
        self.ensure.assert_not_called()


class FlagTargetReviewSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_does_not_overwrite_safety_reasons(self):
        """NO_PROVENANCE·FACT_CONFLICT_OPEN·FALLBACK:* 는 덮지 않는다 — 사유 없음·NEW_FACTS 만."""

        class Db:
            calls = []

            async def execute(self, sql, *args):
                Db.calls.append((sql, args))

        await worker._flag_target_review(Db(), store_id=STORE, card_id=55, relation="SUPPLEMENT")
        sql, args = Db.calls[0]
        self.assertIn("needs_review_reason is null or needs_review_reason = $4", sql)
        self.assertEqual(args, (STORE, 55, "OWNER_ANSWER_SUPPLEMENT", "NEW_FACTS"))
        Db.calls.clear()
        await worker._flag_target_review(Db(), store_id=STORE, card_id=None, relation="NEW")
        self.assertEqual(Db.calls, [])


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
                patch(f"{MOD}._index_ready", AsyncMock(return_value=True)), \
                patch(f"{MOD}.process_next_owner_event", side_effect=process):
            await asyncio.wait_for(worker.run_owner_answer_worker(object(), stop=stop), 2)
        self.assertEqual(calls, [1, 1, 2])

    async def test_loop_skips_store_without_active_index(self):
        """활성 공개 색인이 없는 매장은 사건을 태우지(FAILED) 않고 건너뛴다."""
        stop = asyncio.Event()
        calls = []

        async def ready(pool, *, store_id, warned):
            return store_id != 1

        async def process(pool, *, store_id):
            calls.append(store_id)
            stop.set()
            return None

        with patch(f"{MOD}._stores_with_pending", AsyncMock(return_value=[1, 2])), \
                patch(f"{MOD}._index_ready", side_effect=ready), \
                patch(f"{MOD}.process_next_owner_event", side_effect=process):
            await asyncio.wait_for(worker.run_owner_answer_worker(object(), stop=stop), 2)
        self.assertEqual(calls, [2])

    async def test_index_ready_warns_once_per_status(self):
        from app.publish.bootstrap import IndexStatus

        class Pool:
            def acquire(self):
                return _Ctx()

        class _Ctx:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *exc):
                return False

        statuses = iter([IndexStatus(5, "MISSING", 3, 0), IndexStatus(5, "MISSING", 3, 0),
                         IndexStatus(5, "READY", 3, 1)])
        warned: dict[int, str] = {}
        with patch(f"{MOD}.index_status", AsyncMock(side_effect=lambda *a, **k: next(statuses))), \
                self.assertLogs(worker.logger, level="WARNING") as logs:
            self.assertFalse(await worker._index_ready(Pool(), store_id=5, warned=warned))
            self.assertFalse(await worker._index_ready(Pool(), store_id=5, warned=warned))
            self.assertTrue(await worker._index_ready(Pool(), store_id=5, warned=warned))
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(warned, {})

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


class RetargetProposalSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_retarget_updates_relation_target_reason_in_store(self):
        class Db:
            calls = []

            async def execute(self, sql, *args):
                Db.calls.append((sql, args))

        outcome = worker.AnswerOutcome("REVIEW", "SUPPLEMENT", (CHANGED,), CHANGED)
        await worker._retarget_proposal(Db(), store_id=STORE, proposal_id=70, outcome=outcome)
        sql, args = Db.calls[0]
        self.assertIn("status = 'PENDING_REVIEW'", sql)
        self.assertIn("where store_id = $1 and proposal_id = $2", sql)
        self.assertEqual(args, (STORE, 70, "SUPPLEMENT", 55, 550, "OWNER_ANSWER_REVIEW"))


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
            return dict(proposal_id=70, status=kw["status"], relation_type=kw["relation"],
                        result_card_id=kw.get("result_card_id"),
                        result_version_id=kw.get("result_version_id"))

        self.cards = AsyncMock(return_value=[LINKED])
        self.set_proposal = AsyncMock()
        self.patches = [
            patch(f"{MOD}.claim_owner_event", AsyncMock(return_value=dict(CLAIM))),
            patch(f"{MOD}.heartbeat_owner_event", AsyncMock(return_value=True)),
            patch(f"{MOD}.finish_owner_event", side_effect=finish),
            patch(f"{MOD}._load_context", AsyncMock(return_value=_context())),
            patch(f"{MOD}._insert_proposal", side_effect=insert),
            patch(f"{MOD}._set_proposal", self.set_proposal),
            patch(f"{MOD}._flag_target_review", AsyncMock()),
            patch(f"{MOD}._card_text", AsyncMock(return_value=("t", "c", 4))),
            patch(f"{MOD}.current_manifest", AsyncMock(return_value={55: 550})),
            patch(f"{OT}.ensure_owner_answer_source", AsyncMock(return_value=(SOURCE, "DONE"))),
            patch(f"{OT}.answer_cards", self.cards),
            patch(f"{OT}.answer_fact_count", AsyncMock(return_value=1)),
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
            self.assertEqual(await self._run(broken), "REVIEW", broken)
            self.assertEqual([r.status for r in self.finished], ["REVIEW"])
            self.assertIn("insert:PENDING_REVIEW", self.log)
            self.assertLess(self.log.index("lock_publication"),
                            self.log.index("insert:PENDING_REVIEW"))

    async def test_recorded_linked_card_no_longer_servable_reports_review(self):
        with patch(f"{MOD}._load_context", AsyncMock(return_value=_context(dict(
                proposal_id=70, status="LINKED", relation_type="IDENTICAL",
                result_card_id=55, result_version_id=550)))):
            self.assertEqual(await self._run(dict(APPROVED, review_status="PENDING")), "REVIEW")
        self.cards.assert_not_awaited()
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
