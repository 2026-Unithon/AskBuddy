from __future__ import annotations

import unittest

from app.bootstrap.router import _default_destination, get_bootstrap
from app.errors import ApiError


class FakeDb:
    def __init__(self, *rows):
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query: str, *args):
        self.calls.append((query, args))
        return self.rows.pop(0)


class BootstrapTest(unittest.IsolatedAsyncioTestCase):
    def test_destinations(self):
        self.assertEqual(_default_destination("OWNER", False, False), "/owner/intent")
        self.assertEqual(_default_destination("OWNER", True, False), "/owner/upload")
        self.assertEqual(_default_destination("OWNER", True, True), "/owner/questions/v2")
        self.assertEqual(_default_destination("STAFF", False, False), "/staff/auth")
        self.assertEqual(_default_destination("STAFF", True, False), "/staff/roadmap")

    async def test_owner_without_store_goes_to_intent(self):
        db = FakeDb(
            {"user_id": 1, "name": "점주", "role": "OWNER"},
        )

        result = await get_bootstrap(db, {"user_id": 1, "role": "OWNER"})

        self.assertIsNone(result.store)
        self.assertEqual(result.default_destination, "/owner/intent")
        self.assertEqual(result.badges.waiting_questions, 0)

    async def test_completed_owner_gets_store_scoped_badges(self):
        db = FakeDb(
            {"user_id": 1, "name": "점주", "role": "OWNER"},
            {
                "store_id": 10,
                "member_role": "OWNER",
                "store_name": "테스트 카페",
                "guide_completed_at": "2026-09-10T00:00:00Z",
                "category_version": 4,
            },
            {"waiting_questions": 2, "pending_cards": 7},
        )

        result = await get_bootstrap(
            db, {"user_id": 1, "role": "OWNER", "store_id": 10}
        )

        self.assertEqual(result.default_destination, "/owner/questions/v2")
        self.assertTrue(result.store.guide_completed)
        self.assertEqual(result.store.category_version, 4)
        self.assertEqual(result.badges.pending_cards, 7)
        self.assertEqual(db.calls[-1][1], (10,))
        self.assertIn("knowledge_change_proposals", db.calls[-1][0])

    async def test_staff_with_store_goes_to_roadmap(self):
        db = FakeDb(
            {"user_id": 2, "name": "직원", "role": "STAFF"},
            {
                "store_id": 10,
                "member_role": "STAFF",
                "store_name": "테스트 카페",
                "guide_completed_at": None,
                "category_version": 1,
            },
            {"waiting_questions": 0, "pending_cards": 1},
        )

        result = await get_bootstrap(
            db, {"user_id": 2, "role": "STAFF", "store_id": 10}
        )

        self.assertEqual(result.default_destination, "/staff/roadmap")

    async def test_claimed_other_store_is_hidden(self):
        db = FakeDb(
            {"user_id": 1, "name": "점주", "role": "OWNER"},
            None,
        )

        with self.assertRaises(ApiError) as raised:
            await get_bootstrap(
                db, {"user_id": 1, "role": "OWNER", "store_id": 999}
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.code, "STORE_NOT_FOUND")

    async def test_stale_role_is_rejected(self):
        db = FakeDb({"user_id": 1, "name": "점주", "role": "OWNER"})

        with self.assertRaises(ApiError) as raised:
            await get_bootstrap(db, {"user_id": 1, "role": "STAFF"})

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.code, "AUTH_INVALID")


if __name__ == "__main__":
    unittest.main()
