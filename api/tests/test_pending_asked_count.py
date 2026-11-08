"""질문 목록에 물어본 횟수(2026-11-08). 상세와 같은 방식(v2 영수증, v1 발생 기록)으로 센다."""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.learn import v2_router


class Conn:
    def __init__(self):
        self.queries = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, query, *args):
        self.queries.append(query)
        return [dict(question_id=101, question_text="디카페인 원두는 어디 있어요?", status="WAITING", asked_count=3)]

    async def execute(self, *args):
        pass


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class PendingAskedCountTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_has_asked_count(self):
        conn = Conn()
        with patch.object(v2_router, "enabled", new=lambda: None), \
             patch.object(v2_router, "get_pool", new=lambda: Pool(conn)), \
             patch.object(v2_router, "scope", new=AsyncMock(return_value=(1, 5))), \
             patch.object(v2_router, "require_owner", new=AsyncMock()):
            result = await v2_router.pending_list({"role": "OWNER"}, 9, None, None)
        self.assertEqual(result["questions"][0]["asked_count"], 3)
        self.assertIn("r_answer_receipts", conn.queries[0])
        self.assertIn("pending_question_occurrences", conn.queries[0])
