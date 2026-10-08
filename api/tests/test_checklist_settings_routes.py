"""P5 화면에서 현재 설정을 복원하는 조회 경계 검증."""
from datetime import time
import unittest
from unittest.mock import AsyncMock, patch

from app.checklist.router import Member, get_me, get_settings
from app.errors import ApiError


class SettingsReadsTest(unittest.IsolatedAsyncioTestCase):
    def member(self, role):
        return Member(store_id=42, user_id=7, member_id=9, role=role, personal=False,
                      timezone="Asia/Seoul", day_starts_at=time(3, 30), staff_records_visible=False)

    async def test_settings_uses_persisted_values(self):
        claims = {"store_id": 42, "user_id": 7, "role": "OWNER"}
        db = object()
        with patch("app.checklist.router.require_member", AsyncMock(return_value=self.member("OWNER"))) as auth:
            result = await get_settings(db, claims)
            auth.assert_awaited_once_with(db, claims)
        self.assertEqual(result, {"business_day_starts_at": "03:30", "staff_records_visible": False, "timezone": "Asia/Seoul"})

    async def test_staff_cannot_read_owner_settings(self):
        with patch("app.checklist.router.require_member", AsyncMock(return_value=self.member("STAFF"))):
            with self.assertRaises(ApiError) as raised:
                await get_settings(object(), {"role": "STAFF"})
        self.assertEqual(raised.exception.status_code, 403)

    async def test_me_uses_authenticated_members_preference(self):
        claims = {"store_id": 42, "user_id": 7, "role": "STAFF"}
        db = object()
        with patch("app.checklist.router.require_member", AsyncMock(return_value=self.member("STAFF"))) as auth:
            self.assertEqual(await get_me(db, claims), {"personal_records_enabled": False})
            auth.assert_awaited_once_with(db, claims)
