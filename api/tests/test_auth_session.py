"""90일 슬라이딩 세션 (이슈 #37)."""
import asyncio
import hashlib
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt

from app.auth import session

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
    access_token_expire_minutes=60, refresh_token_expire_days=90,
    auth_cookie_secure=True, origins=["https://askbuddy.kr"])


def _h(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class TokenDb:
    """auth_refresh_tokens 만 흉내 낸다. SQL 앞부분으로 동작을 고른다."""

    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.next_id = 1

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchval(self, sql, *args):
        if sql.lstrip().startswith("insert into auth_refresh_tokens"):
            user_id, token_hash, family_id, expires_at = args
            tid = self.next_id
            self.next_id += 1
            self.rows[tid] = dict(token_id=tid, user_id=user_id, token_hash=token_hash,
                                  family_id=family_id, expires_at=expires_at,
                                  revoked_at=None, replaced_by=None)
            return tid
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "from auth_refresh_tokens where token_hash" in sql:
            return next((dict(r) for r in self.rows.values() if r["token_hash"] == args[0]), None)
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith("select user_id from users"):
            return
        now = datetime.now(timezone.utc)
        if "replaced_by = $2" in sql:
            row = self.rows[args[0]]
            row.update(revoked_at=now, replaced_by=args[1])
        elif "where family_id = $1" in sql:
            for r in self.rows.values():
                if r["family_id"] == args[0] and r["revoked_at"] is None:
                    r["revoked_at"] = now
        elif "where user_id = $1" in sql:
            for r in self.rows.values():
                if r["user_id"] == args[0] and r["revoked_at"] is None:
                    r["revoked_at"] = now
        else:
            raise AssertionError(sql)


def run(coro):
    return asyncio.run(coro)


class SessionTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.auth.session.get_settings", "app.deps.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.db = TokenDb()

    def test_issue_stores_only_hash_with_90_day_expiry(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        row = self.db.rows[tid]
        self.assertEqual(row["token_hash"], _h(raw))
        self.assertNotIn(raw, str(row))
        left = row["expires_at"] - datetime.now(timezone.utc)
        self.assertAlmostEqual(left.total_seconds(), 90 * 86400, delta=60)

    def test_rotate_returns_new_token_and_revokes_old(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        user_id, new_raw = run(session.rotate_refresh(self.db, raw=raw))
        self.assertEqual(user_id, 7)
        self.assertNotEqual(new_raw, raw)
        old = self.db.rows[tid]
        self.assertIsNotNone(old["revoked_at"])
        new = next(r for r in self.db.rows.values() if r["token_hash"] == _h(new_raw))
        self.assertEqual(old["replaced_by"], new["token_id"])
        self.assertEqual(new["family_id"], old["family_id"])

    def test_reuse_within_grace_rejects_without_family_revoke(self):
        raw, _ = run(session.issue_refresh(self.db, user_id=7))
        _, new_raw = run(session.rotate_refresh(self.db, raw=raw))
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
        # 다른 탭이 받은 새 토큰은 여전히 쓸 수 있다
        user_id, _ = run(session.rotate_refresh(self.db, raw=new_raw))
        self.assertEqual(user_id, 7)

    def test_reuse_after_grace_revokes_whole_family(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        _, new_raw = run(session.rotate_refresh(self.db, raw=raw))
        self.db.rows[tid]["revoked_at"] = datetime.now(timezone.utc) - timedelta(seconds=31)
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=new_raw))

    def test_expired_and_unknown_rejected(self):
        raw, tid = run(session.issue_refresh(self.db, user_id=7))
        self.db.rows[tid]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw="nope"))

    def test_revoke_user_sessions(self):
        raw1, _ = run(session.issue_refresh(self.db, user_id=7))
        raw2, _ = run(session.issue_refresh(self.db, user_id=7))
        other, _ = run(session.issue_refresh(self.db, user_id=8))
        run(session.revoke_user_sessions(self.db, user_id=7))
        for raw in (raw1, raw2):
            with self.assertRaises(session.RefreshRejected):
                run(session.rotate_refresh(self.db, raw=raw))
        self.assertEqual(run(session.rotate_refresh(self.db, raw=other))[0], 8)

    def test_access_token_shape(self):
        token = session.create_access_token(user_id=7, role="STAFF", store_id=None)
        claims = jwt.decode(token, SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertEqual((claims["user_id"], claims["role"]), (7, "STAFF"))
        self.assertNotIn("store_id", claims)
        self.assertAlmostEqual(claims["exp"] - datetime.now(timezone.utc).timestamp(), 3600, delta=30)
        token = session.create_access_token(user_id=7, role="STAFF", store_id=3)
        self.assertEqual(jwt.decode(token, SETTINGS.jwt_secret, algorithms=["HS256"])["store_id"], 3)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import router as auth_router_module
from app.deps import get_db
from app.errors import install_error_handlers


class SessionApiTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.auth.session.get_settings", "app.deps.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.db = TokenDb()
        users = {7: {"user_id": 7, "name": "알바", "role": "STAFF"}}
        original_fetchrow = self.db.fetchrow

        async def fetchrow(sql, *args):
            if "from users where user_id" in sql:
                return users.get(args[0])
            return await original_fetchrow(sql, *args)

        async def fetchval(sql, *args, _orig=self.db.fetchval):
            if "from store_members" in sql:
                return 3
            return await _orig(sql, *args)

        self.db.fetchrow = fetchrow
        self.db.fetchval = fetchval
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app, base_url="https://api.askbuddy.kr")
        self.addCleanup(self.client.close)

    def _cookie(self):
        raw, _ = run(session.issue_refresh(self.db, user_id=7))
        self.client.cookies.set("ab_refresh", raw, domain="api.askbuddy.kr", path="/auth")
        return raw

    def test_refresh_rotates_cookie_and_returns_store_token(self):
        raw = self._cookie()
        res = self.client.post("/auth/refresh", headers={"Origin": "https://askbuddy.kr"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["user"], {"user_id": 7, "name": "알바", "role": "STAFF", "store_id": 3})
        set_cookie = res.headers["set-cookie"]
        self.assertIn("ab_refresh=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Path=/auth", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)
        self.assertNotIn(raw, set_cookie)

    def test_refresh_without_cookie_is_401(self):
        res = self.client.post("/auth/refresh", headers={"Origin": "https://askbuddy.kr"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"]["code"], "SESSION_EXPIRED")

    def test_refresh_from_foreign_origin_is_403(self):
        self._cookie()
        for headers in ({"Origin": "https://evil.example"}, {}):
            res = self.client.post("/auth/refresh", headers=headers)
            self.assertEqual(res.status_code, 403)

    def test_logout_revokes_and_clears(self):
        raw = self._cookie()
        res = self.client.post("/auth/logout", headers={"Origin": "https://askbuddy.kr"})
        self.assertEqual(res.status_code, 204)
        self.assertIn('ab_refresh=""', res.headers["set-cookie"])
        with self.assertRaises(session.RefreshRejected):
            run(session.rotate_refresh(self.db, raw=raw))
