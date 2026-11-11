"""계획 8 Task 5: 올린 자료 목록. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SourceListTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.other = await seed_store(self.conn)
        self.user = await self.conn.fetchval("insert into users (name, role) values ('사장', 'OWNER') returning user_id")
        ins = "insert into sources (store_id, uploaded_by, source_type, title) values ($1, $2, 'SCAN', $3) returning source_id"
        self.a = await self.conn.fetchval(ins, self.store, self.user, "레시피북")
        self.b = await self.conn.fetchval(ins, self.store, self.user, "지운 자료")
        # 지운 자료는 tombstone(D20): deleted_at 과 source_availability 가 함께 바뀐다(CHECK)
        await self.conn.execute("update sources set deleted_at = now(), source_availability = 'DELETED' where source_id = $1", self.b)
        await self.conn.fetchval(ins, self.other, self.user, "남의 자료")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_lists_only_my_live_sources(self):
        from app.ingest import repository
        rows = await repository.list_sources(self.conn, self.store, cursor=None, limit=30)
        self.assertEqual([r["title"] for r in rows], ["레시피북"])

    async def test_cursor_pages_by_source_id_desc(self):
        from app.ingest import repository
        ins = "insert into sources (store_id, uploaded_by, source_type, title) values ($1, $2, 'SCAN', $3) returning source_id"
        c = await self.conn.fetchval(ins, self.store, self.user, "새 자료")
        first = await repository.list_sources(self.conn, self.store, cursor=None, limit=1)
        self.assertEqual([r["source_id"] for r in first], [c])
        rest = await repository.list_sources(self.conn, self.store, cursor=c, limit=30)
        self.assertEqual([r["source_id"] for r in rest], [self.a])

    async def test_route_is_owner_only_and_pages(self):
        from app.errors import ApiError
        from app.ingest.router import list_ingest_sources
        with self.assertRaises(ApiError) as err:
            await list_ingest_sources(self.conn, {"user_id": 2, "store_id": self.store, "role": "STAFF"}, cursor=None, limit=30)
        self.assertEqual(err.exception.status_code, 403)
        page = await list_ingest_sources(self.conn, {"user_id": self.user, "store_id": self.store, "role": "OWNER"}, cursor=None, limit=30)
        self.assertEqual([(i["source_id"], i["title"]) for i in page["items"]], [(self.a, "레시피북")])
        self.assertIsNone(page["next_cursor"])
