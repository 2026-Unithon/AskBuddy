"""계획 7 Task 2: 카테고리 종류는 AI 판단(입구 분류 source_logic)으로 채우고 사장님 값은 덮지 않는다.

실제 스키마(일회용 DB)에서 돈다. PLAN7_TEST_DB_URL 이 없으면 건너뛴다.
"""
import json
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.categories import repository as categories_repo
from app.checklist import repository as checklist_repo


async def _category(conn, store_id, name, kind=None, kind_source=None):
    return await conn.fetchval(
        "insert into task_categories (store_id, category_name, kind, kind_source) values ($1, $2, $3, $4) returning category_id",
        store_id, name, kind, kind_source)


async def _source(conn, store_id, logic):
    source_id = await conn.fetchval(
        "insert into sources (store_id, uploaded_by, source_type) values ($1, 1, 'SCAN') returning source_id", store_id)
    if logic:
        await conn.execute(
            "insert into intake_route_decisions (store_id, source_id, entry, normalizer, sample_summary, sample_hash, "
            "model_sections, decisions, source_decision, source_logic) "
            "values ($1, $2, 'UPLOAD', 'DOC_TEXT', '{}', repeat('0', 64), '[]', '[]', '{}', $3)",
            store_id, source_id, logic)
    return source_id


async def _card(conn, store_id, category_id, source_id=None):
    return await conn.fetchval(
        "insert into knowledge_cards (store_id, category_id, source_id) values ($1, $2, $3) returning card_id",
        store_id, category_id, source_id)


@unittest.skipUnless(ENABLED, SKIP_REASON)
class CategoryKindTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_ai_sets_kind_from_source_logic(self):
        for logic, kind in (("RECIPE", "RECIPE"), ("PROCEDURE", "TASK"), ("REFERENCE", "INFO"), ("NOTICE", "INFO")):
            category = await _category(self.conn, self.store, f"카테고리 {logic}")
            card = await _card(self.conn, self.store, category, await _source(self.conn, self.store, logic))
            await categories_repo.fill_kind_from_card(self.conn, self.store, card)
            row = await self.conn.fetchrow("select kind, kind_source from task_categories where category_id = $1", category)
            self.assertEqual((row["kind"], row["kind_source"]), (kind, "AI"), logic)

    async def test_owner_kind_is_not_overwritten(self):
        category = await _category(self.conn, self.store, "음료", "TASK", "OWNER")
        card = await _card(self.conn, self.store, category, await _source(self.conn, self.store, "RECIPE"))
        await categories_repo.fill_kind_from_card(self.conn, self.store, card)
        self.assertEqual(await self.conn.fetchval("select kind from task_categories where category_id = $1", category), "TASK")

    async def test_no_route_leaves_kind_empty(self):
        category = await _category(self.conn, self.store, "기타")
        card = await _card(self.conn, self.store, category, await _source(self.conn, self.store, None))
        await categories_repo.fill_kind_from_card(self.conn, self.store, card)
        self.assertIsNone(await self.conn.fetchval("select kind from task_categories where category_id = $1", category))

    async def test_other_store_card_changes_nothing(self):
        category = await _category(self.conn, self.store, "음료")
        card = await _card(self.conn, self.store, category, await _source(self.conn, self.store, "RECIPE"))
        await categories_repo.fill_kind_from_card(self.conn, self.store + 999, card)
        self.assertIsNone(await self.conn.fetchval("select kind from task_categories where category_id = $1", category))

    async def test_default_link_uses_kind_before_name(self):
        recipe_named_task = await _card(self.conn, self.store, await _category(self.conn, self.store, "음료 레시피", "TASK", "OWNER"))
        task_named_recipe = await _card(self.conn, self.store, await _category(self.conn, self.store, "오픈 마감", "RECIPE", "AI"))
        name_rule = await _card(self.conn, self.store, await _category(self.conn, self.store, "메뉴 제조"))
        info = await _card(self.conn, self.store, await _category(self.conn, self.store, "보관 위치", "INFO", "AI"))
        legacy_task = await _card(self.conn, self.store, await _category(self.conn, self.store, "마감 청소"))
        for card in (recipe_named_task, task_named_recipe, name_rule, info, legacy_task):
            await checklist_repo.add_default_link(self.conn, self.store, card)
        linked = [r["card_id"] for r in await self.conn.fetch("select card_id from checklist_cards where store_id = $1 order by card_id", self.store)]
        self.assertEqual(linked, [recipe_named_task, legacy_task])

    async def test_owner_patch_sets_kind_and_source(self):
        from app.categories.router import update_category
        from app.categories.schemas import UpdateCategoryRequest
        category = await _category(self.conn, self.store, "음료", "RECIPE", "AI")
        result = await update_category(category, UpdateCategoryRequest(kind="TASK"), self.conn, {"user_id": 1, "store_id": self.store, "role": "OWNER"})
        self.assertEqual(result.category.kind, "TASK")
        row = await self.conn.fetchrow("select kind, kind_source from task_categories where category_id = $1", category)
        self.assertEqual((row["kind"], row["kind_source"]), ("TASK", "OWNER"))

    async def test_owner_patch_other_store_is_404(self):
        from app.categories.router import update_category
        from app.categories.schemas import UpdateCategoryRequest
        from app.errors import ApiError
        category = await _category(self.conn, self.store, "음료")
        with self.assertRaises(ApiError) as raised:
            await update_category(category, UpdateCategoryRequest(kind="TASK"), self.conn, {"user_id": 1, "store_id": self.store + 999, "role": "OWNER"})
        self.assertEqual(raised.exception.status_code, 404)

    async def test_list_has_kind(self):
        from app.categories import repository as repo
        await _category(self.conn, self.store, "음료", "RECIPE", "AI")
        rows = await repo.list_current(self.conn, self.store)
        self.assertIn("RECIPE", [r["kind"] for r in rows])


if __name__ == "__main__":
    unittest.main()
