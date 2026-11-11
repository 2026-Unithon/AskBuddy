"""계획 8: 설정, 계정. 실제 스키마. PLAN7_TEST_DB_URL 이 없으면 건너뛴다."""
import unittest

from tests._plan7_db import ENABLED, SKIP_REASON, drop_db, fresh_db, seed_store


@unittest.skipUnless(ENABLED, SKIP_REASON)
class SchemaTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_columns_exist(self):
        cols = {(r["table_name"], r["column_name"]) for r in await self.conn.fetch(
            "select table_name, column_name from information_schema.columns where table_schema = 'public'")}
        for pair in [("auth_refresh_tokens", "user_agent"), ("user_feedback", "body")]:
            self.assertIn(pair, cols)
        # 기한은 stores.purge_due_at 한 곳에만 둔다(계획 9 R3)
        self.assertNotIn(("users", "withdrawal_due_at"), cols)

    async def test_feedback_is_in_the_purge_list(self):
        from app.bootstrap import purge
        self.assertIn("user_feedback", purge.PURGE_ORDER)

    async def test_feedback_checks(self):
        store = await seed_store(self.conn)
        user = await self.conn.fetchval("insert into users (name, role) values ('알바', 'STAFF') returning user_id")
        with self.assertRaises(Exception):
            await self.conn.execute("insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, 'BUG', 'x')", store, user)
        with self.assertRaises(Exception):
            await self.conn.execute("insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, 'IDEA', '')", store, user)


from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)


@unittest.skipUnless(ENABLED, SKIP_REASON)
class AccountTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn, self.name = await fresh_db()
        self.store = await seed_store(self.conn)
        q = "insert into users (name, role) values ($1, $2) returning user_id"
        self.owner = await self.conn.fetchval(q, "사장", "OWNER")
        self.staff = await self.conn.fetchval(q, "알바", "STAFF")
        await self.conn.execute("update stores set owner_id = $2 where store_id = $1", self.store, self.owner)
        for uid, role in [(self.owner, "OWNER"), (self.staff, "STAFF")]:
            await self.conn.execute("insert into store_members (store_id, user_id, member_role) values ($1, $2, $3)", self.store, uid, role)
        await self.conn.execute("insert into user_identities (user_id, provider, provider_user_id) values ($1, 'KAKAO', 'k-staff')", self.staff)

    async def asyncTearDown(self):
        await drop_db(self.conn, self.name)

    async def test_leave_store_removes_membership_keeps_account(self):
        from app.bootstrap import account
        await account.leave_store(self.conn, store_id=self.store, user_id=self.staff)
        self.assertIsNotNone(await self.conn.fetchval("select removed_at from store_members where user_id = $1", self.staff))
        self.assertIsNone(await self.conn.fetchval("select deleted_at from users where user_id = $1", self.staff))

    async def test_owner_cannot_leave(self):
        from app.bootstrap import account
        with self.assertRaises(account.OwnerCannotLeave):
            await account.leave_store(self.conn, store_id=self.store, user_id=self.owner)

    async def test_staff_withdraw_anonymizes_and_frees_kakao(self):
        from app.bootstrap import account
        await account.withdraw_staff(self.conn, user_id=self.staff)
        row = await self.conn.fetchrow("select name, deleted_at, avatar_path from users where user_id = $1", self.staff)
        self.assertEqual(row["name"], "탈퇴한 사용자")
        self.assertIsNotNone(row["deleted_at"])
        self.assertIsNone(row["avatar_path"])
        self.assertEqual(await self.conn.fetchval("select count(*) from user_identities where user_id = $1", self.staff), 0)
        self.assertIsNotNone(await self.conn.fetchval("select removed_at from store_members where user_id = $1", self.staff))

    async def test_owner_withdraw_closes_store_then_cancel_reopens(self):
        from app.bootstrap import account
        from app.config import get_settings
        days = get_settings().withdrawal_grace_days
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        row = await self.conn.fetchrow("select closing_at, purge_due_at from stores where store_id = $1", self.store)
        self.assertEqual((row["closing_at"], row["purge_due_at"]), (NOW, NOW + timedelta(days=days)))
        self.assertEqual(await account.withdrawal_due(self.conn, user_id=self.owner), NOW + timedelta(days=days))
        await account.cancel_withdrawal(self.conn, user_id=self.owner, now=NOW + timedelta(days=days - 1))
        row = await self.conn.fetchrow("select closing_at, purge_due_at from stores where store_id = $1", self.store)
        self.assertEqual((row["closing_at"], row["purge_due_at"]), (None, None))
        self.assertIsNone(await account.withdrawal_due(self.conn, user_id=self.owner))

    async def test_withdraw_owner_refuses_someone_elses_store(self):
        from app.bootstrap import account
        with self.assertRaises(LookupError):
            await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.staff, now=NOW)
        self.assertIsNone(await self.conn.fetchval("select closing_at from stores where store_id = $1", self.store))

    async def test_cancel_after_due_fails(self):
        from app.bootstrap import account
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        with self.assertRaises(account.WithdrawalExpired):
            await account.cancel_withdrawal(self.conn, user_id=self.owner, now=NOW + timedelta(days=31))

    async def test_withdraw_revokes_every_member_session(self):
        from app.auth import session
        from app.bootstrap import account
        for uid in (self.owner, self.staff):
            await session.issue_refresh(self.conn, user_id=uid)
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        self.assertEqual(await self.conn.fetchval("select count(*) from auth_refresh_tokens where revoked_at is null"), 0)

    async def test_withdrawn_store_is_purged_once_the_grace_has_passed(self):
        # 탈퇴(이 계획)와 파기(계획 9)가 이어지는지 본다. DB 시계가 기준이라 탈퇴 시각을 과거로 준다
        import asyncpg
        from datetime import datetime as dt
        from app.bootstrap import account, purge
        from app.config import get_settings
        from tests._plan7_db import _db_url
        days = get_settings().withdrawal_grace_days
        await self.conn.execute("insert into user_feedback (store_id, user_id, kind, body) values ($1, $2, 'IDEA', '의견')", self.store, self.staff)
        await self.conn.execute("set session_replication_role = origin")
        deleted = []

        async def fake(bucket, paths):
            deleted.append(bucket)
        pool = await asyncpg.create_pool(_db_url(self.name), min_size=1, max_size=2)
        try:
            await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=dt.now(timezone.utc) - timedelta(days=days - 1))
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [])
            await account.cancel_withdrawal(self.conn, user_id=self.owner, now=dt.now(timezone.utc))
            await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=dt.now(timezone.utc) - timedelta(days=days, seconds=1))
            self.assertEqual(await purge.purge_due_stores(pool, delete_objects=fake), [self.store])
        finally:
            await pool.close()
        self.assertEqual(await self.conn.fetchval("select count(*) from users where user_id = any($1::bigint[])", [self.owner, self.staff]), 0)
        self.assertEqual(await self.conn.fetchval("select count(*) from user_feedback where store_id = $1", self.store), 0)
        self.assertEqual(await self.conn.fetchval("select store_name from stores where store_id = $1", self.store), "삭제된 매장")
        with self.assertRaises(account.WithdrawalExpired):
            await account.cancel_withdrawal(self.conn, user_id=self.owner, now=dt.now(timezone.utc))

    async def test_closed_store_blocks_every_request(self):
        from app.bootstrap import account
        from app.deps import get_store_id
        from app.errors import ApiError
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        with self.assertRaises(ApiError) as staff_err:
            await get_store_id({"store_id": self.store, "user_id": self.staff, "role": "STAFF"}, self.conn)
        self.assertEqual(staff_err.exception.code, "STORE_CLOSED")
        with self.assertRaises(ApiError) as owner_err:
            await get_store_id({"store_id": self.store, "user_id": self.owner, "role": "OWNER"}, self.conn)
        self.assertEqual(owner_err.exception.code, "OWNER_WITHDRAWING")

    async def test_api_claims_routes_are_blocked_too(self):
        # cards·ingest 등은 get_store_id 를 거치지 않고 ApiClaims 의 store_id 만 쓴다. 남은 access token 으로 쓰면 안 된다
        from app.bootstrap import account
        from app.errors import ApiError, check_store_open
        await check_store_open({"store_id": self.store, "user_id": self.staff, "role": "STAFF"}, self.conn)
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        with self.assertRaises(ApiError) as err:
            await check_store_open({"store_id": self.store, "user_id": self.staff, "role": "STAFF"}, self.conn)
        self.assertEqual(err.exception.code, "STORE_CLOSED")
        # 매장이 없는 토큰(가입 직후)은 그대로 통과
        await check_store_open({"user_id": self.staff, "role": "STAFF"}, self.conn)

    async def test_bootstrap_sends_withdrawing_owner_to_cancel_screen(self):
        from app.bootstrap import account
        from app.bootstrap.router import get_bootstrap
        from app.errors import ApiError
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=NOW)
        out = await get_bootstrap(self.conn, {"store_id": self.store, "user_id": self.owner, "role": "OWNER"})
        self.assertEqual(out.default_destination, "/withdrawal")
        self.assertIsNotNone(out.withdrawal_due_at)
        with self.assertRaises(ApiError) as err:
            await get_bootstrap(self.conn, {"store_id": self.store, "user_id": self.staff, "role": "STAFF"})
        self.assertEqual(err.exception.code, "STORE_CLOSED")

    async def test_kakao_login_sends_withdrawing_owner_to_cancel_screen(self):
        from app.auth.kakao_router import next_after_login
        from app.bootstrap import account
        self.assertEqual(await next_after_login(self.conn, user_id=self.owner, requested="/owner/cards"), "/owner/cards")
        await account.withdraw_owner(self.conn, store_id=self.store, user_id=self.owner, now=datetime.now(timezone.utc))
        self.assertEqual(await next_after_login(self.conn, user_id=self.owner, requested="/owner/cards"), "/withdrawal")
        self.assertEqual(await next_after_login(self.conn, user_id=self.staff, requested=None), None)

    async def test_sessions_list_and_revoke_only_mine(self):
        from app.auth import devices, session
        await session.issue_refresh(self.conn, user_id=self.staff, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Safari/604.1")
        await session.issue_refresh(self.conn, user_id=self.owner, user_agent="x")
        mine = await devices.list_sessions(self.conn, user_id=self.staff, current_family=None)
        self.assertEqual([d["label"] for d in mine], ["아이폰 Safari"])
        others = await devices.list_sessions(self.conn, user_id=self.owner, current_family=None)
        with self.assertRaises(LookupError):
            await devices.revoke(self.conn, user_id=self.staff, family_id=others[0]["family_id"])
        await devices.revoke(self.conn, user_id=self.staff, family_id=mine[0]["family_id"])
        self.assertEqual(await devices.list_sessions(self.conn, user_id=self.staff, current_family=None), [])
        # 남의 계열은 그대로 살아 있다
        self.assertEqual(len(await devices.list_sessions(self.conn, user_id=self.owner, current_family=None)), 1)

    async def test_rotation_keeps_device_and_current_flag(self):
        from app.auth import devices, session
        raw, _ = await session.issue_refresh(self.conn, user_id=self.staff, user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/131.0 Safari/537.36")
        _, new_raw = await session.rotate_refresh(self.conn, raw=raw)
        family = await devices.family_of(self.conn, raw=new_raw)
        rows = await devices.list_sessions(self.conn, user_id=self.staff, current_family=family)
        self.assertEqual([(d["label"], d["current"]) for d in rows], [("Mac Chrome", True)])

    async def test_withdrawal_route_reports_grace_days_from_config(self):
        from app.bootstrap.account_router import get_withdrawal
        from app.config import get_settings
        out = await get_withdrawal(self.conn, self.owner)
        self.assertEqual(out, {"due_at": None, "grace_days": get_settings().withdrawal_grace_days})
