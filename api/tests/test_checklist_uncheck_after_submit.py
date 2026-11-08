"""제출한 뒤 체크를 풀면 제출 기록의 개수도 따라 줄어든다(사용자 실화면 2026-11-08: 풀어도 100% 유지)."""
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from app.checklist import router as checklist_router
from app.checklist.schemas import CheckRequest
from app.checklist.scope import ChecklistCard, Scope

MOD = "app.checklist.router"
TODAY = date(2026, 11, 8)
CARDS = [ChecklistCard(card_id=1, card_version_id=11, title="메뉴 A", lines=("메뉴 A",), common=True, shift_ids=frozenset()),
         ChecklistCard(card_id=2, card_version_id=22, title="메뉴 B", lines=("메뉴 B",), common=True, shift_ids=frozenset())]


class Db:
    @asynccontextmanager
    async def transaction(self):
        yield


class Member:
    store_id, user_id, personal = 1, 7, False


class UncheckAfterSubmitTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        context = (TODAY, None, None, Scope(all=True, shift_ids=()), CARDS, True)
        self.update = AsyncMock()
        self.patches = [
            patch(f"{MOD}.require_member", new=AsyncMock(return_value=Member())),
            patch(f"{MOD}._context", new=AsyncMock(return_value=context)),
            patch(f"{MOD}._now", new=lambda: datetime(2026, 11, 8, 3, tzinfo=timezone.utc)),
            patch(f"{MOD}.date_policy", new=lambda *a, **k: False),
            patch(f"{MOD}.repo.apply_checks", new=AsyncMock()),
            patch(f"{MOD}.repo.checked_keys", new=AsyncMock(return_value={(11, 1)})),
            patch(f"{MOD}.repo.get_submission", new=AsyncMock(return_value={"done_lines": 2, "total_lines": 2})),
            patch(f"{MOD}.repo.update_submission_counts", new=self.update),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_uncheck_after_submit_updates_counts(self):
        body = CheckRequest(business_date=TODAY, card_version_id=22, line_no=1, checked=False)
        await checklist_router.put_check(body, Db(), {"user_id": 7, "store_id": 1, "role": "STAFF"})
        self.update.assert_awaited_once_with(unittest.mock.ANY, 1, TODAY, 7, total=2, done=1)


if __name__ == "__main__":
    unittest.main()
