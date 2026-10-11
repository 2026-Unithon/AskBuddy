"""공개 대상 카드 집합 `current_manifest` 를 검증한다 (W, CP-05).

가짜 conn(AsyncMock)으로 SQL 인자만 검사한다. 사실 블록 조립은
test_wa_publish_fact_only.py / test_w3a_publish_content.py 가 본다.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.publish.content import current_manifest


class CurrentManifestTest(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_follows_current_approved_pointers(self):
        """직전 snapshot 이 아니라 현재 공개 포인터로 만든다(final fix #1·#2).

        레거시 경로가 공개 포인터만 옮긴 카드, 복원된 카드도 그대로 실린다.
        """
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"card_id": 1, "card_version_id": 10},
            {"card_id": 2, "card_version_id": 20},
        ]
        result = await current_manifest(conn, store_id=7)
        self.assertEqual(result, {1: 10, 2: 20})
        sql, *args = conn.fetch.await_args.args
        self.assertEqual(args, [7])
        self.assertIn("review_status = 'APPROVED'", sql)
        self.assertIn("published_version_id is not null", sql)
        self.assertIn("store_id = $1", sql)
        # snapshot 을 읽지 않는다
        self.assertNotIn("snapshot", sql)
        conn.fetchval.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
