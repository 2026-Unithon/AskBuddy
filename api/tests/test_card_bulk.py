"""계획 7 Task 4: 카드 일괄 처리. 공개는 한 판으로, 상태 변경은 판을 한 번만 다시 올린다."""
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.cards.router import bulk_cards
from app.cards.schemas import BulkRequest
from app.errors import ApiError
from app.publish import PublishCardsResult

MOD = "app.cards.router"
STORE, USER, MEMBER = 1, 9, 3
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def _claims():
    return {"user_id": USER, "store_id": STORE, "role": "OWNER"}


class Db:
    def __init__(self, cards):
        self.cards = cards

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, query, *args):
        assert args[0] == STORE
        return [c for c in self.cards if c["card_id"] in args[1]]

    async def fetchval(self, query, *args):
        return MEMBER

    async def execute(self, query, *args):
        pass


def card(card_id, status="PENDING", draft=None, published=None):
    return dict(card_id=card_id, review_status=status, draft_version_id=draft or card_id * 10,
                published_version_id=published, updated_at=NOW)


class BulkApproveTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.publish = AsyncMock(return_value=PublishCardsResult(status="PUBLISHED", snapshot_id=1, knowledge_revision=1))
        for p in [patch(f"{MOD}.publish_cards", new=self.publish), patch(f"{MOD}.get_pool", new=lambda: "POOL"),
                  patch(f"{MOD}.card_usage_context", new=AsyncMock(return_value=None))]:
            p.start()
            self.addCleanup(p.stop)

    async def test_bulk_approve_publishes_once(self):
        db = Db([card(1), card(2), card(3)])
        result = await bulk_cards(BulkRequest(action="approve", card_ids=[1, 2, 3]), db, _claims())
        self.publish.assert_awaited_once()
        self.assertEqual([c.card_id for c in self.publish.await_args.kwargs["changes"]], [1, 2, 3])
        self.assertLessEqual(len(self.publish.await_args.kwargs["idempotency_key"]), 40)
        self.assertEqual([(r.card_id, r.ok) for r in result.results], [(1, True), (2, True), (3, True)])

    async def test_bulk_partial_failure_reports_each(self):
        self.publish.return_value = PublishCardsResult(status="NO_PROVENANCE")

        async def one(card_id, db, claims):
            if card_id == 2:
                raise ApiError(409, "CARD_NO_PROVENANCE", "출처를 확인할 수 없는 카드는 아직 공개할 수 없습니다.")
            return type("R", (), {"review_status": "APPROVED"})()

        with patch(f"{MOD}.approve_card", new=AsyncMock(side_effect=one)):
            result = await bulk_cards(BulkRequest(action="approve", card_ids=[1, 2, 3]), Db([card(1), card(2), card(3)]), _claims())
        self.assertEqual([(r.card_id, r.ok) for r in result.results], [(1, True), (2, False), (3, True)])
        self.assertEqual(result.results[1].error["code"], "CARD_NO_PROVENANCE")

    async def test_bulk_rejects_other_store_and_excluded_cards(self):
        db = Db([card(1), card(3, status="EXCLUDED")])
        result = await bulk_cards(BulkRequest(action="approve", card_ids=[1, 2, 3]), db, _claims())
        self.assertEqual([c.card_id for c in self.publish.await_args.kwargs["changes"]], [1])
        codes = {r.card_id: (r.error or {}).get("code") for r in result.results}
        self.assertEqual(codes, {1: None, 2: "CARD_NOT_FOUND", 3: "CARD_EXCLUDED"})


class BulkStatusTest(unittest.IsolatedAsyncioTestCase):
    """빼기·미공개·되돌리기는 카드마다 상태를 바꾸고 공개 판은 마지막에 한 번만 다시 올린다."""

    def setUp(self):
        self.cards = {1: card(1, "APPROVED", published=10), 2: card(2, "APPROVED", published=20), 4: card(4, "PENDING")}
        self.publish = AsyncMock(return_value=PublishCardsResult(status="PUBLISHED", snapshot_id=1, knowledge_revision=1))
        self.events = iter(range(801, 900))
        for p in [
            patch(f"{MOD}.repo.get_card_for_update", new=AsyncMock(side_effect=lambda db, s, cid: dict(self.cards[cid]) if cid in self.cards else None)),
            patch(f"{MOD}.repo.add_event", new=AsyncMock(side_effect=lambda *a, **k: next(self.events))),
            patch(f"{MOD}.repo.mutation_row", new=AsyncMock(side_effect=lambda db, s, cid: dict(
                card_id=cid, review_status="EXCLUDED", draft_version_id=cid * 10, published_version_id=None, updated_at=NOW))),
            patch(f"{MOD}.publish_cards", new=self.publish), patch(f"{MOD}.get_pool", new=lambda: "POOL"),
            patch(f"{MOD}.card_usage_context", new=AsyncMock(return_value=None)),
        ]:
            p.start()
            self.addCleanup(p.stop)

    async def test_bulk_exclude_republishes_once(self):
        result = await bulk_cards(BulkRequest(action="exclude", card_ids=[1, 2, 4, 7]), Db([]), _claims())
        self.publish.assert_awaited_once()
        self.assertEqual(self.publish.await_args.kwargs["changes"], [])
        self.assertTrue(self.publish.await_args.kwargs["idempotency_key"].startswith("bulk-exclude:"))
        self.assertEqual([(r.card_id, r.ok) for r in result.results], [(1, True), (2, True), (4, True), (7, False)])

    async def test_bulk_exclude_of_unpublished_cards_does_not_republish(self):
        await bulk_cards(BulkRequest(action="exclude", card_ids=[4]), Db([]), _claims())
        self.publish.assert_not_awaited()


class BulkRequestTest(unittest.TestCase):
    def test_move_needs_category(self):
        with self.assertRaises(ValueError):
            BulkRequest(action="move", card_ids=[1])

    def test_card_ids_limit(self):
        with self.assertRaises(ValueError):
            BulkRequest(action="approve", card_ids=list(range(1, 202)))
