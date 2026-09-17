"""일회용 localhost DB 서버에서 전체 migration을 새 UUID DB에 재구축한다.

기존 CP04 스크립트와 달리 .env를 읽지 않고, 고정 이름의 DB를 삭제하지 않는다.
supabase/config.toml과 같은 major의 pgvector 이미지가 필요하다.
"""
import asyncio
import tomllib
from pathlib import Path
from uuid import uuid4

import asyncpg
from verify_r_answer_usage import DSN


async def main():
    admin = await asyncpg.connect(DSN, timeout=5)
    name = "r_rebuild_" + uuid4().hex
    created = False
    fresh = None
    try:
        config = tomllib.loads((Path(__file__).resolve().parents[2]/"supabase/config.toml").read_text(encoding="utf-8"))
        actual_major = int(await admin.fetchval("show server_version_num")) // 10000
        if actual_major != config["db"]["major_version"]:
            raise RuntimeError("Rebuild DB major differs from supabase/config.toml")
        for role in ("anon", "authenticated", "service_role"):
            if not await admin.fetchval("select exists(select 1 from pg_roles where rolname=$1)", role):
                await admin.execute(f'create role "{role}" nologin')
        await admin.execute(f'create database "{name}"')
        created = True
        fresh = await asyncpg.connect(DSN.rsplit("/", 1)[0]+"/"+name, timeout=5)
        for schema in ("auth", "storage", "extensions", "graphql"):
            await fresh.execute(f'create schema "{schema}"')
        migrations = sorted((Path(__file__).resolve().parents[2]/"supabase/migrations").glob("*.sql"))
        for migration in migrations:
            await fresh.execute(migration.read_text(encoding="utf-8"))
            print("PASS migration", migration.name)
        assert await fresh.fetchval("select to_regclass('public.r_question_contexts') is not null")
        print(f"Verified {len(migrations)} migrations; PostgreSQL "
              + await fresh.fetchval("show server_version"))
        from verify_r_index import verify
        pool = await asyncpg.create_pool(DSN.rsplit("/",1)[0]+"/"+name,min_size=1,max_size=3)
        try:
            seed=await verify(pool,fresh)
            from verify_r_reranker_usage import verify as verify_reranker
            await verify_reranker(pool,fresh,seed)
            from verify_r_answer_storage import verify as verify_answers
            await verify_answers(pool,fresh,seed)
            from verify_r_v2_api import verify as verify_api
            await verify_api(pool,fresh,seed)
            from verify_r_owner_delivery import verify as verify_owner
            await verify_owner(pool,fresh,seed)
        finally:
            await pool.close()
    finally:
        if fresh is not None:
            await fresh.close()
        if created:
            await admin.execute(f'drop database "{name}"')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
