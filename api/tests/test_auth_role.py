"""역할 미정 계정과 역할 선택 (이슈 #37)."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import router as auth_router_module
from app.auth import session
from app.bootstrap.router import _default_destination
from app.deps import create_token, get_db
from app.errors import install_error_handlers

SETTINGS = SimpleNamespace(jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256",
                           access_token_expire_minutes=60, refresh_token_expire_days=90,
                           auth_cookie_secure=True, origins=["https://askbuddy.kr"])


def bearer(**claims):
    claims.setdefault("exp", datetime.now(timezone.utc) + timedelta(minutes=5))
    return {"Authorization": "Bearer " + create_token(claims)}


class RoleDb:
    def __init__(self):
        self.users = {5: {"user_id": 5, "name": "새사람", "role": None}}

    async def fetchval(self, sql, *args):
        if sql.lstrip().startswith("update users set role"):
            user = self.users.get(args[0])
            if user and user["role"] is None:
                user["role"] = args[1]
                return args[0]
            return None
        if "from store_members" in sql:
            return None
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        if "from users where user_id" in sql:
            return self.users.get(args[0])
        raise AssertionError(sql)


class RoleSelectTest(unittest.TestCase):
    def setUp(self):
        for target in ("app.deps.get_settings", "app.auth.session.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        self.db = RoleDb()
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def test_unset_token_has_no_role_claim(self):
        claims = jwt.decode(session.create_access_token(user_id=5, role=None, store_id=None),
                            SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertNotIn("role", claims)

    def test_choose_owner_once(self):
        res = self.client.post("/auth/role", json={"role": "OWNER"}, headers=bearer(user_id=5))
        self.assertEqual(res.status_code, 200)
        claims = jwt.decode(res.json()["token"], SETTINGS.jwt_secret, algorithms=["HS256"])
        self.assertEqual(claims["role"], "OWNER")
        again = self.client.post("/auth/role", json={"role": "STAFF"}, headers=bearer(user_id=5, role="OWNER"))
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["error"]["code"], "ROLE_ALREADY_SET")
        self.assertEqual(self.db.users[5]["role"], "OWNER")

    def test_rejects_other_roles(self):
        res = self.client.post("/auth/role", json={"role": "OPERATOR"}, headers=bearer(user_id=5))
        self.assertEqual(res.status_code, 422)

    def test_bootstrap_destination_for_unset_role(self):
        self.assertEqual(_default_destination(None, False, False), "/auth/role")
        self.assertEqual(_default_destination("STAFF", False, False), "/staff/pending")
        self.assertEqual(_default_destination("OWNER", False, False), "/owner/intent")

class LoginWithoutRoleTest(unittest.TestCase):
    def setUp(self):
        import bcrypt
        for target in ("app.deps.get_settings", "app.auth.session.get_settings"):
            p = patch(target, return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        hashed = bcrypt.hashpw(b"secret1", bcrypt.gensalt(rounds=4)).decode()

        class Db:
            async def fetchrow(self, sql, *args):
                if "from users u" in sql:
                    return {"user_id": 7, "name": "알바", "email": args[0], "role": "STAFF",
                            "password_hash": hashed, "store_id": 3}
                raise AssertionError(sql)

        async def start_session(db, response, *, user_id):
            response.set_cookie("ab_refresh", "x")

        q = patch("app.auth.router.start_session", side_effect=start_session)
        q.start()
        self.addCleanup(q.stop)
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(auth_router_module.router, prefix="/auth")
        db = Db()

        async def fake_db():
            yield db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)

    def test_login_without_role(self):
        res = self.client.post("/auth/login", json={"email": "a@example.com", "password": "secret1"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "STAFF")

    def test_old_web_sending_wrong_role_still_logs_in(self):
        # 단일 로그인 화면이라 역할로 막지 않는다. 역할은 DB 값이 정한다
        res = self.client.post("/auth/login", json={"email": "a@example.com", "password": "secret1", "role": "OWNER"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["user"]["role"], "STAFF")
