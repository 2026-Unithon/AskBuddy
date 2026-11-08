"""정리 취소 라우트·멈춤 확인(2026-11-08)."""
import unittest
from unittest.mock import AsyncMock, patch

from app.errors import ApiError
from app.ingest import router as ingest_router

CLAIMS = {"user_id": 9, "store_id": 1, "role": "OWNER"}


class CancelRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_finished_job_is_409(self):
        with patch("app.ingest.router.job_repo.cancel_job", new=AsyncMock(return_value=False)):
            with self.assertRaises(ApiError) as raised:
                await ingest_router.cancel_ingest_job(7, "DB", CLAIMS)
        self.assertEqual((raised.exception.status_code, raised.exception.code), (409, "JOB_NOT_ACTIVE"))

    async def test_cancel_returns_detail(self):
        with patch("app.ingest.router.job_repo.cancel_job", new=AsyncMock(return_value=True)) as cancel, \
             patch("app.ingest.router._job_detail", new=AsyncMock(return_value="DETAIL")):
            self.assertEqual(await ingest_router.cancel_ingest_job(7, "DB", CLAIMS), "DETAIL")
        cancel.assert_awaited_once_with("DB", 1, 7)

    async def test_opening_job_checks_stalled_first(self):
        stalled = AsyncMock(return_value=0)
        with patch("app.ingest.router.job_repo.fail_stalled_jobs", new=stalled), \
             patch("app.ingest.router._job_detail", new=AsyncMock(return_value="DETAIL")):
            await ingest_router.get_ingest_job(7, "DB", CLAIMS)
        stalled.assert_awaited_once_with("DB", 1, minutes=30)
