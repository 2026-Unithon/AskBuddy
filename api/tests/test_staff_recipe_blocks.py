"""계획 7 Task 12: 직원 레시피도 한눈에 보기. 공개 판 사실 묶음을 레시피 응답에 싣는다."""
import unittest
from unittest.mock import AsyncMock, patch

from app.cards.fact_edit_schemas import CardFactsView, FactBlockView, FactRow, FactVariant, LineView
from app.learn.recipe_blocks import blocks_for_staff
from app.learn import router as learn_router


def row(fact_id, sentence, step=None):
    return FactRow(fact_revision_id=fact_id * 10, fact_id=fact_id, position=fact_id, sentence=sentence, assertion=sentence,
                   polarity="AFFIRM", step_order=step)


class BlocksForStaffTest(unittest.TestCase):
    def test_only_heading_lines_variant_leave_the_server(self):
        # 계획 10(D23): 직원도 사장님과 같은 보기(구역 제목·줄). 근거 판 id·사실 칸은 내보내지 않는다
        view = CardFactsView(card_id=1, version_id=10, title="합성", review_status="APPROVED", editable=True, blocks=[
            FactBlockView(block_id="b1", kind="QUANTITIES", order=1, variant=FactVariant(temperature="ICE"), facts=[row(1, "컵=20")],
                          heading="ICE", lines=[LineView(line_no=1, text="컵 20", fact_revision_ids=[10])]),
            FactBlockView(block_id="b2", kind="STEPS", order=2, facts=[row(2, "제조순서=컵 → 재료", 1)],
                          lines=[LineView(line_no=1, text="컵", fact_revision_ids=[20]), LineView(line_no=2, text="재료", fact_revision_ids=[20])])])
        self.assertEqual(blocks_for_staff(view), [
            {"kind": "QUANTITIES", "variant": {"temperature": "ICE", "size": None}, "heading": "ICE",
             "lines": [{"line_no": 1, "text": "컵 20", "price": None}]},
            {"kind": "STEPS", "variant": {"temperature": None, "size": None}, "heading": None,
             "lines": [{"line_no": 1, "text": "컵", "price": None}, {"line_no": 2, "text": "재료", "price": None}]}])


    def test_price_line_carries_price(self):
        # 2026-11-18: 금액은 제목 옆에. 단위 칸이 원인 수치 사실만 인용한 줄에 금액 글을 붙인다(화면은 사장님과 같은 lib/card-price)
        price = row(1, "금액=2000원").model_copy(update={"value": "2000", "unit": "원"})
        water = row(2, "물=120ml").model_copy(update={"value": "120", "unit": "ml"})
        view = CardFactsView(card_id=1, version_id=10, title="합성", review_status="APPROVED", editable=True, blocks=[
            FactBlockView(block_id="b1", kind="NOTES", order=1, facts=[price, water], lines=[
                LineView(line_no=1, text="금액 2,000원", fact_revision_ids=[10]),
                LineView(line_no=2, text="물 120ml", fact_revision_ids=[20]),
                LineView(line_no=3, text="물 120ml 금액 2,000원", fact_revision_ids=[10, 20])])])
        lines = blocks_for_staff(view)[0]["lines"]
        self.assertEqual([line["price"] for line in lines], ["2,000원", None, None])


class RoadmapItemTest(unittest.IsolatedAsyncioTestCase):
    async def test_item_carries_fact_blocks(self):
        item = {"published_version_id": 10, "card_id": 1, "title": "합성", "content": "본문", "progress_status": None,
                "completed_version_id": None, "category_id": 3, "category_name": "음료"}
        blocks = [{"kind": "STEPS", "variant": {"temperature": None, "size": None}, "facts": []}]
        with patch("app.learn.router._member_id", new=AsyncMock(return_value=5)), \
             patch("app.learn.router.roadmap_repo.item_row", new=AsyncMock(return_value=item)), \
             patch("app.learn.router._evidence_items", new=AsyncMock(return_value=[])), \
             patch("app.learn.router.published_fact_blocks", new=AsyncMock(return_value=blocks)) as load:
            result = await learn_router.get_roadmap_item(7, "DB", 1, 9)
        load.assert_awaited_once_with("DB", 1, 1, 10)
        self.assertEqual(result.fact_blocks, blocks)
