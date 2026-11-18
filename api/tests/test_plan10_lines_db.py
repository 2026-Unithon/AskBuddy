"""계획 10: 카드 표시 줄 저장소(card_version_lines). 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store


@unittest.skipUnless(ENABLED, SKIP_REASON)
class LinesSchemaTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.version = await self.conn.fetchval(
            "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
            "values ($1, 1, 1, '합성 꿀 커피', '-', 'EXTRACTION') returning version_id", self.store)
        await self.conn.execute(
            "insert into card_version_blocks (store_id, card_version_id, block_id, kind, block_order, heading) "
            "values ($1, $2, 'b1', 'STEPS', 1, 'HOT')", self.store, self.version)
        await self.conn.execute("set session_replication_role = origin")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_line_needs_text_and_facts(self):
        ins = ("insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) "
               "values ($1, $2, 'b1', 1, $3, $4)")
        with self.assertRaises(Exception):
            await self.conn.execute(ins, self.store, self.version, " ", [1])
        with self.assertRaises(Exception):
            await self.conn.execute(ins, self.store, self.version, "2샷", [])

    async def test_lines_are_immutable_while_store_active(self):
        await self.conn.execute(
            "insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) "
            "values ($1, $2, 'b1', 1, '2샷', '{1}')", self.store, self.version)
        with self.assertRaises(Exception):
            await self.conn.execute("update card_version_lines set text = 'x' where store_id = $1", self.store)
        with self.assertRaises(Exception):
            await self.conn.execute("delete from card_version_lines where store_id = $1", self.store)

    async def test_block_delete_cascades_lines(self):
        # 평가 매장 초기화 스크립트처럼 블록째 지우면 줄도 따라 지워진다
        await self.conn.execute(
            "insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) "
            "values ($1, $2, 'b1', 1, '2샷', '{1}')", self.store, self.version)
        await self.conn.execute("delete from card_version_blocks where store_id = $1", self.store)
        self.assertEqual(await self.conn.fetchval("select count(*) from card_version_lines where store_id = $1", self.store), 0)

    async def test_other_store_cannot_read_lines(self):
        # D1: 다른 매장 id 로는 같은 판 번호를 물어도 줄이 하나도 나오지 않는다
        from app.cards.fact_edit_repo import load_version_lines
        await self.conn.execute(
            "insert into card_version_lines (store_id, card_version_id, block_id, line_no, text, fact_revision_ids) "
            "values ($1, $2, 'b1', 1, '2샷 내리기', '{1}')", self.store, self.version)
        await self.conn.execute("set session_replication_role = replica")
        other = await seed_store(self.conn)
        self.assertEqual(await load_version_lines(self.conn, other, self.version), {})
        self.assertEqual(await load_version_lines(self.conn, self.store, self.version), {"b1": (("2샷 내리기", (1,)),)})

    async def test_purge_lists_lines(self):
        from app.bootstrap import purge
        self.assertLess(purge.PURGE_ORDER.index("card_version_lines"), purge.PURGE_ORDER.index("card_version_blocks"))


@unittest.skipUnless(ENABLED, SKIP_REASON)
class WriteBlocksTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        # 사실 판(11, 12)은 외래 키를 끈 채 합성 판으로 둔다
        self.version = await self.conn.fetchval(
            "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
            "values ($1, 1, 1, '합성 알갱이', '-', 'EXTRACTION') returning version_id", self.store)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_write_blocks_stores_heading_lines_and_content(self):
        from app.ingest.card_plan import ValidatedBlock
        from app.ingest.fact_cards import write_card_blocks
        blocks = [ValidatedBlock(block_id="b1", kind="STEPS", order=1, fact_revision_ids=(11, 12), variant=(None, None),
                                 heading="만들기", lines=(("물 끓이기", (11,)), ("15분 삶기", (12,))))]
        await write_card_blocks(self.conn, self.store, version_id=self.version, blocks=blocks)
        rows = await self.conn.fetch(
            "select line_no, text, fact_revision_ids from card_version_lines where store_id = $1 order by line_no", self.store)
        self.assertEqual([(r["line_no"], r["text"], list(r["fact_revision_ids"])) for r in rows],
                         [(1, "물 끓이기", [11]), (2, "15분 삶기", [12])])
        self.assertEqual(await self.conn.fetchval(
            "select heading from card_version_blocks where store_id = $1 and card_version_id = $2", self.store, self.version), "만들기")
        self.assertEqual(await self.conn.fetchval(
            "select count(*) from card_block_facts where store_id = $1 and card_version_id = $2", self.store, self.version), 2)
        content = await self.conn.fetchval(
            "select content from card_versions where store_id = $1 and version_id = $2", self.store, self.version)
        self.assertEqual(content, "만들기\n물 끓이기\n15분 삶기")
