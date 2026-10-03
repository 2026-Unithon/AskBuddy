"""/preflight 운영자 전용 전환과 진단 오진 수정 (이슈 #33)."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import preflight
from app.deps import create_token, get_db
from app.ops.deps import create_operator_token

SETTINGS = SimpleNamespace(
    jwt_secret="synthetic-test-key-" * 4, jwt_algorithm="HS256", ops_token_expire_minutes=60,
    env="test", ingest_mode="mock", origins=["http://localhost:3000"],
    embedding_model="emb", gemini_model="gem", stt_model="stt",
    retrieval_threshold=0.35, confidence_threshold=0.6, storage_bucket="sources",
    supabase_db_url="postgresql://user:secret@db.example:5432/postgres")


class RoleDb:
    def __init__(self):
        self.role = "OPERATOR"

    async def fetchrow(self, sql, user_id):
        assert "from users where user_id" in sql
        return {"role": self.role} if user_id == 1 else None


class PreflightAccessTest(unittest.TestCase):
    def setUp(self):
        self.db = RoleDb()
        for target in ("app.deps.get_settings", "app.ops.deps.get_settings",
                       "app.preflight.get_settings"):
            item = patch(target, return_value=SETTINGS)
            item.start()
            self.addCleanup(item.stop)
        ok = preflight._check("x", "live")
        for name, value in (("_probe_db", [ok]), ("_probe_storage", ok), ("_probe_openai", ok),
                            ("_probe_gemini", ok), ("_probe_retrieve", ok)):
            item = patch.object(preflight, name, AsyncMock(return_value=value))
            item.start()
            self.addCleanup(item.stop)
        app = FastAPI()
        app.include_router(preflight.router)

        async def fake_db():
            yield self.db

        app.dependency_overrides[get_db] = fake_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def get(self, token=None, deep=False):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.client.get("/preflight" + ("?deep=1" if deep else ""), headers=headers)

    def test_operator_gets_report(self):
        res = self.get(create_operator_token(1))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(self.get(create_operator_token(1), deep=True).status_code, 200)

    def test_no_token_and_product_token_rejected_without_probing(self):
        product = create_token(dict(store_id=1, user_id=1, role="OWNER",
                                    exp=datetime.now(timezone.utc) + timedelta(minutes=5)))
        self.assertEqual(self.get().status_code, 401)
        self.assertEqual(self.get(deep=True).status_code, 401)
        self.assertEqual(self.get(product).status_code, 401)
        self.assertEqual(self.get(product, deep=True).status_code, 401)
        preflight._probe_openai.assert_not_called()

    def test_revoked_role_gets_403(self):
        token = create_operator_token(1)
        self.db.role = "OWNER"
        self.assertEqual(self.get(token).status_code, 403)


class FakeConn:
    def __init__(self, missing):
        self.missing = missing
        self.counted = False

    async def fetch(self, sql, names):
        assert "to_regclass" in sql
        assert set(self.missing) <= set(names)
        return [{"name": name} for name in self.missing]

    async def fetchval(self, sql, *args):
        self.counted = True
        return 1

    async def close(self):
        pass


class ProbeDbTest(unittest.TestCase):
    def run_probe(self, connect):
        with patch.object(preflight.asyncpg, "connect", connect):
            return asyncio.run(preflight._probe_db(SETTINGS))

    def test_missing_tables_named_without_connection_hint(self):
        conn = FakeConn(["knowledge_entities", "fact_revisions"])
        checks = {c["name"]: c for c in self.run_probe(AsyncMock(return_value=conn))}
        self.assertEqual(checks["데이터베이스"]["state"], "live")
        self.assertEqual(checks["스키마"]["state"], "dead")
        self.assertIn("knowledge_entities", checks["스키마"]["detail"])
        self.assertIn("fact_revisions", checks["스키마"]["detail"])
        self.assertIn("migration", checks["스키마"]["fix"])
        self.assertFalse(any("SUPABASE_DB_URL" in c["fix"] for c in checks.values()))
        # 없는 테이블을 읽는 집계는 돌리지 않는다
        self.assertFalse(conn.counted)

    def test_full_schema_runs_counts(self):
        conn = FakeConn([])
        checks = {c["name"]: c for c in self.run_probe(AsyncMock(return_value=conn))}
        self.assertEqual(checks["스키마"]["state"], "live")
        self.assertTrue(conn.counted)
        self.assertIn("시드 데이터", checks)

    def test_connection_failure_is_only_connection_row(self):
        checks = self.run_probe(AsyncMock(side_effect=OSError("connection refused")))
        self.assertEqual([c["name"] for c in checks], ["데이터베이스"])
        self.assertEqual(checks[0]["state"], "dead")
        self.assertIn("SUPABASE_DB_URL", checks[0]["fix"])
        self.assertNotIn("secret", checks[0]["detail"])


class FakePool:
    def __init__(self, store_id):
        self.store_id = store_id

    async def fetchval(self, sql, slug):
        assert "store_slug" in sql and slug == "demo-cafe"
        return self.store_id


class ProbeRetrieveTest(unittest.TestCase):
    def run_probe(self, pool, retrieve):
        with patch.object(preflight, "get_pool", return_value=pool), \
             patch.object(preflight, "retrieve_question", retrieve), \
             patch.object(preflight, "DbUsageSink", lambda p: "sink"):
            return asyncio.run(preflight._probe_retrieve(SETTINGS))

    def test_missing_demo_store_is_warn_and_skips_search(self):
        retrieve = AsyncMock()
        check = self.run_probe(FakePool(None), retrieve)
        self.assertEqual(check["state"], "warn")
        self.assertIn("demo-cafe", check["detail"])
        retrieve.assert_not_called()

    def test_hit_calls_retrieve_directly_with_development_cost(self):
        retrieve = AsyncMock(return_value={"kind": "hit", "candidates": [{"score": 0.71}]})
        check = self.run_probe(FakePool(7), retrieve)
        self.assertEqual(check["state"], "live")
        self.assertIn("0.710", check["detail"])
        args, kwargs = retrieve.call_args
        self.assertEqual(args[1], 7)
        ctx = kwargs["usage_context"]
        self.assertEqual((ctx.store_id, ctx.cost_phase, ctx.cost_purpose, ctx.stage),
                         ("7", "OPERATING", "DEVELOPMENT", "QUERY"))
        self.assertEqual(kwargs["usage_sink"], "sink")

    def test_miss_is_dead_with_reason(self):
        retrieve = AsyncMock(return_value={"kind": "miss", "reason": "below_threshold", "candidates": []})
        check = self.run_probe(FakePool(7), retrieve)
        self.assertEqual(check["state"], "dead")
        self.assertIn("below_threshold", check["detail"])

    def test_search_error_is_dead_not_401(self):
        retrieve = AsyncMock(side_effect=RuntimeError("embedding failed"))
        check = self.run_probe(FakePool(7), retrieve)
        self.assertEqual(check["state"], "dead")
        self.assertIn("embedding failed", check["detail"])
