"""사장 리포트: 영업일 창 계산·권한·알바생 기록 공개 설정."""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, patch

from app.checklist.router import Member
from app.errors import ApiError
from app.report import router as rr


def member(role="OWNER", visible=True) -> Member:
    return Member(store_id=42, user_id=7, member_id=9, role=role, personal=True,
                  timezone="Asia/Seoul", day_starts_at=time(4), staff_records_visible=visible)


class WindowTest(unittest.TestCase):
    def test_seven_business_days_including_today(self):
        now = datetime(2026, 11, 5, 17, 0, tzinfo=timezone.utc)  # 11-06 02:00 KST → 영업일 11-05
        first, last, start, end = rr.report_window(now, "Asia/Seoul", time(4), 7)
        self.assertEqual((first, last), (date(2026, 10, 30), date(2026, 11, 5)))
        self.assertEqual(start, datetime(2026, 10, 29, 19, 0, tzinfo=timezone.utc))  # 10-30 04:00 KST
        self.assertEqual(end, now)


class SummaryTest(unittest.IsolatedAsyncioTestCase):
    def patches(self, m):
        return [
            patch.object(rr, "require_member", AsyncMock(return_value=m)),
            patch.object(rr.repo, "question_counts", AsyncMock(return_value={"questions": 3})),
            patch.object(rr.repo, "top_escalations", AsyncMock(return_value=[])),
            patch.object(rr.repo, "per_staff", AsyncMock(return_value=[{"member_id": 2}])),
            patch.object(rr.repo, "checklist_counts", AsyncMock(return_value={"submissions": 0, "complete": 0})),
            patch.object(rr.repo, "today_task_counts", AsyncMock(return_value={"tasks": 0, "assigned": 0, "done": 0})),
        ]

    async def run_summary(self, m):
        ps = self.patches(m)
        for p in ps:
            p.start()
        try:
            return await rr.summary(object(), {}, days=7)
        finally:
            for p in ps:
                p.stop()

    async def test_staff_cannot_read_report(self):
        with self.assertRaises(ApiError) as raised:
            await self.run_summary(member("STAFF"))
        self.assertEqual(raised.exception.code, "OWNER_ONLY")

    async def test_per_staff_hidden_when_records_not_visible(self):
        result = await self.run_summary(member(visible=False))
        self.assertIsNone(result["per_staff"])
        self.assertEqual(result["questions"], {"questions": 3})

    async def test_per_staff_shown_when_visible(self):
        result = await self.run_summary(member())
        self.assertEqual(result["per_staff"], [{"member_id": 2}])
        self.assertEqual(result["days"], 7)


class HttpQueryTest(unittest.TestCase):
    """실제 HTTP 쿼리 문자열로 부른다. 함수를 직접 부르면 ?days=7 문자열 변환을 못 본다."""

    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.deps import get_db
        from app.errors import get_api_claims, install_error_handlers

        app = FastAPI()
        install_error_handlers(app)
        app.include_router(rr.router, prefix="/report")

        async def fake_db():
            yield object()
        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[get_api_claims] = lambda: {"store_id": 42, "user_id": 7, "role": "OWNER"}
        return TestClient(app)

    def test_days_query_string_accepted(self):
        with patch.object(rr, "require_member", AsyncMock(return_value=member())), \
             patch.object(rr.repo, "question_counts", AsyncMock(return_value={})), \
             patch.object(rr.repo, "top_escalations", AsyncMock(return_value=[])), \
             patch.object(rr.repo, "per_staff", AsyncMock(return_value=[])), \
             patch.object(rr.repo, "checklist_counts", AsyncMock(return_value={})), \
             patch.object(rr.repo, "today_task_counts", AsyncMock(return_value={})):
            client = self.client()
            for days in (7, 30):
                res = client.get(f"/report/summary?days={days}")
                self.assertEqual(res.status_code, 200, res.text)
                self.assertEqual(res.json()["days"], days)
            self.assertEqual(client.get("/report/summary").json()["days"], 7)

    def test_other_days_rejected(self):
        res = self.client().get("/report/summary?days=9")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
