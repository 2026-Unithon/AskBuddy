"""카드 버전 → RAW 블록 고정과 KnowledgeContent 조립을 검증한다 (W, CP-05 / Task 2).

가짜 conn(AsyncMock)으로 SQL 호출 순서·인자만 검사한다. 실제 DB 는 Task 7의
통합 스크립트가 돈다.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.contracts.snapshot import KnowledgeContent
from app.learn.approved_renderer import RENDERER_VERSION
from app.publish.content import (
    MAX_BLOCKS,
    RAW_SPAN_MAX,
    InvalidContent,
    NoProvenance,
    build_knowledge_content,
    current_manifest,
    ensure_raw_blocks,
)


def _conn_with_fetchvals(*values):
    """fetchval 이 호출될 때마다 순서대로 값을 돌려주는 가짜 conn."""
    conn = AsyncMock()
    conn.fetchval.side_effect = list(values)
    return conn


class EnsureRawBlocksTest(unittest.IsolatedAsyncioTestCase):
    async def test_existing_blocks_is_idempotent_and_inserts_nothing(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 1  # 이미 블록이 있다
        await ensure_raw_blocks(
            conn, store_id=1, card_id=2, card_version_id=3,
            allow_owner_answer=False)
        conn.execute.assert_not_awaited()
        self.assertEqual(conn.fetchval.await_count, 1)

    async def test_missing_version_raises(self):
        conn = AsyncMock()
        conn.fetchval.return_value = None  # 블록 없음 확인
        conn.fetchrow.return_value = None   # 카드 버전도 없음
        with self.assertRaises(ValueError):
            await ensure_raw_blocks(
                conn, store_id=1, card_id=2, card_version_id=3,
                allow_owner_answer=False)

    async def test_long_content_splits_into_multiple_spans_under_max_and_roundtrips(self):
        # 두 개의 빈 줄을 포함한 5000자 본문
        para_a = "가" * 2000
        para_b = "나" * 2000
        para_c = "다" * 996
        content = f"{para_a}\n\n{para_b}\n\n{para_c}"
        self.assertEqual(len(content), 5000)

        conn = AsyncMock()
        conn.fetchval.side_effect = [
            None,   # 블록 존재 확인 -> 없음
            10,     # knowledge_cards.source_id
        ] + list(range(100, 100 + MAX_BLOCKS))  # raw_spans insert returning id
        conn.fetchrow.return_value = {"content": content}

        await ensure_raw_blocks(
            conn, store_id=1, card_id=2, card_version_id=3,
            allow_owner_answer=False)

        insert_calls = [c for c in conn.fetchval.await_args_list
                        if "insert into raw_spans" in c.args[0]]
        self.assertGreaterEqual(len(insert_calls), 2)
        texts = [c.args[-1] for c in insert_calls]
        for text in texts:
            self.assertLessEqual(len(text), RAW_SPAN_MAX)
        self.assertEqual("".join(texts), content)

        # card_version_blocks insert 도 조각 수만큼 있어야 한다
        self.assertEqual(conn.execute.await_count, len(texts))
        for n, call in enumerate(conn.execute.await_args_list, start=1):
            self.assertEqual(call.args[3], f"raw{n}")

    async def test_no_source_and_owner_answer_disallowed_raises_no_provenance(self):
        conn = AsyncMock()
        conn.fetchval.side_effect = [
            None,  # 블록 존재 확인 -> 없음
            None,  # source_id 없음
        ]
        conn.fetchrow.return_value = {"content": "본문"}
        with self.assertRaises(NoProvenance):
            await ensure_raw_blocks(
                conn, store_id=1, card_id=2, card_version_id=3,
                allow_owner_answer=False)

    async def test_no_source_but_owner_answer_allowed_uses_owner_answer_id(self):
        conn = AsyncMock()
        conn.fetchval.side_effect = [
            None,  # 블록 존재 확인 -> 없음
            None,  # source_id 없음
            77,    # owner_answers.answer_id
            555,   # raw_spans insert returning id
        ]
        conn.fetchrow.return_value = {"content": "짧은 본문"}

        await ensure_raw_blocks(
            conn, store_id=1, card_id=2, card_version_id=3,
            allow_owner_answer=True)

        insert_call = next(c for c in conn.fetchval.await_args_list
                           if "insert into raw_spans" in c.args[0])
        # (query, store_id, source_id, owner_answer_id, text)
        self.assertIsNone(insert_call.args[2])
        self.assertEqual(insert_call.args[3], 77)

    async def test_version_owner_answer_wins_over_card_source(self):
        # 자료 출처 카드에 얹은 점주 답변 판은 자료가 아니라 그 답변을 출처로 싣는다
        conn = AsyncMock()
        conn.fetchval.side_effect = [
            None,  # 블록 존재 확인 -> 없음
            555,   # raw_spans insert returning id
        ]
        conn.fetchrow.return_value = {"content": "점주 답", "owner_answer_id": 88}

        await ensure_raw_blocks(
            conn, store_id=1, card_id=2, card_version_id=3,
            allow_owner_answer=True)

        self.assertFalse(any("from knowledge_cards" in c.args[0]
                             for c in conn.fetchval.await_args_list))
        insert_call = next(c for c in conn.fetchval.await_args_list
                           if "insert into raw_spans" in c.args[0])
        self.assertIsNone(insert_call.args[2])
        self.assertEqual(insert_call.args[3], 88)

    async def test_version_owner_answer_disallowed_raises_no_provenance(self):
        # 플래그가 꺼져 있으면 카드에 자료 출처가 있어도 공개하지 않는다
        conn = AsyncMock()
        conn.fetchval.side_effect = [None, 10]
        conn.fetchrow.return_value = {"content": "점주 답", "owner_answer_id": 88}
        with self.assertRaises(NoProvenance):
            await ensure_raw_blocks(
                conn, store_id=1, card_id=2, card_version_id=3,
                allow_owner_answer=False)
        self.assertFalse(any("insert into raw_spans" in c.args[0]
                             for c in conn.fetchval.await_args_list))

    async def test_too_many_chunks_raises_value_error(self):
        content = "\n\n".join("가" * RAW_SPAN_MAX for _ in range(MAX_BLOCKS + 1))
        conn = AsyncMock()
        conn.fetchval.side_effect = [None, 10]
        conn.fetchrow.return_value = {"content": content}
        with self.assertRaises(InvalidContent):
            await ensure_raw_blocks(
                conn, store_id=1, card_id=2, card_version_id=3,
                allow_owner_answer=False)

    async def test_empty_or_blank_content_raises_invalid_content_without_insert(self):
        # 빈 원문을 블록 0개로 조용히 통과시키면 조립 단계에서 뒤늦게 터진다(final fix #3)
        for content in ("", "  \n\n  ", None):
            with self.subTest(content=content):
                conn = AsyncMock()
                conn.fetchval.side_effect = [None, 10]  # 블록 없음, 자료 출처 10
                conn.fetchrow.return_value = {"content": content}
                with self.assertRaises(InvalidContent):
                    await ensure_raw_blocks(
                        conn, store_id=1, card_id=2, card_version_id=3,
                        allow_owner_answer=False)
                conn.execute.assert_not_awaited()
                self.assertFalse(any("insert into raw_spans" in c.args[0]
                                     for c in conn.fetchval.await_args_list))

    async def test_all_calls_include_store_id_first(self):
        conn = AsyncMock()
        conn.fetchval.side_effect = [None, 10, 900]
        conn.fetchrow.return_value = {"content": "본문"}
        await ensure_raw_blocks(
            conn, store_id=42, card_id=2, card_version_id=3,
            allow_owner_answer=False)
        for call in conn.fetchval.await_args_list:
            self.assertEqual(call.args[1], 42)
        for call in conn.fetchrow.await_args_list:
            self.assertEqual(call.args[1], 42)
        for call in conn.execute.await_args_list:
            self.assertEqual(call.args[1], 42)


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


class BuildKnowledgeContentTest(unittest.IsolatedAsyncioTestCase):
    async def test_builds_valid_knowledge_content_with_renderer_version(self):
        conn = AsyncMock()

        async def fetchrow(query, *args):
            if "from card_versions" in query:
                return {"title": "아이스 아메리카노 만들기"}
            if "from raw_spans" in query:
                return {"raw_span_id": 500, "source_id": 60,
                        "owner_answer_id": None, "span_text": "원문 그대로"}
            raise AssertionError(f"unexpected query: {query}")

        conn.fetchrow.side_effect = fetchrow
        conn.fetch.return_value = [
            {"block_id": "raw1", "kind": "RAW", "block_order": 1,
             "raw_span_id": 500},
        ]

        content = await build_knowledge_content(
            conn, store_id=7, manifest={1: 10}, glossary_version="glossary/v1")

        self.assertIsInstance(content, KnowledgeContent)
        self.assertEqual(content.renderer_version, RENDERER_VERSION)
        self.assertEqual(len(content.cards), 1)
        self.assertEqual(content.cards[0].card_id, "1")
        self.assertEqual(len(content.raw_spans), 1)
        self.assertEqual(content.raw_spans[0].raw_span_id, "500")

        # 매장 인자 검사
        for call in conn.fetch.await_args_list:
            self.assertEqual(call.args[1], 7)

    async def test_version_without_blocks_raises_value_error(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"title": "제목"}
        conn.fetch.return_value = []
        with self.assertRaises(ValueError):
            await build_knowledge_content(
                conn, store_id=7, manifest={1: 10}, glossary_version="glossary/v1")

    async def test_empty_title_falls_back_to_default(self):
        conn = AsyncMock()

        async def fetchrow(query, *args):
            if "from card_versions" in query:
                return {"title": "   "}
            if "from raw_spans" in query:
                return {"raw_span_id": 500, "source_id": 60,
                        "owner_answer_id": None, "span_text": "원문"}
            raise AssertionError(f"unexpected query: {query}")

        conn.fetchrow.side_effect = fetchrow
        conn.fetch.return_value = [
            {"block_id": "raw1", "kind": "RAW", "block_order": 1,
             "raw_span_id": 500},
        ]
        content = await build_knowledge_content(
            conn, store_id=7, manifest={1: 10}, glossary_version="glossary/v1")
        self.assertEqual(content.cards[0].title, "제목 없음")


if __name__ == "__main__":
    unittest.main()
