"""계획 7 Task 8: 지난 대화 목록. 제목(첫 질문)·마지막 시각·검색, 내 대화만. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.learn.sessions import list_member_sessions


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SessionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def session(self, member, questions, minutes_ago):
        sid = await self.conn.fetchval(
            "insert into chat_sessions (store_id, member_id, contract_version) values ($1, $2, 'v2') returning session_id", self.store, member)
        for i, q in enumerate(questions):
            at = f"now() - interval '{minutes_ago} minutes' + interval '{i} seconds'"
            await self.conn.execute(f"insert into chat_messages (session_id, sender_type, content, created_at) values ($1, 'USER', $2, {at})", sid, q)
            await self.conn.execute(f"insert into chat_messages (session_id, sender_type, content, created_at) values ($1, 'BUDDY', '답', {at})", sid)
        return sid

    async def test_title_last_at_and_order(self):
        old = await self.session(7, ["우유 발주 언제 해요?"], 60)
        new = await self.session(7, ["바닐라 시럽 몇 펌프예요?", "얼음은요?"], 5)
        rows = await list_member_sessions(self.conn, self.store, 7, None)
        self.assertEqual([r["session_id"] for r in rows], [new, old])
        self.assertEqual(rows[0]["title"], "바닐라 시럽 몇 펌프예요?")
        self.assertGreater(rows[0]["last_at"], rows[1]["last_at"])

    async def test_search_and_only_mine(self):
        mine = await self.session(7, ["우유 발주 언제 해요?"], 10)
        await self.session(8, ["우유 보관은요?"], 5)
        await self.session(7, ["얼음은요?"], 3)
        rows = await list_member_sessions(self.conn, self.store, 7, "우유")
        self.assertEqual([r["session_id"] for r in rows], [mine])
        self.assertEqual(await list_member_sessions(self.conn, self.store + 999, 7, None), [])
