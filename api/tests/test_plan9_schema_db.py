"""계획 9: 스키마 정리. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest
from pathlib import Path

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

ROOT = Path(__file__).resolve().parents[2]
LIVE = ["api/app", "api/scripts/demo_seed.py", "db/002_seed_demo.sql", "web/lib", "web/app", "web/components"]

DEAD = [("store_members", "day_count"), ("store_members", "progress_rate"), ("store_members", "is_deployable"),
        ("stores", "knowledge_coverage"), ("stores", "deploy_threshold")]


async def columns(conn):
    return {(r["table_name"], r["column_name"]) for r in await conn.fetch(
        "select table_name, column_name from information_schema.columns where table_schema = 'public'")}


@unittest.skipUnless(ENABLED, SKIP_REASON)
class DeadColumnsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_dead_columns_are_gone(self):
        cols = await columns(self.conn)
        for pair in DEAD:
            self.assertNotIn(pair, cols)


class DeadNamesTest(unittest.TestCase):
    def test_no_live_code_names_dead_columns(self):
        names = ["day_count", "progress_rate", "is_deployable", "knowledge_coverage", "deploy_threshold",
                 "update_member_rate", "listStaff", "staffQuery"]
        hits = []
        for entry in LIVE:
            base = ROOT / entry
            files = [base] if base.is_file() else [p for p in base.rglob("*") if p.suffix in (".py", ".ts", ".tsx", ".sql")]
            for path in files:
                text = path.read_text(encoding="utf-8")
                hits += [f"{path.relative_to(ROOT)}: {n}" for n in names if n in text]
        self.assertEqual(hits, [])


@unittest.skipUnless(ENABLED, SKIP_REASON)
class ConstraintTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        # seed_store 가 FK 와 트리거를 꺼 두므로 다시 켠다
        await self.conn.execute("set session_replication_role = origin")
        self.staff = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_member_role_must_match_user_role(self):
        with self.assertRaises(Exception):
            await self.conn.execute(
                "insert into store_members (store_id, user_id, member_role) values ($1, $2, 'OWNER')", self.store, self.staff)

    async def test_matching_role_is_accepted(self):
        await self.conn.execute(
            "insert into store_members (store_id, user_id, member_role) values ($1, $2, 'STAFF')", self.store, self.staff)

    async def test_user_role_cannot_change_under_a_membership(self):
        await self.conn.execute(
            "insert into store_members (store_id, user_id, member_role) values ($1, $2, 'STAFF')", self.store, self.staff)
        with self.assertRaises(Exception):
            await self.conn.execute("update users set role = 'OWNER' where user_id = $1", self.staff)

    async def test_verified_flag_cannot_disagree_with_status(self):
        # 트리거가 맞춰 주므로 트리거를 끈 채 어긋난 값을 넣어 본다
        await self.conn.execute("set session_replication_role = replica")
        with self.assertRaises(Exception):
            await self.conn.execute(
                "insert into knowledge_cards (store_id, review_status, is_verified) values ($1, 'PENDING', true)", self.store)


@unittest.skipUnless(ENABLED, SKIP_REASON)
class CardTextTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_card_has_no_text_columns(self):
        cols = await columns(self.conn)
        self.assertNotIn(("knowledge_cards", "title"), cols)
        self.assertNotIn(("knowledge_cards", "content"), cols)

    async def test_insert_card_writes_text_to_version_only(self):
        from app.ingest import repository
        card_id = await repository.insert_card(
            self.conn, self.store, category_id=None, source_id=None, title="마감 청소", content="바닥을 닦는다", confidence=70)
        row = await self.conn.fetchrow(
            "select v.title, v.content from knowledge_cards c join card_versions v "
            "on v.store_id = c.store_id and v.version_id = c.draft_version_id where c.store_id = $1 and c.card_id = $2",
            self.store, card_id)
        self.assertEqual((row["title"], row["content"]), ("마감 청소", "바닥을 닦는다"))

    async def test_review_list_reads_draft_version(self):
        from app.ingest import repository
        card_id = await repository.insert_card(
            self.conn, self.store, category_id=None, source_id=None, title="처음", content="처음 글", confidence=70)
        version = await self.conn.fetchval(
            "insert into card_versions (store_id, card_id, version_no, title, content, change_source) "
            "values ($1, $2, 2, '고친 제목', '고친 글', 'OWNER_EDIT') returning version_id", self.store, card_id)
        await self.conn.execute("update knowledge_cards set draft_version_id = $3 where store_id = $1 and card_id = $2", self.store, card_id, version)
        rows = await repository.list_review_cards(self.conn, self.store, verified=None, source_id=None, limit=10, offset=0)
        self.assertEqual([(r["title"], r["content"]) for r in rows], [("고친 제목", "고친 글")])
