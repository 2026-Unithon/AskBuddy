"""격리 PostgreSQL에서 R 답변 원장의 commit/격리/불변/실패를 검사한다.

전용 localhost:55439/usage_verify만 사용한다. 기존 DB/.env를 읽지 않는다.
사전 조건: 새 일회용 DB. stores/extraction_runs는 원장 FK용 최소 fixture다.
전체 애플리케이션 migration 재구축 검증과 구별한다.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.contracts.usage import UsageAttempt, UsageContext
from app.learn.answering import compose_grounded_answer
from app.learn.answer_usage import AnswerUsageStartError
from app.usage import DbUsageSink
from app.usage.repository import start_attempt, finalize_attempt

DSN = "postgresql://postgres:synthetic-local-test@127.0.0.1:55439/usage_verify"
RESULTS = []


def check(name, ok):
    if not ok:
        raise AssertionError(name)
    RESULTS.append(name)
    print("PASS", name)


def context(key, store=1):
    return UsageContext(store_id=str(store), cost_phase="OPERATING", cost_purpose="EVALUATION",
                        stage="ANSWER", logical_call_id=key, evaluation_run_id="9")


async def main():
    observer = await asyncpg.connect(DSN)
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1)
    try:
        # 빈 검증 DB만 허용한다. 기존 데이터가 있으면 시작하지 않는다.
        assert await observer.fetchval("select to_regclass('public.stores')") is None
        await observer.execute("create table stores(store_id bigint primary key); "
                               "create table extraction_runs(run_id bigint primary key); "
                               "insert into stores values(1),(2)")
        migration = Path(__file__).resolve().parents[2] / "supabase/migrations/20260915090000_mc0_usage_ledger.sql"
        await observer.execute(migration.read_text(encoding="utf-8"))
        check("real MC0 migration applied", await observer.fetchval(
            "select count(*) from pg_trigger where tgname='trg_usage_attempt_freeze'") == 1)

        async def run(key, *, text=None, tokens=(12, 3), error=None, store=1):
            async def provider(**kwargs):
                row = await observer.fetchrow(
                    "select status from ai_usage_attempts where store_id=$1 and logical_call_id=$2", store, key)
                assert row['status'] == 'STARTED'  # 별도 연결에서 보이므로 commit 완료
                assert pool.get_idle_size() == 1
                if error:
                    raise error
                return NS(text=text if text is not None else '{"answer":"승인 원문","card_ids":[1]}',
                          usage_metadata=NS(prompt_token_count=tokens[0], candidates_token_count=tokens[1]),
                          model_version="synthetic", response_id="test-response")
            call = AsyncMock(side_effect=provider)
            with patch("app.learn.answering.get_settings", return_value=NS(
                    answer_mode="grounded_llm", gemini_api_key="fake", gemini_model="synthetic")), \
                 patch("google.genai.Client", return_value=NS(aio=NS(models=NS(generate_content=call)))):
                result = await compose_grounded_answer("합성 질문", [dict(id=1, content="승인 원문")],
                    usage_context=context(key, store), usage_sink=DbUsageSink(pool))
            return result, call

        value, call = await run("normal")
        row = await observer.fetchrow("select * from ai_usage_attempts where logical_call_id='normal'")
        check("commit before provider and connection returned", call.await_count == 1 and row['status']=='SUCCEEDED')
        check("tokens and evaluation attribution persisted", row['prompt_tokens']==12 and row['evaluation_run_id']==9
              and row['cost_purpose']=='EVALUATION' and row['cost_usd'] is None)

        try:
            await run("normal")
        except AnswerUsageStartError:
            check("duplicate start blocked before provider", True)
        else:
            raise AssertionError("duplicate start was accepted")

        base = UsageAttempt(context=context("tenant"), requested_model="synthetic")
        aid = await start_attempt(pool, base)
        final = base.model_copy(update=dict(status="FAILED"))
        await finalize_attempt(pool, aid, final.model_copy(update=dict(context=context("tenant", 2))),
                               known_cost=None, cost=None, price_status="NO_RATE")
        check("store B cannot finalize store A", await observer.fetchval(
            "select status from ai_usage_attempts where usage_attempt_id=$1", aid) == 'STARTED')
        await asyncio.gather(*(finalize_attempt(pool, aid, final,
            known_cost=None, cost=None, price_status="NO_RATE") for _ in range(2)))
        check("concurrent finalize is idempotent", await observer.fetchval(
            "select count(*) from ai_usage_attempts where usage_attempt_id=$1 and status='FAILED'", aid)==1)
        for sql in ("update ai_usage_attempts set prompt_tokens=999 where usage_attempt_id=$1",
                    "delete from ai_usage_attempts where usage_attempt_id=$1"):
            try:
                await observer.execute(sql, aid)
            except asyncpg.RaiseError:
                check("database freeze blocks " + sql.split()[0], True)
            else:
                raise AssertionError("freeze missing")

        await run("parse", text="{broken")
        row = await observer.fetchrow("select status,prompt_tokens from ai_usage_attempts where logical_call_id='parse'")
        check("parse failure keeps incurred usage", row['status']=='FAILED' and row['prompt_tokens']==12)
        await run("timeout", error=TimeoutError())
        row = await observer.fetchrow("select status,usage_status,prompt_tokens from ai_usage_attempts where logical_call_id='timeout'")
        check("provider timeout remains unknown cost", tuple(row)==('FAILED','UNKNOWN',None))
        try:
            await run("cancel", error=asyncio.CancelledError())
        except asyncio.CancelledError:
            pass
        check("cancellation persisted as failure", await observer.fetchval(
            "select status from ai_usage_attempts where logical_call_id='cancel'")=='FAILED')
        await run("zero", tokens=(0,0))
        await run("missing", tokens=(None,None))
        values = await observer.fetch("select logical_call_id,usage_status,prompt_tokens from ai_usage_attempts "
                                      "where logical_call_id in ('zero','missing') order by logical_call_id")
        check("zero and missing remain distinct", [tuple(r) for r in values]==
              [('missing','UNKNOWN',None),('zero','COMPLETE',0)])

        # 실제 row lock으로 finalize timeout을 유발한다. 공급자를 다시 호출하지 않는다.
        blocked = UsageAttempt(context=context("blocked"), requested_model="synthetic")
        bid = await start_attempt(pool, blocked)
        async with observer.transaction():
            await observer.fetchrow("select * from ai_usage_attempts where usage_attempt_id=$1 for update", bid)
            await asyncio.wait_for(finalize_attempt(pool, bid, blocked.model_copy(update=dict(status="FAILED")),
                known_cost=None, cost=None, price_status="NO_RATE"), timeout=1.5)
        check("exhausted DB finalize leaves STARTED UNKNOWN", tuple(await observer.fetchrow(
            "select status,usage_status from ai_usage_attempts where usage_attempt_id=$1", bid))==('STARTED','UNKNOWN'))

        await run("normal", store=2)
        check("same call key isolated by store", await observer.fetchval(
            "select count(*) from ai_usage_attempts where logical_call_id='normal'")==2)
        print(json.dumps(dict(passed=len(RESULTS), postgres=await observer.fetchval("show server_version"))))
    finally:
        await pool.close()
        await observer.close()


if __name__ == "__main__":
    asyncio.run(main())
