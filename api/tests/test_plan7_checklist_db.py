"""제출 기록 개수 맞추기 SQL 을 실제 스키마에서 돌린다. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest
from datetime import date

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.checklist import repository as repo


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SubmissionCountsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_update_counts_only_that_user_day_store(self):
        day = date(2026, 11, 8)
        for user in (7, 8):
            await repo.insert_submission(self.conn, self.store, day, user, None, 2, 2, late=False, personal=False)
        await repo.update_submission_counts(self.conn, self.store, day, 7, total=2, done=1)
        await repo.update_submission_counts(self.conn, self.store + 999, day, 8, total=2, done=0)
        rows = {r["user_id"]: r["done_lines"] for r in await self.conn.fetch(
            "select user_id, done_lines from checklist_submissions where store_id = $1", self.store)}
        self.assertEqual(rows, {7: 1, 8: 2})
