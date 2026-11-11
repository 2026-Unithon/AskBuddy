"""계획 8 Task 6: 문의, 의견 저장. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store


@unittest.skipUnless(ENABLED, SKIP_REASON)
class FeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.user = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_saves_trimmed_body_with_store(self):
        from app.bootstrap import account
        fid = await account.save_feedback(self.conn, store_id=self.store, user_id=self.user, kind="IDEA", body="  다크 모드  ")
        row = await self.conn.fetchrow("select store_id, kind, body from user_feedback where feedback_id = $1", fid)
        self.assertEqual(dict(row), {"store_id": self.store, "kind": "IDEA", "body": "다크 모드"})

    async def test_rejects_blank(self):
        from app.bootstrap import account
        with self.assertRaises(ValueError):
            await account.save_feedback(self.conn, store_id=self.store, user_id=self.user, kind="INQUIRY", body="   ")

    async def test_route_maps_blank_to_400(self):
        from fastapi import BackgroundTasks
        from app.bootstrap.account_router import FeedbackRequest, post_feedback
        from app.errors import ApiError
        with self.assertRaises(ApiError) as err:
            await post_feedback(FeedbackRequest(kind="IDEA", body="   "), self.conn, self.store, self.user, BackgroundTasks())
        self.assertEqual((err.exception.status_code, err.exception.code), (400, "FEEDBACK_EMPTY"))
        saved = await post_feedback(FeedbackRequest(kind="INQUIRY", body="사진이 안 올라가요"), self.conn, self.store, self.user, BackgroundTasks())
        self.assertIsInstance(saved["feedback_id"], int)

    async def test_saved_feedback_schedules_mail_after_response(self):
        # 계획 9 Task 10: 저장한 뒤 메일 알림을 응답 뒤로 미룬다(기다리지 않는다). 빈 글이면 미루지 않는다
        from fastapi import BackgroundTasks
        from app.bootstrap import feedback_mail
        from app.bootstrap.account_router import FeedbackRequest, post_feedback
        tasks = BackgroundTasks()
        saved = await post_feedback(FeedbackRequest(kind="IDEA", body="다크 모드"), self.conn, self.store, self.user, tasks)
        self.assertEqual([(t.func, t.kwargs) for t in tasks.tasks],
                         [(feedback_mail.notify_feedback, {"feedback_id": saved["feedback_id"], "kind": "IDEA"})])
