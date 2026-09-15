"""일회용 localhost DB 안의 임시 schema에서 R 원자 제한 migration을 검증한다."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.learn.request_limits import request_lease
from app.errors import ApiError
from app.learn.router import _record_pending_occurrence
from verify_r_answer_usage import DSN


async def main():
    schema = "r_guard_" + uuid4().hex
    admin = await asyncpg.connect(DSN)
    pool = None
    passed = []
    def check(name, ok):
        assert ok, name
        passed.append(name)
        print("PASS", name)
    try:
        await admin.execute(f'create schema "{schema}"')
        await admin.execute(f'set search_path to "{schema}"')
        await admin.execute("create table stores(store_id bigint primary key); create table users(user_id bigint primary key); "
                            "insert into stores select generate_series(1,9); insert into users values(1),(2),(3)")
        path = Path(__file__).resolve().parents[2]/"supabase/migrations/20260915170000_r_request_limits.sql"
        await admin.execute(path.read_text(encoding="utf-8"))
        pool = await asyncpg.create_pool(DSN,min_size=1,max_size=4,server_settings={"search_path":schema})
        settings = NS(request_member_per_minute=20,request_store_per_minute=120,
                      request_member_concurrency=2,request_store_concurrency=8,chat_deadline_seconds=5)
        with patch("app.learn.request_limits.get_settings",return_value=settings):
            async with request_lease(pool,1,1):
                async with request_lease(pool,1,1):
                    try:
                        async with request_lease(pool,1,1):
                            raise AssertionError("third concurrent request accepted")
                    except ApiError as exc:
                        check("member concurrency blocked",exc.status_code==429)
                    async with request_lease(pool,2,1):
                        check("other store independent",True)
            check("release marks leases finished",await admin.fetchval(
                "select count(*) from r_request_leases where store_id=1 and finished_at is null")==0)
            settings.request_member_per_minute=2
            try:
                async with request_lease(pool,1,1):
                    raise AssertionError("rate exceeded")
            except ApiError as exc:
                check("finished requests still count per minute",exc.status_code==429)
            settings.request_member_per_minute=20
            settings.request_store_concurrency=1
            async with request_lease(pool,3,1):
                try:
                    async with request_lease(pool,3,2):
                        raise AssertionError("store concurrency exceeded")
                except ApiError as exc:
                    check("store concurrency across members",exc.status_code==429)
            await admin.execute("insert into r_request_leases(request_id,store_id,user_id,expires_at) "
                                "values($1,4,1,clock_timestamp()-interval '1 second')",uuid4())
            async with request_lease(pool,4,1):
                check("expired worker lease recovered",True)
            settings.request_store_concurrency=8
            settings.request_member_concurrency=1
            entered=asyncio.Event()
            release=asyncio.Event()
            async def first():
                async with request_lease(pool,5,1):
                    entered.set()
                    await release.wait()
            task=asyncio.create_task(first())
            await entered.wait()
            try:
                async with request_lease(pool,5,1):
                    raise AssertionError("second worker exceeded limit")
            except ApiError as exc:
                check("separate connection cannot bypass limit",exc.status_code==429)
            finally:
                release.set()
                await task
            outcomes=[]
            limited=asyncio.Event()
            finish=asyncio.Event()
            async def contender():
                try:
                    async with request_lease(pool,6,1):
                        outcomes.append("accepted")
                        await finish.wait()
                except ApiError:
                    outcomes.append("limited")
                    limited.set()
            tasks=[asyncio.create_task(contender()) for _ in range(2)]
            try:
                await asyncio.wait_for(limited.wait(),2)
            finally:
                finish.set()
                await asyncio.gather(*tasks)
            check("simultaneous workers admit exactly one request",sorted(outcomes)==["accepted","limited"])
        await admin.execute("""
            create table store_members(member_id bigint primary key,store_id bigint);
            create table pending_questions(question_id bigint primary key,store_id bigint);
            create table chat_sessions(session_id bigint primary key,member_id bigint,store_id bigint);
            create table chat_messages(message_id bigint primary key,session_id bigint);
            create table pending_question_occurrences(question_id bigint,member_id bigint,message_id bigint,
                unique(question_id,member_id,message_id));
            insert into store_members values(1,1),(2,2);
            insert into pending_questions values(1,1),(2,2);
            insert into chat_sessions values(1,1,1),(2,2,2);
            insert into chat_messages values(1,1),(2,2);
        """)
        await _record_pending_occurrence(admin,1,1,1,store_id=1)
        await _record_pending_occurrence(admin,1,2,1,store_id=1)
        await _record_pending_occurrence(admin,1,1,2,store_id=1)
        await _record_pending_occurrence(admin,2,1,1,store_id=1)
        check("pending occurrence rejects cross-store member/message/question", await admin.fetchval(
            "select count(*) from pending_question_occurrences")==1)
        print(f"{len(passed)}/{len(passed)} PASS PostgreSQL " + await admin.fetchval("show server_version"))
    finally:
        if pool:
            await pool.close()
        await admin.execute('set search_path to public')
        await admin.execute(f'drop schema "{schema}" cascade')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
