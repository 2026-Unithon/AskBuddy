from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.categories.classifier import classify_cards
from app.categories.router import _identity, require_owner
from app.categories.schemas import CreateCategoryRequest
from app.errors import ApiError


class CategoriesTest(unittest.IsolatedAsyncioTestCase):
    def test_category_name_is_normalized(self):
        request = CreateCategoryRequest(name="  고객   응대  ", sort_order=3)
        self.assertEqual(request.name, "고객 응대")

    def test_identity_requires_jwt_store(self):
        with self.assertRaises(ApiError) as raised:
            _identity({"user_id": 1, "role": "OWNER"})
        self.assertEqual(raised.exception.code, "STORE_REQUIRED")

    async def test_staff_cannot_mutate_categories(self):
        with self.assertRaises(ApiError) as raised:
            await require_owner({"user_id": 2, "store_id": 1, "role": "STAFF"})
        self.assertEqual(raised.exception.code, "OWNER_ONLY")

    async def test_mock_classifier_keeps_current_and_uses_other_for_deleted(self):
        cards = [
            {"card_id": 1, "category_name": "오픈업무"},
            {"card_id": 2, "category_name": "삭제된 분류"},
        ]
        with patch(
            "app.categories.classifier.get_settings",
            return_value=SimpleNamespace(ingest_mode="mock"),
        ):
            result = await classify_cards(cards, ["오픈업무", "기타"])
        self.assertEqual(result, {1: "오픈업무", 2: "기타"})


if __name__ == "__main__":
    unittest.main()
