"""계획 7 실제 스키마 검사용 일회용 DB.

PLAN7_TEST_DB_URL(127.0.0.1·localhost 만)이 있을 때만 쓴다. 처음 한 번 모든 migration 을 올린 틀 DB 를 만들고,
테스트마다 그 틀에서 새 DB 를 복사해 준다. 운영·개발 DB 에는 연결하지 않는다.
예) docker run -d --name plan7-pg -e POSTGRES_PASSWORD=synthetic-local-test -p 127.0.0.1:55439:5432 pgvector/pgvector:pg17
    PLAN7_TEST_DB_URL=postgresql://postgres:synthetic-local-test@127.0.0.1:55439/postgres pytest tests/test_plan7_*.py
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg

URL = os.environ.get("PLAN7_TEST_DB_URL", "")
ENABLED = bool(URL) and urlparse(URL).hostname in ("127.0.0.1", "localhost")
SKIP_REASON = "PLAN7_TEST_DB_URL(로컬 일회용 DB)이 있을 때만 실제 스키마로 돈다"
TEMPLATE = "plan7_template"
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _db_url(name: str) -> str:
    return URL.rsplit("/", 1)[0] + "/" + name


async def _build_template() -> None:
    admin = await asyncpg.connect(URL)
    try:
        if await admin.fetchval("select 1 from pg_database where datname = $1", TEMPLATE):
            return
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval("select 1 from pg_roles where rolname = $1", role):
                await admin.execute(f'create role "{role}" nologin')
        await admin.execute(f'create database "{TEMPLATE}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(_db_url(TEMPLATE))
    try:
        for schema in ("auth", "storage", "extensions", "graphql"):
            await conn.execute(f'create schema if not exists "{schema}"')
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            await conn.execute(migration.read_text(encoding="utf-8"))
    finally:
        await conn.close()


async def fresh_db() -> tuple[asyncpg.Connection, str]:
    """틀에서 복사한 새 DB 연결과 이름. 끝나면 drop_db 로 지운다."""
    await _build_template()
    name = "plan7_" + uuid4().hex[:12]
    admin = await asyncpg.connect(URL)
    try:
        await admin.execute(f'create database "{name}" template "{TEMPLATE}"')
    finally:
        await admin.close()
    return await asyncpg.connect(_db_url(name)), name


async def drop_db(conn: asyncpg.Connection, name: str) -> None:
    await conn.close()
    admin = await asyncpg.connect(URL)
    try:
        await admin.execute(f'drop database if exists "{name}"')
    finally:
        await admin.close()


async def seed_store(conn: asyncpg.Connection) -> int:
    """외래 키를 끈 채 최소 매장 한 줄(합성)."""
    await conn.execute("set session_replication_role = replica")
    return await conn.fetchval(
        "insert into stores (owner_id, store_name, business_type) values (1, '합성 매장', 'CAFE') returning store_id")


