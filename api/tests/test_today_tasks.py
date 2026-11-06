"""오늘만 할 일: 요청 검증·권한·알림 생성·다듬기 실패 경계."""
from __future__ import annotations

import re
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.checklist.router import Member
from app.errors import ApiError
from app.notifications.service import create_today_task_notification
from app.today_tasks import router as tt
from app.today_tasks.polish import polish_text
from app.today_tasks.schemas import DoneRequest, TodayTaskCreate

# migration 20261106120000 의 destination 검사식과 같다
DESTINATION = re.compile(r"^/(owner|staff)([/?][A-Za-z0-9_/?=&.-]*)?$")


def member(role: str = "OWNER") -> Member:
    return Member(store_id=42, user_id=7, member_id=9, role=role, personal=True,
                  timezone="Asia/Seoul", day_starts_at=time(4), staff_records_visible=True)


class FakeDb:
    def __init__(self):
        self.in_tx = False

    @asynccontextmanager
    async def transaction(self):
        self.in_tx = True
        try:
            yield
        finally:
            self.in_tx = False


class SchemaTest(unittest.TestCase):
    def test_trims_text_and_dedupes_targets(self):
        req = TodayTaskCreate(text="  오늘   마감 후\n\n 쓰레기통  밖으로 ", member_ids=[3, 3, 5])
        self.assertEqual(req.text, "오늘 마감 후\n쓰레기통 밖으로")
        self.assertEqual(req.member_ids, [3, 5])
        self.assertIsNone(req.body)

    def test_rejects_blank_text(self):
        with self.assertRaises(ValidationError):
            TodayTaskCreate(text="   \n ", member_ids=[3])

    def test_rejects_over_300_chars(self):
        with self.assertRaises(ValidationError):
            TodayTaskCreate(text="가" * 301, member_ids=[3])

    def test_requires_at_least_one_target(self):
        with self.assertRaises(ValidationError):
            TodayTaskCreate(text="쓰레기통 밖으로", member_ids=[])


class CreateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = patch.object(tt, "_now", return_value=datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc))
        self.now.start()
        self.addCleanup(self.now.stop)

    async def test_staff_cannot_send(self):
        with patch.object(tt, "require_member", AsyncMock(return_value=member("STAFF"))):
            with self.assertRaises(ApiError) as raised:
                await tt.create(TodayTaskCreate(text="a", member_ids=[3]), FakeDb(), {}, MagicMock())
        self.assertEqual(raised.exception.code, "OWNER_ONLY")

    async def test_unknown_target_rejected_without_notification(self):
        notify = AsyncMock()
        with patch.object(tt, "require_member", AsyncMock(return_value=member())), \
             patch.object(tt.repo, "active_staff", AsyncMock(return_value={3: 30})), \
             patch.object(tt.repo, "create_task", AsyncMock()) as create, \
             patch.object(tt, "create_today_task_notification", notify):
            with self.assertRaises(ApiError) as raised:
                await tt.create(TodayTaskCreate(text="a", member_ids=[3, 4]), FakeDb(), {}, MagicMock())
        self.assertEqual(raised.exception.code, "TARGET_NOT_FOUND")
        create.assert_not_awaited()
        notify.assert_not_awaited()

    async def test_creates_notification_per_target_and_schedules_push(self):
        db = FakeDb()
        seen_tx: list[bool] = []

        async def notify(db_, store_id, task_id, user_id, body):
            seen_tx.append(db.in_tx)
            return {30: 500, 50: 501}[user_id]

        background = MagicMock()
        listed = [{"task_id": 11, "body": "다듬은 문장", "targets": []}]
        with patch.object(tt, "require_member", AsyncMock(return_value=member())), \
             patch.object(tt.repo, "active_staff", AsyncMock(return_value={3: 30, 5: 50})), \
             patch.object(tt.repo, "create_task", AsyncMock(return_value=11)) as create, \
             patch.object(tt.repo, "list_for_owner", AsyncMock(return_value=listed)), \
             patch.object(tt, "create_today_task_notification", AsyncMock(side_effect=notify)):
            result = await tt.create(
                TodayTaskCreate(text="쓰레기통 밖으로", body="다듬은 문장", member_ids=[3, 5]), db, {}, background)
        # 2026-11-06 03:00Z = 12:00 KST → 영업일 11-06
        create.assert_awaited_once_with(db, 42, date(2026, 11, 6), "다듬은 문장", "쓰레기통 밖으로", 7, [3, 5])
        self.assertEqual(seen_tx, [True, True])  # 앱 알림은 지시와 같은 트랜잭션에서 만든다
        self.assertEqual([c.args[1:] for c in background.add_task.call_args_list], [(42, 500), (42, 501)])
        self.assertEqual(result["task"]["task_id"], 11)

    async def test_without_polish_sends_original_text(self):
        with patch.object(tt, "require_member", AsyncMock(return_value=member())), \
             patch.object(tt.repo, "active_staff", AsyncMock(return_value={3: 30})), \
             patch.object(tt.repo, "create_task", AsyncMock(return_value=11)) as create, \
             patch.object(tt.repo, "list_for_owner", AsyncMock(return_value=[{"task_id": 11}])), \
             patch.object(tt, "create_today_task_notification", AsyncMock(return_value=None)) as notify:
            await tt.create(TodayTaskCreate(text="원문 그대로", member_ids=[3]), FakeDb(), {}, MagicMock())
        self.assertEqual(create.await_args.args[3], "원문 그대로")
        self.assertEqual(notify.await_args.args[4], "원문 그대로")


class StaffRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_done_on_other_or_expired_task_is_404(self):
        with patch.object(tt, "require_member", AsyncMock(return_value=member("STAFF"))), \
             patch.object(tt.repo, "set_done", AsyncMock(return_value=False)):
            with self.assertRaises(ApiError) as raised:
                await tt.done(11, DoneRequest(done=True), FakeDb(), {})
        self.assertEqual(raised.exception.status_code, 404)

    async def test_mine_uses_own_member_and_business_day(self):
        with patch.object(tt, "_now", return_value=datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)), \
             patch.object(tt, "require_member", AsyncMock(return_value=member("STAFF"))), \
             patch.object(tt.repo, "list_for_member", AsyncMock(return_value=[])) as listing:
            result = await tt.list_mine(FakeDb(), {})
        # 11-07 03:00 KST 는 영업일 시작(04:00) 전이라 아직 11-06 영업일이다
        self.assertEqual(result["business_date"], "2026-11-06")
        self.assertEqual(listing.await_args.args[1:], (42, date(2026, 11, 6), 9))


class NotificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_today_task_notification_shape(self):
        db = MagicMock()
        db.fetchval = AsyncMock(return_value=77)
        nid = await create_today_task_notification(db, 42, 11, 30, "쓰레기통 밖으로 옮겨 주세요")
        self.assertEqual(nid, 77)
        args = db.fetchval.await_args.args
        self.assertEqual(args[1:6], (42, 30, "TODAY_TASK", "TODAY_TASK", 11))
        self.assertEqual(args[6], "today-task:42:11:30")
        self.assertRegex(args[9], DESTINATION)
        self.assertEqual(args[9], "/staff?task_id=11")


class PolishTest(unittest.IsolatedAsyncioTestCase):
    async def test_mock_mode_returns_original(self):
        with patch("app.today_tasks.polish.get_settings", return_value=SimpleNamespace(ingest_mode="mock")):
            self.assertEqual(await polish_text("쓰레기통 밖으로", store_id=42, call_id="x"), "쓰레기통 밖으로")

    async def test_model_failure_is_503_so_owner_can_send_original(self):
        settings = SimpleNamespace(ingest_mode="real", gemini_api_key="k", gemini_model="m")
        with patch("app.today_tasks.polish.get_settings", return_value=settings), \
             patch("app.today_tasks.polish.recorded_generate", AsyncMock(side_effect=RuntimeError("down"))):
            with self.assertRaises(ApiError) as raised:
                await polish_text("쓰레기통 밖으로", store_id=42, call_id="x", usage_sink=object())
        self.assertEqual((raised.exception.status_code, raised.exception.code), (503, "POLISH_UNAVAILABLE"))

    async def test_overlong_model_output_rejected(self):
        settings = SimpleNamespace(ingest_mode="real", gemini_api_key="k", gemini_model="m")
        out = SimpleNamespace(body="가" * 301)
        with patch("app.today_tasks.polish.get_settings", return_value=settings), \
             patch("app.today_tasks.polish.recorded_generate", AsyncMock(return_value=out)):
            with self.assertRaises(ApiError):
                await polish_text("쓰레기통 밖으로", store_id=42, call_id="x", usage_sink=object())


if __name__ == "__main__":
    unittest.main()


class ValidationEnvelopeTest(unittest.TestCase):
    """새 경로의 422 도 공통 오류 형식으로 나간다(errors.py new_api 접두사)."""

    def test_new_routes_use_error_envelope(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.errors import install_error_handlers
        from app.report.router import router as report_router

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(tt.router, prefix="/today-tasks")
        app.include_router(report_router, prefix="/report")
        from app.deps import get_db

        async def fake_db():
            yield object()
        from app.errors import get_api_claims
        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[get_api_claims] = lambda: {"store_id": 1, "user_id": 1, "role": "OWNER"}
        client = TestClient(app, headers={"Authorization": "Bearer x"})
        for method, path, body in (("POST", "/today-tasks", {}), ("GET", "/report/summary?days=9", None)):
            res = client.request(method, path, json=body)
            self.assertEqual(res.status_code, 422, path)
            self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR", path)
