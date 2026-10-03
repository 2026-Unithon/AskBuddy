"""운영자 로그인·토큰 경계 (이슈 #33)."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bcrypt
import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import CurrentStoreId, create_token, get_db
from app.ops import router as ops_router_module
from app.ops.deps import OperatorId
from app.ops.lockout import LoginLimiter

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
    ops_token_expire_minutes=60, ops_login_max_failures=3, ops_login_lock_minutes=15)
PASSWORD_HASH = bcrypt.hashpw(b"right-password", bcrypt.gensalt(rounds=4)).decode()


class UsersDb:
    def __init__(self):
        self.users = {
            "ops@example.com": dict(user_id=1, name="운영자", email="ops@example.com",
                                    role="OPERATOR", password_hash=PASSWORD_HASH),
            "owner@example.com": dict(user_id=2, name="점주", email="owner@example.com",
                                      role="OWNER", password_hash=PASSWORD_HASH),
        }

    async def fetchrow(self, sql, *args):
        if "from users where email" in sql:
            return self.users.get(args[0])
        if "from users where user_id" in sql:
            return next((u for u in self.users.values() if u["user_id"] == args[0]), None)
        if "store_members" in sql:
            # 매장 1 에는 점주(user 2)만 소속돼 있다
            return {"member_role": "OWNER"} if args == (1, 2) else None
        raise AssertionError(sql)


class LoginLimiterTest(unittest.TestCase):
    def test_window_expiry_and_reset(self):
        now = [0.0]
        limiter = LoginLimiter(2, 60, clock=lambda: now[0])
        self.assertTrue(limiter.try_acquire("1.1.1.1", "a@example.com"))
        self.assertTrue(limiter.try_acquire("1.1.1.1", "a@example.com"))
        self.assertFalse(limiter.try_acquire("1.1.1.1", "a@example.com"))
        self.assertTrue(limiter.try_acquire("2.2.2.2", "a@example.com"))
        self.assertTrue(limiter.try_acquire("1.1.1.1", "b@example.com"))
        now[0] = 61
        self.assertTrue(limiter.try_acquire("1.1.1.1", "a@example.com"))
        limiter.reset("1.1.1.1", "a@example.com")
        self.assertTrue(limiter.try_acquire("1.1.1.1", "a@example.com"))
        self.assertTrue(limiter.try_acquire("1.1.1.1", "a@example.com"))
        self.assertFalse(limiter.try_acquire("1.1.1.1", "a@example.com"))


class OpsAuthTest(unittest.TestCase):
    def setUp(self):
        self.db = UsersDb()
        for target in ("app.deps.get_settings", "app.ops.deps.get_settings",
                       "app.ops.router.get_settings"):
            item = patch(target, return_value=SETTINGS)
            item.start()
            self.addCleanup(item.stop)
        limiter = patch.object(ops_router_module, "_limiter", LoginLimiter(3, 900))
        limiter.start()
        self.addCleanup(limiter.stop)

        app = FastAPI()
        app.include_router(ops_router_module.router, prefix="/ops")

        @app.get("/ops-only")
        async def ops_only(operator_id: OperatorId):
            return {"operator_id": operator_id}

        @app.get("/store-only")
        async def store_only(store_id: CurrentStoreId):
            return {"store_id": store_id}

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def login(self, email, password):
        return self.client.post("/ops/login", json={"email": email, "password": password})

    @staticmethod
    def bearer(token):
        return {"Authorization": "Bearer " + token}

    @staticmethod
    def later(minutes=5):
        return datetime.now(timezone.utc) + timedelta(minutes=minutes)

    def test_operator_login_returns_ops_token(self):
        res = self.login("OPS@example.com", "right-password")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["operator"], {"user_id": 1, "name": "운영자", "email": "ops@example.com"})
        claims = jwt.decode(body["token"], SETTINGS.jwt_secret, algorithms=["HS256"],
                            audience="askbuddy-ops")
        self.assertEqual(claims["role"], "OPERATOR")
        self.assertEqual(claims["user_id"], 1)
        self.assertNotIn("store_id", claims)
        self.assertAlmostEqual(claims["exp"] - datetime.now(timezone.utc).timestamp(), 3600, delta=30)
        res = self.client.get("/ops-only", headers=self.bearer(body["token"]))
        self.assertEqual(res.json(), {"operator_id": 1})

    def test_failures_share_one_401(self):
        for email, password in (("ops@example.com", "wrong-password"),
                                ("owner@example.com", "right-password"),
                                ("nobody@example.com", "right-password")):
            res = self.login(email, password)
            self.assertEqual(res.status_code, 401, email)
            self.assertEqual(res.json(), {"detail": "invalid credentials"}, email)

    def test_missing_account_still_runs_bcrypt(self):
        with patch("app.ops.router._verify_password", return_value=False) as verify:
            self.assertEqual(self.login("nobody@example.com", "right-password").status_code, 401)
        verify.assert_called_once()

    def test_repeated_failures_block_even_correct_password(self):
        for _ in range(3):
            self.assertEqual(self.login("ops@example.com", "wrong-password").status_code, 401)
        self.assertEqual(self.login("ops@example.com", "right-password").status_code, 429)
        # 다른 이메일은 막히지 않는다
        self.assertEqual(self.login("owner@example.com", "wrong-password").status_code, 401)

    def test_concurrent_failures_cannot_bypass_lockout(self):
        import asyncio
        import time

        import httpx

        calls = []

        def slow_verify(password, password_hash):
            calls.append(1)
            time.sleep(0.05)
            return False

        async def run():
            transport = httpx.ASGITransport(app=self.client.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await asyncio.gather(*[
                    c.post("/ops/login", json={"email": "ops@example.com", "password": "wrong-password"})
                    for _ in range(10)])

        with patch("app.ops.router._verify_password", side_effect=slow_verify):
            responses = asyncio.run(run())
        self.assertLessEqual(len(calls), SETTINGS.ops_login_max_failures)
        codes = sorted(r.status_code for r in responses)
        self.assertEqual(codes.count(401), SETTINGS.ops_login_max_failures)
        self.assertEqual(codes.count(429), 10 - SETTINGS.ops_login_max_failures)

    def test_operator_token_rejected_by_store_api(self):
        token = self.login("ops@example.com", "right-password").json()["token"]
        self.assertEqual(self.client.get("/store-only", headers=self.bearer(token)).status_code, 401)

    def test_product_token_rejected_by_operator_dependency(self):
        product = create_token(dict(store_id=1, user_id=2, role="OWNER", exp=self.later()))
        # 제품 토큰은 매장 API 에서는 통과한다 (대조)
        self.assertEqual(self.client.get("/store-only", headers=self.bearer(product)).status_code, 200)
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(product)).status_code, 401)
        self.assertEqual(self.client.get("/ops-only").status_code, 401)

    def test_ops_audience_with_other_role_rejected(self):
        forged = create_token(dict(user_id=2, role="OWNER", aud="askbuddy-ops", exp=self.later()))
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(forged)).status_code, 401)

    def test_expired_ops_token_rejected(self):
        expired = create_token(dict(user_id=1, role="OPERATOR", aud="askbuddy-ops",
                                    exp=datetime.now(timezone.utc) - timedelta(minutes=1)))
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(expired)).status_code, 401)

    def test_role_revoked_returns_403(self):
        token = self.login("ops@example.com", "right-password").json()["token"]
        self.db.users["ops@example.com"]["role"] = "OWNER"
        self.assertEqual(self.client.get("/ops-only", headers=self.bearer(token)).status_code, 403)


def test_operator_role_migration():
    path = Path(__file__).resolve().parents[2] / "supabase/migrations/20261003090000_ops_operator_role.sql"
    sql = path.read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "users_role_check" in code
    assert "'OWNER'" in code and "'STAFF'" in code and "'OPERATOR'" in code
    assert "store_members" not in code


def test_limiter_map_stays_within_cap():
    """키가 상한에 닿아도 맵 크기가 상한을 넘지 않는다. 요청마다 전체를 훑지 않는다."""
    now = [0.0]
    limiter = LoginLimiter(max_failures=5, window_seconds=900, clock=lambda: now[0], max_keys=10)
    for i in range(50):
        now[0] += 1
        assert limiter.try_acquire("1.1.1.1", f"u{i}@example.com")
        assert len(limiter._failures) <= 10
    # 가장 오래된 키가 밀려나고 최근 키는 남는다
    assert ("1.1.1.1", "u49@example.com") in limiter._failures
    assert ("1.1.1.1", "u0@example.com") not in limiter._failures
