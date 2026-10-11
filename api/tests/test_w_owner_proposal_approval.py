"""검수 대기 점주 답변 제안의 나중 승인 `approve_owner_proposal` (Phase A Task 6).

승인 = 그 답변 자료(OWNER_TEXT)가 만든 사실 카드 초안을 모두 한 번에 공개한다.
DB 보조 함수·publish_cards 는 patch 한다. 여기서 보는 것은
  - 사실 초안이 없는 제안(v1 관계 분석 제안·사실 0개)을 ValueError 로 거절하는가
  - 초안 카드 전부를 publish_cards 한 번으로 공개하는가
  - hook 이 제안을 다시 확인하고 R 완료 접점(notify_r)을 같은 트랜잭션에서 부르는가
실제 DB 는 verify_w_fact_only (b)·verify_w_publication_flow §9 가 돈다.
"""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.contracts.usage import UsageContext
from app.ingest.owner_text import AnswerCard
from app.learn import knowledge_apply as ka
from app.publish.approval import CardChange, PublishCardsResult

STORE = 7
MEMBER = 2
ACTOR = 20
PROPOSAL = 70
ANSWER = 501
SOURCE = 300
MOD = "app.learn.knowledge_apply"


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


def _proposal(relation="NEW", status="PENDING_REVIEW", result_card=None, result_version=None):
    return dict(proposal_id=PROPOSAL, answer_id=ANSWER, relation_type=relation,
                status=status, target_card_id=None, target_version_id=None,
                category_id=3, proposed_title="제목", proposed_content="내용",
                result_card_id=result_card, result_version_id=result_version)


def card(cid, *, draft, published=None, status="PENDING", reason=None):
    return AnswerCard(card_id=cid, draft_version_id=draft, published_version_id=published,
                      review_status=status, needs_review_reason=reason)


# 새 카드 5(초안 50), 공개 카드 7(초안 71·공개 70), 공개 카드 9(초안=공개 90)
CARDS = [card(5, draft=50), card(7, draft=71, published=70, status="APPROVED",
                                  reason="NEW_FACTS"),
         card(9, draft=90, published=90, status="APPROVED")]


def _usage() -> UsageContext:
    return UsageContext(store_id=str(STORE), stage="EMBED", cost_phase="OPERATING",
                        cost_purpose="PRODUCT", logical_call_id="owner-proposal:t",
                        operation_id="t")


class ApproveOwnerProposalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log: list = []
        self.pool = FakePool(self.log)
        self.publish_result = PublishCardsResult(status="PUBLISHED", snapshot_id=5,
                                                 knowledge_revision=12)
        self.patches = {
            "lock_publication": patch(f"{MOD}._lock_publication", AsyncMock()),
            "lock_proposal": patch(f"{MOD}._lock_proposal",
                                   AsyncMock(return_value=_proposal())),
            "source": patch(f"{MOD}.owner_answer_source", AsyncMock(return_value=SOURCE)),
            "cards": patch(f"{MOD}.answer_cards", AsyncMock(return_value=list(CARDS))),
            "finish": patch(f"{MOD}._finish_proposal", AsyncMock()),
            "publish": patch(f"{MOD}.publish_cards", AsyncMock(side_effect=self._publish)),
            "fact_count": patch(f"{MOD}.answer_fact_count", AsyncMock(return_value=0)),
            # 이미 공개된 카드가 지금 서빙 가능한가(worker 의 LINKED 확인). 기본은 서빙 불가
            "linked": patch("app.cards.owner_answer_worker._linked_target",
                            AsyncMock(return_value=None)),
        }
        self.m = {name: p.start() for name, p in self.patches.items()}
        self.hook = None

    def tearDown(self):
        for p in self.patches.values():
            p.stop()

    async def _publish(self, pool, **kwargs):
        self.hook = kwargs["in_transaction"]
        self.log.append("publish_cards")
        return self.publish_result

    async def _approve(self, notify_r=None):
        return await ka.approve_owner_proposal(
            self.pool, store_id=STORE, member_id=MEMBER, actor_user_id=ACTOR,
            proposal_id=PROPOSAL, usage_context=_usage(), notify_r=notify_r)

    async def _run_hook(self, *, proposal_status="PENDING_REVIEW"):
        """publish_cards 가 발행 트랜잭션 안에서 hook 을 부르는 것을 흉내 낸다."""
        self.m["lock_proposal"].return_value = _proposal(status=proposal_status)
        conn = FakeConn(self.log)
        async with conn.transaction():
            await self.hook(conn, 5, 12)
        return conn

    # --- 사실 초안 없는 제안 ---
    async def test_legacy_proposal_without_source_raises(self):
        self.m["source"].return_value = None
        with self.assertRaises(ValueError) as caught:
            await self._approve()
        self.assertEqual(str(caught.exception), ka.LEGACY_PROPOSAL_MESSAGE)
        self.assertEqual(self.m["source"].await_args.kwargs, dict(owner_answer_id=ANSWER))
        self.m["cards"].assert_not_awaited()
        self.m["publish"].assert_not_awaited()

    async def test_approve_without_drafts_raises(self):
        self.m["cards"].return_value = [card(9, draft=90, published=90, status="APPROVED")]
        with self.assertRaises(ValueError) as caught:
            await self._approve()
        self.assertEqual(str(caught.exception), ka.NO_DRAFT_MESSAGE)
        self.m["publish"].assert_not_awaited()

    async def test_approve_with_no_answer_cards_raises(self):
        # 사실 0개(NO_FACTS) 제안 — 이어진 카드 자체가 없다
        self.m["cards"].return_value = []
        with self.assertRaises(ValueError) as caught:
            await self._approve()
        self.assertEqual(str(caught.exception), ka.NO_DRAFT_MESSAGE)
        self.m["publish"].assert_not_awaited()

    async def test_approve_with_held_facts_says_held(self):
        # 사실은 있지만 점주가 고치던 초안 때문에 보류(FACTS_PENDING) — 거절 문구가 상황과 맞다
        self.m["cards"].return_value = []
        self.m["fact_count"].return_value = 2
        with self.assertRaises(ValueError) as caught:
            await self._approve()
        self.assertEqual(str(caught.exception), ka.FACTS_HELD_MESSAGE)
        self.m["publish"].assert_not_awaited()

    # --- 카드 화면에서 먼저 공개한 경우(I4) ---
    async def test_already_published_cards_close_proposal_and_notify_r(self):
        self.m["cards"].return_value = [card(9, draft=90, published=90, status="APPROVED"),
                                        card(11, draft=110, published=110, status="APPROVED")]
        self.m["linked"].side_effect = lambda conn, *, store_id, card_id: (
            {9: 90, 11: 110}[card_id], 33)
        calls = []

        async def notify(conn, answer_id, card_id, version_id, revision):
            calls.append((conn.is_in_transaction(), answer_id, card_id, version_id, revision))

        result = await self._approve(notify_r=notify)
        self.assertEqual(result.status, "ALREADY_APPLIED")
        self.m["publish"].assert_not_awaited()
        finish = self.m["finish"].await_args.kwargs
        self.assertEqual((finish["card_id"], finish["version_id"], finish["card_ids"],
                          finish["store_id"]), (9, 90, [9, 11], STORE))
        self.assertEqual(calls, [(True, ANSWER, 9, 90, 33)])
        self.assertEqual([c.kwargs["store_id"] for c in self.m["linked"].await_args_list],
                         [STORE, STORE])
        self.assertIn("tx_commit", self.log)

    async def test_already_published_but_one_not_serving_raises_no_draft(self):
        self.m["cards"].return_value = [card(9, draft=90, published=90, status="APPROVED"),
                                        card(11, draft=110, published=110, status="APPROVED")]
        self.m["linked"].side_effect = lambda conn, *, store_id, card_id: (
            (90, 33) if card_id == 9 else None)
        notify = AsyncMock()
        with self.assertRaises(ValueError) as caught:
            await self._approve(notify_r=notify)
        self.assertEqual(str(caught.exception), ka.NO_DRAFT_MESSAGE)
        self.m["finish"].assert_not_awaited()
        notify.assert_not_awaited()

    # --- 공개 ---
    async def test_approve_publishes_all_answer_drafts_once(self):
        result = await self._approve()
        self.assertEqual(result, self.publish_result)
        self.m["publish"].assert_awaited_once()
        call = self.m["publish"].await_args
        self.assertEqual(call.args, (self.pool,))
        self.assertEqual((call.kwargs["store_id"], call.kwargs["member_id"],
                          call.kwargs["actor_user_id"]), (STORE, MEMBER, ACTOR))
        self.assertEqual(call.kwargs["changes"], [CardChange(5, 50, 50), CardChange(7, 71, 71)])
        self.assertEqual(call.kwargs["idempotency_key"], f"owner-proposal:{PROPOSAL}")
        self.assertEqual(call.kwargs["usage_context"], _usage())
        self.assertEqual(self.m["cards"].await_args.kwargs, dict(source_id=SOURCE))
        # 준비 트랜잭션은 publish_cards 전에 커밋된다(연결을 잡지 않는다)
        self.assertLess(self.log.index("tx_commit"), self.log.index("publish_cards"))
        await self._run_hook()
        finish = self.m["finish"].await_args.kwargs
        self.assertEqual((finish["store_id"], finish["card_id"], finish["version_id"]),
                         (STORE, 5, 50))
        # 공개 hook 이 비운 검수 사유를 다시 확인할 카드 — 이번에 공개한 카드 전부
        self.assertEqual(list(finish["card_ids"]), [5, 7])
        self.assertEqual(finish["proposal"]["proposal_id"], PROPOSAL)

    async def test_supplement_proposal_publishes_the_same_way(self):
        # relation 이 SUPPLEMENT 여도 대상 카드에 판을 새로 만들지 않는다 — 사실 초안을 공개할 뿐
        self.m["lock_proposal"].return_value = _proposal("SUPPLEMENT")
        await self._approve()
        self.assertEqual(self.m["publish"].await_args.kwargs["changes"],
                         [CardChange(5, 50, 50), CardChange(7, 71, 71)])
        self.assertFalse(hasattr(ka, "_stage_proposal_card"))

    # --- 상태 ---
    async def test_unapprovable_status_raises(self):
        for status in ("LINKED", "DISMISSED"):
            self.m["lock_proposal"].return_value = _proposal(status=status)
            with self.assertRaises(ValueError):
                await self._approve()
        self.m["publish"].assert_not_awaited()

    async def test_already_published_proposal_is_already_applied(self):
        self.m["lock_proposal"].return_value = _proposal(
            status="PUBLISHED", result_card=90, result_version=900)
        result = await self._approve()
        self.assertEqual(result.status, "ALREADY_APPLIED")
        self.m["publish"].assert_not_awaited()
        self.m["source"].assert_not_awaited()

    async def test_published_without_result_ids_is_rejected(self):
        self.m["lock_proposal"].return_value = _proposal(status="PUBLISHED")
        with self.assertRaises(ValueError):
            await self._approve()
        self.m["publish"].assert_not_awaited()

    async def test_missing_proposal_raises_lookup(self):
        self.m["lock_proposal"].return_value = None
        with self.assertRaises(LookupError):
            await self._approve()

    async def test_failed_publish_leaves_proposal_untouched(self):
        for status in ("NO_PROVENANCE", "STALE", "PREPARE_FAILED"):
            self.publish_result = PublishCardsResult(status=status)
            result = await self._approve()
            self.assertEqual(result.status, status)
        self.m["finish"].assert_not_awaited()

    # --- hook ---
    async def test_hook_marks_published_and_notifies_r_in_tx(self):
        seen = []

        async def notify(conn, owner_answer_id, card_id, card_version_id, revision):
            seen.append((owner_answer_id, card_id, card_version_id, revision,
                         conn.is_in_transaction()))

        await self._approve(notify_r=notify)
        await self._run_hook()
        self.assertEqual(seen, [(ANSWER, 5, 50, 12, True)])
        # 옛 색인(card_embeddings) 호환 쓰기는 제거했다
        self.assertFalse(hasattr(ka, "embed_card"))
        self.assertFalse(hasattr(ka, "prepare_embedding"))

    async def test_hook_rejects_proposal_changed_meanwhile(self):
        notify = AsyncMock()
        await self._approve(notify_r=notify)
        with self.assertRaises(ValueError):
            await self._run_hook(proposal_status="PUBLISHED")
        self.assertIn("tx_rollback", self.log)
        notify.assert_not_awaited()
        self.m["finish"].assert_not_awaited()

    async def test_hook_without_notifier_logs_warning(self):
        await self._approve(notify_r=None)
        with self.assertLogs(MOD, level="WARNING") as logs:
            await self._run_hook()
        self.assertTrue(any("R 완료 접점 미연결" in line for line in logs.output))
        self.m["finish"].assert_awaited_once()


class FinishProposalSqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_reason_rechecked_for_every_published_card(self):
        """publish_cards 가 공개하며 비운 검수 사유를 공개한 카드마다 다시 표시한다."""

        class Db:
            def __init__(self):
                self.calls = []

            async def execute(self, sql, *args):
                self.calls.append((sql, args))

        db = Db()
        with patch(f"{MOD}._attach_owner_answer_citations", AsyncMock()):
            await ka._finish_proposal(db, store_id=STORE, proposal=_proposal(), card_id=5,
                                      version_id=50, card_ids=[5, 7])
        reflag = [args for sql, args in db.calls if "needs_review_reason" in sql]
        self.assertEqual(reflag, [(STORE, 5), (STORE, 7)])


if __name__ == "__main__":
    unittest.main()
