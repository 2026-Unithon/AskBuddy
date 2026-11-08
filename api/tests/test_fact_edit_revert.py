"""계획 7 Task 7: 수정 되돌리기. 직전 판 사실로 지금 카드에 대한 편집 요청을 만든다(판은 지우지 않는다)."""
import unittest

from app.cards.fact_edit_revert import plan_revert
from app.cards.fact_edit_schemas import CardFactsView, EditAdd, EditKeep, EditModify, FactBlockView, FactRow


def r(fact_id, rev, sentence, **kw):
    return FactRow(fact_revision_id=rev, fact_id=fact_id, position=rev, sentence=sentence, assertion=sentence, polarity="AFFIRM", **kw)


def view(version, *blocks):
    return CardFactsView(card_id=1, version_id=version, title="합성", review_status="PENDING", editable=True,
                         blocks=[FactBlockView(block_id=f"b{i}", kind=k, order=i, facts=list(rows)) for i, (k, rows) in enumerate(blocks)])


class PlanRevertTest(unittest.TestCase):
    def test_modified_fact_goes_back_to_old_fields(self):
        old = view(10, ("QUANTITIES", [r(1, 11, "시럽=2펌프", value="2", unit="펌프"), r(2, 21, "컵=20")]))
        cur = view(12, ("QUANTITIES", [r(1, 12, "시럽=3펌프", value="3", unit="펌프"), r(2, 21, "컵=20")]))
        req = plan_revert(old, cur, idempotency_key="revert-1-12")
        items = req.blocks[0].items
        self.assertIsInstance(items[0], EditModify)
        self.assertEqual((items[0].fact_revision_id, items[0].fact.sentence, items[0].fact.value), (12, "시럽=2펌프", "2"))
        self.assertEqual(items[1], EditKeep(op="KEEP", fact_revision_id=21))
        self.assertEqual((req.expected_version_id, req.deleted_fact_revision_ids), (12, []))

    def test_added_fact_is_deleted_and_removed_fact_comes_back(self):
        old = view(10, ("NOTES", [r(1, 11, "휘핑 없음"), r(3, 31, "얼음 가득")]))
        cur = view(12, ("NOTES", [r(1, 11, "휘핑 없음"), r(4, 41, "새 줄")]))
        req = plan_revert(old, cur, idempotency_key="revert-1-12")
        self.assertEqual(req.deleted_fact_revision_ids, [41])
        items = req.blocks[0].items
        self.assertEqual(items[0], EditKeep(op="KEEP", fact_revision_id=11))
        self.assertIsInstance(items[1], EditAdd)
        self.assertEqual(items[1].fact.sentence, "얼음 가득")

    def test_old_block_order_is_restored(self):
        old = view(10, ("STEPS", [r(1, 11, "샷", step_order=1), r(2, 21, "우유", step_order=2)]))
        cur = view(12, ("STEPS", [r(2, 21, "우유", step_order=1), r(1, 11, "샷", step_order=2)]))
        req = plan_revert(old, cur, idempotency_key="revert-1-12")
        self.assertEqual([i.fact_revision_id for i in req.blocks[0].items], [11, 21])


from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.cards import router as cards_router
from app.cards.fact_edit_schemas import RevertRequest

MOD = "app.cards.router"
CLAIMS = {"user_id": 9, "store_id": 1, "role": "OWNER"}


class Db:
    def __init__(self, edit, draft):
        self.edit, self.draft = edit, draft

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, query, *args):
        assert args[0] == 1
        return self.edit

    async def fetchval(self, query, *args):
        return self.draft


class RevertRouteTest(unittest.IsolatedAsyncioTestCase):
    def edit(self, minutes_ago=0):
        return {"from_version_id": 10, "to_version_id": 12, "created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)}

    async def test_revert_saves_planned_edit(self):
        old = view(10, ("NOTES", [r(1, 11, "휘핑 없음")]))
        cur = view(12, ("NOTES", [r(1, 12, "휘핑 올림")]))
        save = AsyncMock(return_value="SAVED")
        with patch(f"{MOD}._facts_view_at", new=AsyncMock(return_value=old)), \
             patch(f"{MOD}.get_card_facts", new=AsyncMock(return_value=cur)), \
             patch(f"{MOD}.fact_edit.save_fact_edit", new=save):
            result = await cards_router.revert_fact_edit(1, 77, RevertRequest(idempotency_key="revert-77-a"), Db(self.edit(), 12), CLAIMS)
        self.assertEqual(result, "SAVED")
        self.assertEqual(save.await_args.kwargs["req"].blocks[0].items[0].fact.sentence, "휘핑 없음")

    async def test_revert_refuses_stale_expired_or_missing(self):
        cases = ((self.edit(), 13, 409, "REVERT_STALE"), (self.edit(minutes_ago=11), 12, 409, "REVERT_EXPIRED"), (None, 12, 404, "EDIT_NOT_FOUND"))
        for edit, draft, status, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(cards_router.ApiError) as raised:
                    await cards_router.revert_fact_edit(1, 77, RevertRequest(idempotency_key="revert-77-a"), Db(edit, draft), CLAIMS)
                self.assertEqual((raised.exception.status_code, raised.exception.code), (status, code))
