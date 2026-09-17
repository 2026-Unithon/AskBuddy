"""임시 schema에서 M3 migration·문맥 경합·publication/card 잠금을 실측한다.

전용 loopback 검증 DB만 사용한다. 전체 migration 재구축/실제 W 종단 검증과 다르다.
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.errors import ApiError
from app.learn.answering import AnswerComposition
from app.learn.question_contexts import (
    ClarificationLimit, accept_context, create_context, load_context, offer_next_context,
)
from app.learn.router import _citations_are_current, _lock_chat_publication, _open_session
from verify_r_answer_usage import DSN


async def main():
    schema = "r_context_"+uuid4().hex
    admin = await asyncpg.connect(DSN, timeout=5)
    conn = None
    passed = []

    def check(name, value):
        assert value, name
        passed.append(name)
        print("PASS", name)

    async def rejected(name, action, exception, code=None):
        try:
            async with admin.transaction():
                await action()
        except exception as exc:
            check(name, code is None or exc.code == code)
        else:
            raise AssertionError(name+" accepted")

    async def blocked(sql, *args):
        # 시간 추측 대신 PostgreSQL이 실제 lock_timeout을 반환하는지 확인한다.
        try:
            async with conn.transaction():
                await conn.execute("set local lock_timeout='100ms'")
                await conn.execute(sql, *args)
        except asyncpg.LockNotAvailableError:
            return True
        return False

    try:
        await admin.execute(f'create schema "{schema}"')
        await admin.execute(f'set search_path to "{schema}"')
        await admin.execute("""
            create table store_members(member_id bigint primary key, store_id bigint not null);
            create table chat_sessions(session_id bigint generated always as identity primary key,
                store_id bigint not null, member_id bigint not null references store_members,
                started_at timestamptz not null default now());
            insert into store_members values(1,1),(2,2),(3,1);
            insert into chat_sessions(store_id,member_id) values(1,1),(2,2),(1,3);
            create table knowledge_publications(store_id bigint primary key,
                knowledge_revision bigint not null default 0);
            create table knowledge_cards(card_id bigint primary key,store_id bigint,
                published_version_id bigint,review_status text,is_verified boolean);
            insert into knowledge_publications values(1,1),(2,1);
            insert into knowledge_cards values(10,1,100,'APPROVED',true),(20,2,200,'APPROVED',true);
        """)
        migration = Path(__file__).resolve().parents[2]/"supabase/migrations/20260917103000_m3_question_context.sql"
        await admin.execute(migration.read_text(encoding="utf-8"))
        conn = await asyncpg.connect(DSN, server_settings={"search_path": schema}, timeout=5)
        check("legacy sessions remain v1", await admin.fetchval(
            "select count(*) from chat_sessions where contract_version='v1'") == 3)
        await rejected("session contract cannot be rewritten", lambda: admin.execute(
            "update chat_sessions set contract_version='v2' where session_id=1"), asyncpg.RaiseError)
        sid = await admin.fetchval("""insert into chat_sessions(store_id,member_id,contract_version)
            values(1,1,'v2') returning session_id""")
        check("legacy open session skips v2", await _open_session(admin,1,1) == 1)
        args = dict(store_id=1,member_id=1,session_id=sid)
        async with admin.transaction():
            original = await create_context(admin, **args, original_question="  합성 질문\n",
                confirmed_slots={"entity":"합성라테"}, proposed_slots={"temperature":"ICE"},
                knowledge_revision=1, slot="temperature", options=("HOT","ICE"))
        args["context_id"] = original.context.context_id
        check("question whitespace preserved", original.context.original_question == "  합성 질문\n")
        for label, scope in (("other store",dict(store_id=2,member_id=2,session_id=2)),
                             ("other member",dict(store_id=1,member_id=3,session_id=3)),
                             ("v1 session",dict(store_id=1,member_id=1,session_id=1))):
            await rejected(label+" denied", lambda scope=scope: load_context(admin, **scope,
                context_id=original.context.context_id), ApiError, "NOT_FOUND")
        await rejected("composite FK blocks cross session scope", lambda: admin.execute(
            "update r_question_contexts set store_id=2 where context_id=$1",args["context_id"]),
            asyncpg.ForeignKeyViolationError)
        async with admin.transaction():
            loaded = await load_context(admin, **args)
            check("load does not refresh TTL",loaded.context.expires_at==original.context.expires_at)
            accepted = await accept_context(admin, **args, expected_state_revision=1,
                                           option="HOT", knowledge_revision=2)
        check("publication change discards inference", accepted.context.proposed_slots=={}
              and accepted.context.confirmed_slots=={"entity":"합성라테","temperature":"HOT"})
        await rejected("same choice not applied twice",lambda: accept_context(admin,**args,
            expected_state_revision=1,option="HOT",knowledge_revision=2),ApiError,"INVALID_CONTRACT")
        async with admin.transaction():
            next_offer = await offer_next_context(admin, **args, slot="predicate", options=("수량","위치"))
            check("second offer does not refresh TTL",next_offer.context.expires_at==accepted.context.expires_at)
            await accept_context(admin,**args,expected_state_revision=next_offer.state_revision,
                                 option="수량",knowledge_revision=2)
        await rejected("third clarification requires escalation",lambda: offer_next_context(
            admin, **args,slot="size",options=("small","large")),ClarificationLimit)
        async with admin.transaction():
            locked = await load_context(admin, **args)
            check("concurrent context update is locked",await blocked(
                "update r_question_contexts set state_revision=state_revision+1 where context_id=$1",
                locked.context.context_id))
        await admin.execute("update r_question_contexts set expires_at=clock_timestamp() where context_id=$1",
                            args["context_id"])
        await rejected("expired context returns 410",lambda:load_context(admin,**args),ApiError,"CONTEXT_EXPIRED")
        composition = AnswerComposition("합성 승인",[dict(id=10,version_id=100)],"CARD_ORIGINAL","FALLBACK")
        async with admin.transaction():
            await _lock_chat_publication(admin,1)
            check("published citation accepted",await _citations_are_current(admin,1,composition))
            check("publication change waits for answer transaction",await blocked(
                "update knowledge_publications set knowledge_revision=2 where store_id=1"))
            check("card change waits for answer transaction",await blocked(
                "update knowledge_cards set published_version_id=101 where card_id=10"))
            await conn.execute("update knowledge_publications set knowledge_revision=2 where store_id=2")
            check("other store publication independent",True)
        await conn.execute("update knowledge_cards set published_version_id=101 where card_id=10")
        async with admin.transaction():
            check("old citation rejected after commit",not await _citations_are_current(admin,1,composition))
            check("cross store citation rejected",not await _citations_are_current(admin,2,composition))
        print(f"Verified {len(passed)} context/stale DB checks")
    finally:
        if conn is not None:
            await conn.close()
        # 이 실행이 만든 UUID schema만 정리한다. 기존 DB 객체는 건드리지 않는다.
        await admin.execute(f'drop schema if exists "{schema}" cascade')
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
