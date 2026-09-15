"""실제 JWT dependency와 라우터를 통과하는 매장 격리 API 테스트."""
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import create_token, get_db
from app.reg.router import router


class StoreDb:
    def __init__(self):
        self.role = "STAFF"
        self.calls = []

    async def fetchrow(self, sql, store_id, other):
        self.calls.append((sql, store_id, other))
        if "store_members" in sql:
            return {"member_role": self.role} if other == 10 and self.role else None
        if "from stores" in sql:
            return {"store_id": store_id} if other in (str(store_id), f"store-{store_id}") else None
        raise AssertionError(sql)

    async def fetch(self, sql, store_id):
        self.calls.append((sql, store_id))
        assert "v.version_id = c.published_version_id" in sql
        assert "c.review_status = 'APPROVED'" in sql
        return [dict(id=store_id * 100, title="합성 카드", content="승인 원문",
                     category="", confidence=100, is_verified=True)]


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.db = StoreDb()
        self.settings = patch("app.deps.get_settings", return_value=SimpleNamespace(
            jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256"))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        app = FastAPI()
        app.include_router(router, prefix="/reg")

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        pool = SimpleNamespace(acquire=asynccontextmanager(fake_db))
        @asynccontextmanager
        async def lease(*args):
            yield "synthetic"
        for name, value in (("get_pool", lambda: pool), ("request_lease", lease)):
            item = patch("app.reg.router." + name, value)
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def headers(self, **changes):
        claims = dict(store_id=1, user_id=10, role="STAFF",
                      exp=datetime.now(timezone.utc) + timedelta(minutes=5))
        claims.update(changes)
        if claims["exp"] is None:
            claims.pop("exp")
        return {"Authorization": "Bearer " + create_token(claims)}

    def test_no_token_and_invalid_tokens_never_query_db(self):
        self.assertEqual(self.client.get("/reg/cards?store_id=1").status_code, 401)
        for changes in (dict(exp=None), dict(exp=1)):
            self.assertEqual(self.client.get("/reg/cards?store_id=1", headers=self.headers(**changes)).status_code, 401)
        self.assertEqual(self.db.calls, [])

    def test_membership_removal_and_role_change(self):
        for role in (None, "OWNER"):
            self.db.role = role
            self.assertEqual(self.client.get("/reg/cards?store_id=1", headers=self.headers()).status_code, 403)

    def test_two_store_lists_and_cross_store_404(self):
        for sid in (1, 2):
            response = self.client.get(f"/reg/cards?store_id=store-{sid}", headers=self.headers(store_id=sid))
            self.assertEqual(response.status_code, 200)
            self.assertEqual([c["id"] for c in response.json()["cards"]], [sid * 100])
        response = self.client.get("/reg/cards?store_id=1", headers=self.headers(store_id=2))
        self.assertEqual(response.status_code, 404)

    def test_retrieve_checks_store_before_embedding(self):
        search = AsyncMock(return_value=dict(kind="miss", reason="no_match", message="없음"))
        with patch("app.reg.router.retrieve_question", search):
            response = self.client.post("/reg/retrieve", json=dict(store_id="2", question="우유"), headers=self.headers())
            self.assertEqual(response.status_code, 404)
            search.assert_not_called()
            response = self.client.post("/reg/retrieve", json=dict(store_id="1", question="우유"), headers=self.headers())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(search.call_args.args[1], 1)

    def test_invalid_identity_and_validation(self):
        for value in (True, 0, -1, "01", "9223372036854775808", 1.5):
            response = self.client.get("/reg/cards?store_id=1", headers=self.headers(store_id=value))
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/reg/retrieve", json={}, headers=self.headers()).status_code, 422)
