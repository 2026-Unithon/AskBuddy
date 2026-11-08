"""계획 7 Task 9: 이름 고치기·합류 승인 되돌리기·카테고리 순서와 이름. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store

from app.bootstrap import profile
from app.categories import repository as categories_repo
from app.members import repository as members_repo


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SmallFeaturesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        self.owner = await self.conn.fetchval("insert into users (name, role) values ('사장', 'OWNER') returning user_id")
        self.staff = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_rename_user_and_store(self):
        await profile.rename_user(self.conn, self.staff, "새 이름")
        await profile.rename_store(self.conn, self.store, "새 매장")
        self.assertEqual(await self.conn.fetchval("select name from users where user_id = $1", self.staff), "새 이름")
        self.assertEqual(await self.conn.fetchval("select store_name from stores where store_id = $1", self.store), "새 매장")

    async def test_undo_approve_puts_request_back_and_removes_member(self):
        request = await self.conn.fetchval(
            "insert into store_join_requests (store_id, user_id, status) values ($1, $2, 'PENDING') returning request_id", self.store, self.staff)
        await members_repo.approve(self.conn, store_id=self.store, request_id=request, owner_id=self.owner)
        await members_repo.undo_approve(self.conn, store_id=self.store, request_id=request, owner_id=self.owner)
        self.assertEqual(await self.conn.fetchval("select status from store_join_requests where request_id = $1", request), "PENDING")
        self.assertIsNotNone(await self.conn.fetchval(
            "select removed_at from store_members where store_id = $1 and user_id = $2", self.store, self.staff))
        with self.assertRaises(members_repo.AlreadyDecided):
            await members_repo.undo_approve(self.conn, store_id=self.store, request_id=request, owner_id=self.owner)

    async def test_undo_approve_expires(self):
        request = await self.conn.fetchval(
            "insert into store_join_requests (store_id, user_id, status, decided_at) values ($1, $2, 'APPROVED', now() - interval '11 minutes') returning request_id",
            self.store, self.staff)
        with self.assertRaises(members_repo.AlreadyDecided):
            await members_repo.undo_approve(self.conn, store_id=self.store, request_id=request, owner_id=self.owner)

    async def test_category_order_and_rename(self):
        ids = [await self.conn.fetchval("insert into task_categories (store_id, category_name, sort_order) values ($1, $2, $3) returning category_id", self.store, n, i)
               for i, n in enumerate(["음료", "마감", "재고"])]
        await categories_repo.set_order(self.conn, self.store, [ids[2], ids[0], ids[1]])
        rows = await self.conn.fetch("select category_id from task_categories where store_id = $1 order by sort_order", self.store)
        self.assertEqual([r["category_id"] for r in rows], [ids[2], ids[0], ids[1]])
        renamed = await categories_repo.rename(self.conn, self.store, ids[0], "음료 레시피")
        self.assertEqual(renamed["category_name"], "음료 레시피")
        with self.assertRaises(categories_repo.NameTaken):
            await categories_repo.rename(self.conn, self.store, ids[1], "음료 레시피".upper())
        self.assertIsNone(await categories_repo.rename(self.conn, self.store + 999, ids[1], "다른 매장"))

    async def test_routes_on_real_schema(self):
        from app.bootstrap.router import RenameRequest, rename_me, rename_store
        from app.categories.router import order_categories, update_category
        from app.categories.schemas import CategoryOrderRequest, UpdateCategoryRequest
        from app.errors import ApiError
        owner = {"user_id": self.owner, "store_id": self.store, "role": "OWNER"}
        await rename_me(RenameRequest(name="  김   사장 "), self.conn, owner)
        self.assertEqual(await self.conn.fetchval("select name from users where user_id = $1", self.owner), "김 사장")
        with self.assertRaises(ApiError):
            await rename_store(RenameRequest(name="남의 매장"), self.conn, {**owner, "role": "STAFF"})
        a = await self.conn.fetchval("insert into task_categories (store_id, category_name) values ($1, 'Coffee') returning category_id", self.store)
        b = await self.conn.fetchval("insert into task_categories (store_id, category_name) values ($1, '마감') returning category_id", self.store)
        with self.assertRaises(ApiError) as raised:
            await update_category(b, UpdateCategoryRequest(name="coffee"), self.conn, owner)
        self.assertEqual(raised.exception.status_code, 409)
        result = await update_category(b, UpdateCategoryRequest(name="마감 청소", kind="TASK"), self.conn, owner)
        self.assertEqual((result.category.name, result.category.kind), ("마감 청소", "TASK"))
        await order_categories(CategoryOrderRequest(ids=[b, a]), self.conn, owner)
        self.assertEqual([r["category_id"] for r in await self.conn.fetch(
            "select category_id from task_categories where store_id = $1 order by sort_order", self.store)], [b, a])
