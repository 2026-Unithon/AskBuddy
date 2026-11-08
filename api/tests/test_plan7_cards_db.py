"""계획 7 카드 상태 변경을 실제 스키마에서 돌린다(검수 기록 제약 포함). PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.cards.router import bulk_cards, unpublish_card
from app.cards.schemas import BulkRequest


async def card(conn, store, status, published=None):
    card_id = await conn.fetchval(
        "insert into knowledge_cards (store_id, title, content, review_status) values ($1, '합성', '합성', $2) returning card_id",
        store, status)
    if published:
        await conn.execute("update knowledge_cards set published_version_id = draft_version_id where card_id = $1", card_id)
    return card_id


@unittest.skipUnless(ENABLED, SKIP_REASON)
class CardsDbTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.claims = {"user_id": 1, "store_id": self.store, "role": "OWNER"}

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_unpublish_needs_review_writes_event(self):
        card_id = await card(self.conn, self.store, "NEEDS_REVIEW")
        result = await unpublish_card(card_id, self.conn, self.claims)
        self.assertEqual(result.review_status, "PENDING")
        event = await self.conn.fetchrow(
            "select action, from_status, to_status from card_review_events where store_id = $1 and card_id = $2", self.store, card_id)
        self.assertEqual(tuple(event), ("UNPUBLISH", "NEEDS_REVIEW", "PENDING"))

    async def test_bulk_exclude_and_move_on_real_schema(self):
        a, b = await card(self.conn, self.store, "PENDING"), await card(self.conn, self.store, "PENDING")
        category = await self.conn.fetchval(
            "insert into task_categories (store_id, category_name) values ($1, '오픈 마감') returning category_id", self.store)
        moved = await bulk_cards(BulkRequest(action="move", card_ids=[a, b], category_id=category), self.conn, self.claims)
        self.assertTrue(all(r.ok for r in moved.results), moved)
        rows = await self.conn.fetch("select category_id, assignment_type from knowledge_cards where store_id = $1 order by card_id", self.store)
        self.assertEqual({(r["category_id"], r["assignment_type"]) for r in rows}, {(category, "MANUAL")})
        excluded = await bulk_cards(BulkRequest(action="exclude", card_ids=[a, b]), self.conn, self.claims)
        self.assertTrue(all(r.ok for r in excluded.results), excluded)
        self.assertEqual({r["review_status"] for r in await self.conn.fetch(
            "select review_status from knowledge_cards where store_id = $1", self.store)}, {"EXCLUDED"})
        restored = await bulk_cards(BulkRequest(action="restore", card_ids=[a, b]), self.conn, self.claims)
        self.assertEqual([r.review_status for r in restored.results], ["PENDING", "PENDING"])
