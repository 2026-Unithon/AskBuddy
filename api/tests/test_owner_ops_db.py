"""로컬 PostgreSQL 에서 오늘만 할 일·리포트 SQL 과 매장 격리를 검증한다. 테스트 데이터는 롤백한다.

OPS_TEST_DB_URL(없으면 KAKAO_TEST_DB_URL)이 로컬 주소일 때만 실행한다. 운영 연결은 거부한다.
"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import asyncpg

from app.notifications.service import create_today_task_notification
from app.report import repository as report
from app.today_tasks import repository as tasks

DB_URL = os.environ.get("OPS_TEST_DB_URL") or os.environ.get("KAKAO_TEST_DB_URL")
TODAY = date(2026, 11, 6)
T0 = datetime(2026, 11, 5, 19, 0, tzinfo=timezone.utc)  # 11-06 04:00 KST 영업일 시작


@unittest.skipUnless(DB_URL, "로컬 DB 통합 검증은 명시적으로 실행한다")
class OwnerOpsDb(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        assert urlparse(DB_URL).hostname in ("127.0.0.1", "localhost", "::1")
        self.db = await asyncpg.connect(DB_URL)
        self.tx = self.db.transaction()
        await self.tx.start()
        self.a = await self.store("합성 A")
        self.b = await self.store("합성 B")

    async def asyncTearDown(self):
        await self.tx.rollback()
        await self.db.close()

    async def user(self, name, role):
        return await self.db.fetchval("insert into users (name, role) values ($1, $2) returning user_id", name, role)

    async def member(self, store_id, user_id, role):
        return await self.db.fetchval(
            "insert into store_members (store_id, user_id, member_role) values ($1, $2, $3) returning member_id",
            store_id, user_id, role)

    async def store(self, name):
        owner = await self.user(f"{name} 사장", "OWNER")
        store_id = await self.db.fetchval(
            "insert into stores (owner_id, store_name, business_type) values ($1, $2, 'CAFE') returning store_id",
            owner, name)
        owner_member = await self.member(store_id, owner, "OWNER")
        staff = []
        for n in ("박지호", "김민준"):
            uid = await self.user(f"{name} {n}", "STAFF")
            staff.append((await self.member(store_id, uid, "STAFF"), uid))
        return {"id": store_id, "owner": owner, "owner_member": owner_member, "staff": staff}

    # ---- 오늘만 할 일 ----

    async def test_active_staff_excludes_owner_removed_and_other_store(self):
        a, b = self.a, self.b
        (m1, u1), (m2, _) = a["staff"]
        await self.db.execute("update store_members set removed_at = now() where member_id = $1", m2)
        found = await tasks.active_staff(self.db, a["id"], [m1, m2, a["owner_member"], b["staff"][0][0]])
        self.assertEqual(found, {m1: u1})

    async def test_task_lifecycle_is_scoped_to_target_and_day(self):
        a = self.a
        (m1, _), (m2, _) = a["staff"]
        tid = await tasks.create_task(self.db, a["id"], TODAY, "쓰레기통 밖으로", "쓰레기통", a["owner"], [m1])
        await tasks.create_task(self.db, a["id"], TODAY - timedelta(days=1), "어제 일", "어제", a["owner"], [m1])

        self.assertEqual([t["task_id"] for t in await tasks.list_for_member(self.db, a["id"], TODAY, m1)], [tid])
        self.assertEqual(await tasks.list_for_member(self.db, a["id"], TODAY, m2), [])
        # 다른 매장 id 로는 같은 지시가 보이지 않는다
        self.assertEqual(await tasks.list_for_member(self.db, self.b["id"], TODAY, m1), [])

        self.assertEqual(await tasks.mark_seen(self.db, a["id"], m1, [tid], TODAY), 1)
        self.assertEqual(await tasks.mark_seen(self.db, a["id"], m1, [tid], TODAY), 0)
        self.assertFalse(await tasks.set_done(self.db, a["id"], tid, m2, TODAY, True))  # 대상 아님
        self.assertFalse(await tasks.set_done(self.db, a["id"], tid, m1, TODAY + timedelta(days=1), True))  # 영업일 지남
        self.assertTrue(await tasks.set_done(self.db, a["id"], tid, m1, TODAY, True))

        owner_view = await tasks.list_for_owner(self.db, a["id"], TODAY)
        self.assertEqual(len(owner_view), 1)
        target = owner_view[0]["targets"][0]
        self.assertEqual(target["name"], "합성 A 박지호")
        self.assertIsNotNone(target["seen_at"])
        self.assertIsNotNone(target["done_at"])

        self.assertFalse(await tasks.cancel_task(self.db, self.b["id"], tid, TODAY))  # 다른 매장
        self.assertTrue(await tasks.cancel_task(self.db, a["id"], tid, TODAY))
        self.assertEqual(await tasks.list_for_owner(self.db, a["id"], TODAY), [])
        self.assertEqual(await tasks.list_for_member(self.db, a["id"], TODAY, m1), [])

    async def test_target_from_other_store_rejected_by_db(self):
        with self.assertRaises(asyncpg.RaiseError):
            async with self.db.transaction():
                await tasks.create_task(self.db, self.a["id"], TODAY, "x", "x", self.a["owner"], [self.b["staff"][0][0]])

    async def test_today_task_notification_passes_constraints(self):
        (m1, u1), _ = self.a["staff"]
        tid = await tasks.create_task(self.db, self.a["id"], TODAY, "얼음 채우기", "얼음", self.a["owner"], [m1])
        nid = await create_today_task_notification(self.db, self.a["id"], tid, u1, "얼음 채우기")
        self.assertIsNotNone(nid)
        # 같은 지시·사람으로 다시 만들면 중복 알림이 생기지 않는다
        self.assertIsNone(await create_today_task_notification(self.db, self.a["id"], tid, u1, "얼음 채우기"))

    async def test_usage_ledger_accepts_polish_stage(self):
        definition = await self.db.fetchval(
            "select pg_get_constraintdef(oid) from pg_constraint where conname = 'ai_usage_attempts_stage_check'")
        self.assertIn("POLISH", definition)

    # ---- 리포트 ----

    async def session(self, store_id, member_id):
        return await self.db.fetchval(
            "insert into chat_sessions (store_id, member_id) values ($1, $2) returning session_id", store_id, member_id)

    async def msg(self, session_id, sender, at, answer_type=None, source=None):
        return await self.db.fetchval(
            """insert into chat_messages (session_id, sender_type, content, answer_type, answer_source, created_at)
               values ($1, $2, '합성', $3, $4, $5) returning message_id""",
            session_id, sender, answer_type, source, at)

    async def pending(self, store_id, member_id, text, at, status="WAITING"):
        return await self.db.fetchval(
            """insert into pending_questions (store_id, member_id, question_text, status, created_at)
               values ($1, $2, $3, $4, $5) returning question_id""",
            store_id, member_id, text, status, at)

    async def test_report_counts_staff_only_and_store_scoped(self):
        a = self.a
        (m1, _), (m2, _) = a["staff"]
        s1 = await self.session(a["id"], m1)
        s_owner = await self.session(a["id"], a["owner_member"])
        s_b = await self.session(self.b["id"], self.b["staff"][0][0])
        at = T0 + timedelta(hours=2)
        for _ in range(3):
            await self.msg(s1, "USER", at)
        await self.msg(s1, "BUDDY", at, "ANSWERED", "CARD_ORIGINAL")
        await self.msg(s1, "BUDDY", at, "ANSWERED", "OWNER_ANSWER")  # 점주 원문 전달은 AI 답이 아니다
        await self.msg(s1, "BUDDY", at, "NO_ANSWER", "MISS")
        await self.msg(s1, "USER", T0 - timedelta(minutes=1))  # 기간 밖
        await self.msg(s_owner, "USER", at)  # 사장 미리보기
        await self.msg(s_b, "USER", at)  # 다른 매장

        q1 = await self.pending(a["id"], m1, "디카페인 어디?", at, "ANSWERED")
        q2 = await self.pending(a["id"], m2, "오트밀크 있어요?", at)
        for q, m in ((q1, m1), (q1, m2), (q2, m2)):
            await self.db.execute(
                "insert into pending_question_occurrences (question_id, member_id, asked_at) values ($1, $2, $3)", q, m, at)
        await self.db.execute(
            "insert into owner_answers (question_id, answered_by, answer_text, answered_at) values ($1, $2, '창고 2번', $3)",
            q1, a["owner"], at + timedelta(minutes=30))

        end = T0 + timedelta(days=1)
        counts = await report.question_counts(self.db, a["id"], T0, end)
        self.assertEqual(counts, {"questions": 3, "ai_answered": 1, "escalated": 3, "owner_answered": 1,
                                  "answer_minutes_median": 30, "waiting_now": 1})
        top = await report.top_escalations(self.db, a["id"], T0, end)
        self.assertEqual([(t["question_id"], t["asked"]) for t in top], [(q1, 2), (q2, 1)])
        staff = {r["member_id"]: r for r in await report.per_staff(self.db, a["id"], T0, end)}
        self.assertEqual((staff[m1]["questions"], staff[m1]["escalated"]), (3, 1))
        self.assertEqual((staff[m2]["questions"], staff[m2]["escalated"]), (0, 2))
        self.assertNotIn(a["owner_member"], staff)

        other = await report.question_counts(self.db, self.b["id"], T0, end)
        self.assertEqual((other["questions"], other["escalated"]), (1, 0))

    async def test_report_today_task_counts_skip_canceled(self):
        a = self.a
        (m1, _), (m2, _) = a["staff"]
        t1 = await tasks.create_task(self.db, a["id"], TODAY, "a", "a", a["owner"], [m1, m2])
        t2 = await tasks.create_task(self.db, a["id"], TODAY, "b", "b", a["owner"], [m1])
        await tasks.set_done(self.db, a["id"], t1, m1, TODAY, True)
        await tasks.cancel_task(self.db, a["id"], t2, TODAY)
        self.assertEqual(await report.today_task_counts(self.db, a["id"], TODAY - timedelta(days=6), TODAY),
                         {"tasks": 1, "assigned": 2, "done": 1})
        self.assertEqual(await report.checklist_counts(self.db, a["id"], TODAY - timedelta(days=6), TODAY),
                         {"submissions": 0, "complete": 0})


if __name__ == "__main__":
    unittest.main()
