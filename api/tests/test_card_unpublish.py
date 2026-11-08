"""계획 7 Task 3: 미공개(공개 내리기). 공개 판에서 빼고 학습 기록·근무조 연결은 건드리지 않는다."""
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.cards.router import unpublish_card
from app.errors import ApiError
from app.publish import PublishCardsResult

MOD = "app.cards.router"
CARD, STORE, USER, MEMBER = 5, 1, 9, 3


class Db:
    def __init__(self):
        self.sql: list[tuple[str, tuple]] = []
        self.log: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        self.log.append("tx_begin")
        yield
        self.log.append("tx_commit")

    async def execute(self, query, *args):
        self.sql.append((query, args))

    async def fetchval(self, query, *args):
        return MEMBER


def _claims():
    return {"user_id": USER, "store_id": STORE, "role": "OWNER"}


class UnpublishTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.card = dict(card_id=CARD, review_status="APPROVED", published_version_id=50, draft_version_id=50)
        self.db = Db()
        db = self.db

        async def publish(pool, **kwargs):
            db.log.append("publish_cards")
            return PublishCardsResult(status="PUBLISHED", snapshot_id=8, knowledge_revision=8)

        self.publish = AsyncMock(side_effect=publish)
        for p in [
            patch(f"{MOD}.repo.get_card_for_update", new=AsyncMock(side_effect=lambda *a: dict(self.card))),
            patch(f"{MOD}.repo.add_event", new=AsyncMock(return_value=801)),
            patch(f"{MOD}.repo.mutation_row", new=AsyncMock(return_value=dict(
                card_id=CARD, review_status="PENDING", draft_version_id=50, published_version_id=None,
                updated_at=datetime(2026, 11, 8, tzinfo=timezone.utc)))),
            patch(f"{MOD}.card_usage_context", new=AsyncMock(return_value=None)),
            patch(f"{MOD}.get_pool", new=lambda: "POOL"),
            patch(f"{MOD}.publish_cards", new=self.publish),
        ]:
            p.start()
            self.addCleanup(p.stop)

    async def test_unpublish_clears_pointer_then_republishes(self):
        result = await unpublish_card(CARD, self.db, _claims())
        self.assertEqual(result.review_status, "PENDING")
        query, args = self.db.sql[0]
        self.assertIn("published_version_id = null", query)
        self.assertIn("review_status = 'PENDING'", query)
        self.assertEqual(args[:2], (STORE, CARD))
        self.publish.assert_awaited_once()
        self.assertEqual(self.publish.await_args.kwargs["changes"], [])
        self.assertEqual(self.publish.await_args.kwargs["idempotency_key"], f"unpublish:{CARD}:801")
        self.assertLess(self.db.log.index("tx_commit"), self.db.log.index("publish_cards"))

    async def test_unpublish_keeps_learning_and_checklist(self):
        await unpublish_card(CARD, self.db, _claims())
        touched = " ".join(q for q, _ in self.db.sql)
        for table in ("roadmap", "learning", "checklist"):
            self.assertNotIn(table, touched)

    async def test_unpublish_needs_review_goes_pending_without_republish(self):
        self.card.update(review_status="NEEDS_REVIEW", published_version_id=None)
        await unpublish_card(CARD, self.db, _claims())
        self.assertIn("review_status = 'PENDING'", self.db.sql[0][0])
        self.publish.assert_not_awaited()

    async def test_unpublish_rejects_pending_and_excluded(self):
        for status in ("PENDING", "EXCLUDED"):
            with self.subTest(status=status):
                self.card.update(review_status=status, published_version_id=None)
                with self.assertRaises(ApiError) as raised:
                    await unpublish_card(CARD, Db(), _claims())
                self.assertEqual(raised.exception.status_code, 409)
