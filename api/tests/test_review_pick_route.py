"""계획 7 Task 6: 검수 고르기. 카드 응답의 골라야 할 항목, 고른 뒤 틀린 값을 카드에서 빼는 편집."""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.cards import router as cards_router
from app.cards.fact_edit_schemas import CardFactsView, FactBlockView, FactRow, ReviewChooseRequest
from app.cards.review_items import review_item_from_conflict

MOD = "app.cards.router"
STORE, USER = 1, 9


def row(fact_id, rev, sentence):
    return FactRow(fact_revision_id=rev, fact_id=fact_id, position=fact_id, sentence=sentence, assertion=sentence, polarity="AFFIRM")


class ReviewItemTest(unittest.TestCase):
    def test_label_and_values_from_table_cells(self):
        item = review_item_from_conflict(7, 11, "토핑=일반휘핑(30g)", 12, "토핑=일반휘핑(90g)")
        self.assertEqual((item.item_id, item.kind, item.conflict_id, item.label), ("conflict-7", "CHOOSE", 7, "토핑"))
        self.assertEqual([(o.fact_id, o.text) for o in item.options], [(11, "일반휘핑(30g)"), (12, "일반휘핑(90g)")])

    def test_sentence_without_name_is_shown_whole(self):
        item = review_item_from_conflict(8, 21, "그룹헤드 역세척 3회", 22, "그룹헤드 역세척 5회")
        self.assertIsNone(item.label)
        self.assertEqual([o.text for o in item.options], ["그룹헤드 역세척 3회", "그룹헤드 역세척 5회"])


class Db:
    @asynccontextmanager
    async def transaction(self):
        yield


class ChooseRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_choose_removes_rejected_fact_from_card(self):
        view = CardFactsView(card_id=5, version_id=50, title="합성", review_status="NEEDS_REVIEW", editable=True, blocks=[
            FactBlockView(block_id="b1", kind="QUANTITIES", order=1, facts=[row(11, 110, "토핑=30g"), row(12, 120, "토핑=90g"), row(13, 130, "컵=20")])])
        save = AsyncMock(return_value="SAVED")
        with patch(f"{MOD}.fact_revisions.choose_conflict", new=AsyncMock(return_value=12)) as choose, \
             patch(f"{MOD}.get_card_facts", new=AsyncMock(return_value=view)), \
             patch(f"{MOD}.fact_edit.save_fact_edit", new=save):
            result = await cards_router.choose_review_value(
                5, 7, ReviewChooseRequest(keep_fact_id=11, expected_version_id=50, idempotency_key="pick-7-11"), Db(),
                {"user_id": USER, "store_id": STORE, "role": "OWNER"})
        self.assertEqual(result, "SAVED")
        choose.assert_awaited_once()
        req = save.await_args.kwargs["req"]
        self.assertEqual(req.deleted_fact_revision_ids, [120])
        self.assertEqual([i.fact_revision_id for b in req.blocks for i in b.items], [110, 130])
        self.assertEqual(req.expected_version_id, 50)

    async def test_choose_errors_map_to_http(self):
        for error, status in ((LookupError("x"), 404), (ValueError("x"), 409)):
            with self.subTest(status=status), \
                 patch(f"{MOD}.fact_revisions.choose_conflict", new=AsyncMock(side_effect=error)), \
                 patch(f"{MOD}.get_card_facts", new=AsyncMock()):
                with self.assertRaises(cards_router.ApiError) as raised:
                    await cards_router.choose_review_value(
                        5, 7, ReviewChooseRequest(keep_fact_id=11, expected_version_id=50, idempotency_key="pick-7-11"), Db(),
                        {"user_id": USER, "store_id": STORE, "role": "OWNER"})
                self.assertEqual(raised.exception.status_code, status)
