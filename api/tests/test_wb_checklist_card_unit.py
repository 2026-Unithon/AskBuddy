"""Phase B B-D9 — 체크 항목 = 카드 하나(제목). 본문 줄 수와 무관하다."""
import unittest
from datetime import date, datetime, timezone

from app.checklist import repository as repo
from app.checklist.scope import build_today, line_keys

STORE = 3


class FakeDb:
    def __init__(self, rows, sub=None):
        self.rows, self.sub, self.sql = rows, sub, []

    async def fetch(self, sql, *args):
        assert args[0] == STORE
        self.sql.append(sql)
        return self.rows

    async def fetchrow(self, sql, *args):
        assert args[0] == STORE
        return self.sub


def _card_row(card_id, title, content, **extra):
    return {"card_id": card_id, "card_version_id": card_id * 10, "title": title,
            "content": content, "common": True, "shift_ids": [], **extra}


class LoadCardsTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_card_is_one_item_titled(self):
        cards = await repo.load_cards(FakeDb([_card_row(1, "마감 청소", "의자 올리기\n바닥 닦기\n쓰레기"),
                                              _card_row(2, "오픈 준비", "")]), STORE)
        self.assertEqual([(c.card_id, c.lines) for c in cards],
                         [(1, ("마감 청소",)), (2, ("오픈 준비",))])  # 본문이 비어도 뜬다
        self.assertEqual(line_keys(cards), {(10, 1), (20, 1)})

    async def test_blank_title_card_is_skipped(self):
        cards = await repo.load_cards(FakeDb([_card_row(1, "  ", "본문")]), STORE)
        self.assertEqual(cards, [])

    async def test_item_id_for_detail_link_is_carried(self):
        cards = await repo.load_cards(FakeDb([_card_row(1, "마감 청소", "a", item_id=55),
                                              _card_row(2, "오픈 준비", "b")]), STORE)
        self.assertEqual([c.item_id for c in cards], [55, None])


class RecordDayTest(unittest.IsolatedAsyncioTestCase):
    async def test_record_line_text_is_card_title(self):
        at = datetime(2026, 10, 11, 9, tzinfo=timezone.utc)
        rows = [{"card_version_id": 10, "line_no": 1, "created_at": at, "title": "마감 청소",
                 "content": "의자 올리기\n바닥 닦기"},
                {"card_version_id": 20, "line_no": 2, "created_at": at, "title": "옛 줄 체크",
                 "content": "a\nb"}]
        out = await repo.record_day(FakeDb(rows), STORE, 7, date(2026, 10, 11))
        # 예전 줄 단위 체크(line_no 2)는 카드 단위에서 보이지 않는다
        self.assertEqual([(l["title"], l["text"]) for l in out["lines"]], [("마감 청소", "마감 청소")])


class TodayCountTest(unittest.TestCase):
    def test_remaining_is_card_count(self):
        from app.checklist.scope import ChecklistCard, Scope
        cards = [ChecklistCard(1, 10, "마감 청소", ("마감 청소",), True, frozenset()),
                 ChecklistCard(2, 20, "오픈 준비", ("오픈 준비",), True, frozenset())]
        out = build_today(business_date=date(2026, 10, 11), previous_business_date=date(2026, 10, 10),
                          previous_submitted=True, shifts=[], cards=cards, scope=Scope(True, ()),
                          checked={(10, 1)}, selected_shift_id=None, upcoming=False,
                          include_all=False, submissions=[], my_submission=None)
        self.assertEqual(out["scope_counts"], {"total": 2, "done": 1})
        self.assertEqual(out["groups"][0]["cards"][0]["item_id"], None)
