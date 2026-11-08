"""검수 '그 자리 글 입력칸'(2026-11-08). 근거를 확인할 수 없는 사실은 사장님이 고쳐 적어 근거를 만든다."""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.cards import router as cards_router
from app.cards.fact_edit_schemas import CardFactsView, EditKeep, EditModify, FactBlockView, FactOrigin, FactRow, ReviewWriteRequest
from app.cards.review_items import write_items

CLAIMS = {"user_id": 9, "store_id": 1, "role": "OWNER"}


def row(fact_id, sentence, origins=True, value=None):
    o = [FactOrigin(kind="SOURCE", source_id=1, source_title="메모", source_type="SCAN", source_availability="AVAILABLE", locator_type="PAGE")] if origins else []
    return FactRow(fact_revision_id=fact_id * 10, fact_id=fact_id, position=fact_id, sentence=sentence, assertion=sentence,
                   polarity="AFFIRM", origins=o, value=value)


def view(*rows):
    return CardFactsView(card_id=5, version_id=50, title="합성", review_status="NEEDS_REVIEW", editable=True,
                         blocks=[FactBlockView(block_id="b1", kind="NOTES", order=1, facts=list(rows))])


class WriteItemsTest(unittest.TestCase):
    def test_fact_without_source_gets_a_write_item(self):
        items = write_items(view(row(1, "컵은 20이에요."), row(2, "얼음은 가득 담아요.", origins=False)))
        self.assertEqual([(i.kind, i.fact_revision_id, i.text) for i in items], [("WRITE", 20, "얼음은 가득 담아요.")])


class Db:
    @asynccontextmanager
    async def transaction(self):
        yield


class WriteRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_write_modifies_only_that_fact(self):
        save = AsyncMock(return_value="SAVED")
        with patch("app.cards.router.get_card_facts", new=AsyncMock(return_value=view(row(1, "컵은 20이에요."), row(2, "얼음 가득", origins=False)))), \
             patch("app.cards.router.fact_edit.save_fact_edit", new=save):
            result = await cards_router.write_review_value(5, ReviewWriteRequest(
                fact_revision_id=20, text="얼음은 컵에 가득 담아요.", expected_version_id=50, idempotency_key="write-20-a"), Db(), CLAIMS)
        self.assertEqual(result, "SAVED")
        items = save.await_args.kwargs["req"].blocks[0].items
        self.assertEqual(items[0], EditKeep(op="KEEP", fact_revision_id=10))
        self.assertIsInstance(items[1], EditModify)
        self.assertEqual((items[1].fact_revision_id, items[1].fact.sentence), (20, "얼음은 컵에 가득 담아요."))

    async def test_write_unknown_fact_is_404(self):
        with patch("app.cards.router.get_card_facts", new=AsyncMock(return_value=view(row(1, "컵")))):
            with self.assertRaises(cards_router.ApiError) as raised:
                await cards_router.write_review_value(5, ReviewWriteRequest(
                    fact_revision_id=99, text="x", expected_version_id=50, idempotency_key="write-99-a"), Db(), CLAIMS)
        self.assertEqual(raised.exception.status_code, 404)
