"""검수 대기 점주 답변 제안의 나중 승인 `approve_owner_proposal` (W, Task 6).

DB 보조 함수·publish_cards·임베딩은 patch 한다. 여기서 보는 것은
  - NEW/SUPPLEMENT 가 어떤 카드 변경으로 publish_cards 를 부르는가
  - hook 이 제안을 다시 확인하고 R 완료 접점(notify_r)을 같은 트랜잭션에서 부르는가
  - notify_r 이 없으면 경고를 남기는가, 승인 불가 상태는 ValueError 인가
실제 DB 는 Task 7 통합 스크립트가 돈다.
"""
from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.config import get_settings
from app.contracts.usage import UsageContext
from app.learn import knowledge_apply as ka
from app.publish.approval import CardChange, PublishCardsResult

STORE = 7
MEMBER = 2
ACTOR = 20
PROPOSAL = 70
ANSWER = 501
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


def _proposal(relation="NEW", status="PENDING_REVIEW", target=None, target_version=None,
              result_card=None, result_version=None):
    return dict(proposal_id=PROPOSAL, answer_id=ANSWER, relation_type=relation,
                status=status, target_card_id=target,
                target_version_id=(400 if target and target_version is None else target_version),
                category_id=3, proposed_title="제목", proposed_content="내용",
                result_card_id=result_card, result_version_id=result_version)


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
            "answer_card": patch(f"{MOD}._owner_answer_draft", AsyncMock(return_value=None)),
            "create": patch(f"{MOD}.create_owner_answer_card",
                            AsyncMock(return_value=(90, 900))),
            "target": patch(f"{MOD}._lock_target_card", AsyncMock(
                return_value=dict(card_id=40, draft_version_id=400,
                                  published_version_id=400, review_status="APPROVED"))),
            "create_draft": patch(f"{MOD}.card_repo.create_draft",
                                  AsyncMock(return_value=401)),
            "mark_source": patch(f"{MOD}._mark_owner_answer_version", AsyncMock()),
            "version": patch(f"{MOD}._read_version", AsyncMock(return_value=None)),
            "resolve": patch(f"{MOD}.resolve_owner_answer_category",
                             AsyncMock(return_value=8)),
            "set_category": patch(f"{MOD}._set_proposal_category", AsyncMock()),
            "prepare": patch(f"{MOD}.prepare_embedding", AsyncMock(return_value="PREP")),
            "embed": patch(f"{MOD}.embed_card", AsyncMock(return_value=1)),
            "finish": patch(f"{MOD}._finish_proposal", AsyncMock()),
            "publish": patch(f"{MOD}.publish_cards", AsyncMock(
                side_effect=self._publish)),
            # 점주 답변 출처 공개가 켜진 경우가 기본. 꺼진 경우는 따로 본다
            "flag": patch.object(get_settings(), "w_owner_answer_raw_publish", True),
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
        self.m["lock_proposal"].return_value = _proposal(
            relation=self.m["lock_proposal"].return_value["relation_type"],
            status=proposal_status,
            target=self.m["lock_proposal"].return_value["target_card_id"])
        conn = FakeConn(self.log)
        async with conn.transaction():
            await self.hook(conn, 5, 12)
        return conn

    # --- NEW ---
    async def test_new_creates_card_and_publishes_its_draft(self):
        result = await self._approve()
        self.assertEqual(result, self.publish_result)
        self.m["create"].assert_awaited_once()
        kwargs = self.m["create"].await_args.kwargs
        self.assertEqual((kwargs["store_id"], kwargs["answer_id"], kwargs["actor_id"],
                          kwargs["title"], kwargs["content"], kwargs["category_id"]),
                         (STORE, ANSWER, ACTOR, "제목", "내용", 8))
        # 레거시처럼 실제로 쓴 카테고리를 제안에 되써 둔다
        self.m["resolve"].assert_awaited_once()
        self.assertEqual(self.m["resolve"].await_args.kwargs,
                         dict(store_id=STORE, category_id=3))
        self.assertEqual(self.m["set_category"].await_args.kwargs,
                         dict(store_id=STORE, proposal_id=PROPOSAL, category_id=8))
        call = self.m["publish"].await_args
        self.assertEqual(call.args, (self.pool,))
        self.assertEqual(call.kwargs["store_id"], STORE)
        self.assertEqual(call.kwargs["member_id"], MEMBER)
        self.assertEqual(call.kwargs["actor_user_id"], ACTOR)
        self.assertEqual(call.kwargs["changes"], [CardChange(90, 900, 900)])
        self.assertEqual(call.kwargs["idempotency_key"], f"owner-proposal:{PROPOSAL}")
        self.assertEqual(call.kwargs["usage_context"], _usage())
        # 카드 생성 트랜잭션은 publish_cards 전에 커밋된다(연결을 잡지 않는다)
        self.assertLess(self.log.index("tx_commit"), self.log.index("publish_cards"))
        self.m["target"].assert_not_awaited()

    async def test_new_reuses_worker_draft_card(self):
        # worker 가 REVIEW 로 떨어뜨리며 남긴 초안 카드를 다시 만들지 않는다
        self.m["answer_card"].return_value = dict(card_id=91, draft_version_id=910,
                                                  review_status="NEEDS_REVIEW")
        await self._approve()
        self.m["create"].assert_not_awaited()
        self.assertEqual(self.m["publish"].await_args.kwargs["changes"],
                         [CardChange(91, 910, 910)])

    async def test_new_reused_card_excluded_is_rejected(self):
        self.m["answer_card"].return_value = dict(card_id=91, draft_version_id=910,
                                                  review_status="EXCLUDED")
        with self.assertRaises(ValueError):
            await self._approve()
        self.m["publish"].assert_not_awaited()

    # --- SUPPLEMENT / CONFLICT ---
    async def test_supplement_creates_owner_answer_draft_on_target(self):
        self.m["lock_proposal"].return_value = _proposal("SUPPLEMENT", target=40)
        await self._approve()
        self.m["create"].assert_not_awaited()
        self.m["create_draft"].assert_awaited_once()
        call = self.m["create_draft"].await_args
        self.assertEqual(call.args[1:], (STORE, 40))
        self.assertEqual(call.kwargs, dict(title="제목", content="내용", actor_id=ACTOR,
                                           source_version_id=400))
        mark = self.m["mark_source"].await_args.kwargs
        self.assertEqual(mark, dict(store_id=STORE, version_id=401, answer_id=ANSWER))
        self.assertEqual(self.m["publish"].await_args.kwargs["changes"],
                         [CardChange(40, 401, 401)])

    async def test_conflict_target_excluded_or_missing_is_rejected(self):
        self.m["lock_proposal"].return_value = _proposal("CONFLICT", target=40)
        for card in (None, dict(card_id=40, draft_version_id=400,
                                published_version_id=400, review_status="EXCLUDED")):
            self.m["target"].return_value = card
            with self.assertRaises(ValueError):
                await self._approve()
        self.m["create_draft"].assert_not_awaited()
        self.m["publish"].assert_not_awaited()

    # --- 상태 ---
    async def test_unapprovable_status_raises(self):
        for status in ("LINKED", "DISMISSED"):
            self.m["lock_proposal"].return_value = _proposal(status=status)
            with self.assertRaises(ValueError):
                await self._approve()
        self.m["publish"].assert_not_awaited()

    async def test_published_proposal_replay_is_already_applied(self):
        self.m["lock_proposal"].return_value = _proposal(
            status="PUBLISHED", result_card=90, result_version=900)
        result = await self._approve()
        self.assertEqual(result.status, "ALREADY_APPLIED")
        self.m["publish"].assert_not_awaited()
        self.m["create"].assert_not_awaited()
        self.m["prepare"].assert_not_awaited()

    async def test_published_without_result_ids_is_rejected(self):
        self.m["lock_proposal"].return_value = _proposal(status="PUBLISHED")
        with self.assertRaises(ValueError):
            await self._approve()
        self.m["publish"].assert_not_awaited()

    # --- SUPPLEMENT 낡은 기준 방어 ---
    async def test_supplement_stale_target_version_is_rejected(self):
        # 제안을 만든 뒤 대상 카드가 새 판으로 공개됐다. 옛 기준 답으로 되돌리지 않는다
        self.m["lock_proposal"].return_value = _proposal("SUPPLEMENT", target=40,
                                                         target_version=399)
        with self.assertRaises(ValueError):
            await self._approve()
        self.m["create_draft"].assert_not_awaited()
        self.m["publish"].assert_not_awaited()

    async def test_supplement_foreign_unpublished_draft_is_rejected(self):
        # 점주가 고친 미공개 초안을 덮지 않는다
        self.m["lock_proposal"].return_value = _proposal("SUPPLEMENT", target=40)
        self.m["target"].return_value = dict(card_id=40, draft_version_id=405,
                                             published_version_id=400,
                                             review_status="APPROVED")
        self.m["version"].return_value = dict(change_source="OWNER_EDIT", title="제목",
                                              content="내용", owner_answer_id=None)
        with self.assertRaises(ValueError):
            await self._approve()
        self.m["create_draft"].assert_not_awaited()
        self.m["publish"].assert_not_awaited()

    async def test_supplement_retry_reuses_staged_draft(self):
        # 앞선 시도(STALE 등)가 얹어 둔 이 제안의 초안을 재사용한다
        self.m["lock_proposal"].return_value = _proposal("CONFLICT", target=40)
        self.m["target"].return_value = dict(card_id=40, draft_version_id=401,
                                             published_version_id=400,
                                             review_status="APPROVED")
        self.m["version"].return_value = dict(change_source="OWNER_ANSWER", title="제목",
                                              content="내용", owner_answer_id=ANSWER)
        await self._approve()
        self.m["create_draft"].assert_not_awaited()
        self.m["mark_source"].assert_not_awaited()
        self.assertEqual(self.m["publish"].await_args.kwargs["changes"],
                         [CardChange(40, 401, 401)])

    async def test_supplement_draft_of_other_answer_is_rejected(self):
        self.m["lock_proposal"].return_value = _proposal("SUPPLEMENT", target=40)
        self.m["target"].return_value = dict(card_id=40, draft_version_id=401,
                                             published_version_id=400,
                                             review_status="APPROVED")
        self.m["version"].return_value = dict(change_source="OWNER_ANSWER", title="제목",
                                              content="내용", owner_answer_id=ANSWER + 1)
        with self.assertRaises(ValueError):
            await self._approve()

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

    async def test_flag_off_returns_no_provenance_without_staging(self):
        """플래그가 꺼져 있으면 초안을 커밋하지 않는다. 예전에는 초안을 먼저 커밋한 뒤
        publish_cards 가 NO_PROVENANCE 를 돌려줘, 공개할 수 없는 점주 답변 판이 대상
        카드에 남았다(Task 7 실제 DB 검증에서 발견)."""
        for relation, target in (("NEW", None), ("SUPPLEMENT", 40), ("CONFLICT", 40)):
            self.m["lock_proposal"].return_value = _proposal(relation, target=target)
            with patch.object(get_settings(), "w_owner_answer_raw_publish", False):
                result = await self._approve()
            self.assertEqual(result.status, "NO_PROVENANCE")
        for name in ("create", "create_draft", "mark_source", "set_category", "target",
                     "prepare", "publish"):
            self.m[name].assert_not_awaited()

    async def test_flag_off_still_replays_published_proposal(self):
        self.m["lock_proposal"].return_value = _proposal(
            status="PUBLISHED", result_card=90, result_version=900)
        with patch.object(get_settings(), "w_owner_answer_raw_publish", False):
            result = await self._approve()
        self.assertEqual(result.status, "ALREADY_APPLIED")

    # --- hook ---
    async def test_hook_marks_published_and_notifies_r_in_tx(self):
        seen = []

        async def notify(conn, owner_answer_id, card_id, card_version_id, revision):
            seen.append((owner_answer_id, card_id, card_version_id, revision,
                         conn.is_in_transaction()))

        await self._approve(notify_r=notify)
        await self._run_hook()
        self.assertEqual(seen, [(ANSWER, 90, 900, 12, True)])
        finish = self.m["finish"].await_args.kwargs
        self.assertEqual((finish["store_id"], finish["card_id"], finish["version_id"]),
                         (STORE, 90, 900))
        self.assertEqual(finish["proposal"]["proposal_id"], PROPOSAL)
        # 옛 색인 호환 쓰기는 hook 안에서, 준비는 hook 밖에서
        self.m["embed"].assert_awaited_once()
        self.assertEqual(self.m["embed"].await_args.args[1:], (STORE, 90))
        self.assertEqual(self.m["embed"].await_args.kwargs, dict(prepared="PREP"))
        self.m["prepare"].assert_awaited_once()

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


if __name__ == "__main__":
    unittest.main()
