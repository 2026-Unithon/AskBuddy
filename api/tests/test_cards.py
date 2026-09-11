from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.cards.repository import _status_clause
from app.cards.router import _identity, _json_object, require_owner
from app.cards.schemas import CategoryUpdateRequest, DraftUpdateRequest
from app.errors import ApiError


class CardsTest(unittest.IsolatedAsyncioTestCase):
    def test_staff_queries_are_always_approved(self):
        clause, args = _status_clause("excluded", staff=True)
        self.assertIn("APPROVED", clause)
        self.assertEqual(args, [])

    def test_needs_review_includes_reason(self):
        clause, _ = _status_clause("needs_review", staff=False)
        self.assertIn("needs_review_reason is not null", clause)

    def test_draft_text_is_trimmed(self):
        req = DraftUpdateRequest(
            title="  우유 위치  ", content="  둘째 선반  ", expected_version_id=1
        )
        self.assertEqual(req.title, "우유 위치")
        self.assertEqual(req.content, "둘째 선반")

    def test_category_update_requires_positive_id(self):
        with self.assertRaises(ValidationError):
            CategoryUpdateRequest(
                category_id=0, expected_updated_at=datetime.now(timezone.utc)
            )

    def test_category_update_requires_timezone(self):
        with self.assertRaises(ValidationError):
            CategoryUpdateRequest(category_id=1, expected_updated_at=datetime.now())

    def test_json_objects_support_asyncpg_text(self):
        self.assertEqual(_json_object('{"timestamp_sec": 4}'), {"timestamp_sec": 4})

    def test_identity_requires_store(self):
        with self.assertRaises(ApiError) as raised:
            _identity({"user_id": 1, "role": "OWNER"})
        self.assertEqual(raised.exception.code, "STORE_REQUIRED")

    async def test_staff_cannot_mutate_cards(self):
        with self.assertRaises(ApiError) as raised:
            await require_owner({"user_id": 2, "store_id": 1, "role": "STAFF"})
        self.assertEqual(raised.exception.code, "OWNER_ONLY")


if __name__ == "__main__":
    unittest.main()
