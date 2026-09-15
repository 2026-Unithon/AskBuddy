"""원장 DB 준비 후 실행: W 등록 adapter와 R QUERY/ANSWER 집계의 실제 DB 인수."""
import asyncio
import sys
import json
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.contracts.usage import UsageAttempt, UsageContext, ModelUsage
from app.reg.embeddings import recorded_embeddings
from app.usage import DbUsageSink
from app.usage.repository import start_attempt, finalize_attempt
from app.team.usage_metrics import read_run_usage
from verify_r_answer_usage import DSN


async def main():
    pool=await asyncpg.create_pool(DSN,min_size=1,max_size=1)
    observer=await asyncpg.connect(DSN)
    loop=asyncio.get_running_loop()
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name)
        print("PASS",name)
    try:
        fixture=json.loads((Path(__file__).resolve().parents[1]/"tests/fixtures/w_embedding_handoff.json").read_text(encoding="utf-8"))
        context=UsageContext.model_validate(fixture["context"])
        def provider(**kwargs):
            count=asyncio.run_coroutine_threadsafe(observer.fetchval(
                "select count(*) from ai_usage_attempts where store_id=1 and logical_call_id='w-handoff-embedding' and status='STARTED'"),loop).result(timeout=2)
            assert count==1 and pool.get_idle_size()==1
            return NS(data=[NS(index=1,embedding=[2.0]),NS(index=0,embedding=[1.0])],
                      usage=NS(prompt_tokens=12,total_tokens=12),model="synthetic",_request_id="w-test")
        client=NS(embeddings=NS(create=Mock(side_effect=provider)),close=Mock())
        with patch("app.reg.embeddings.get_settings",return_value=NS(
                openai_api_key="fake",embedding_model="synthetic",embedding_dim=1,embedding_timeout_seconds=30)), \
             patch("app.reg.embeddings.OpenAI",return_value=client) as factory:
            vectors=await recorded_embeddings(fixture["texts"],context=context,sink=DbUsageSink(pool))
        check("W batch uses one provider call and restores order",vectors==fixture["expected_vectors"] and client.embeddings.create.call_count==1)
        check("W registration does not inherit query timeout",factory.call_args.kwargs["timeout"]==30)
        row=await observer.fetchrow("select * from ai_usage_attempts where logical_call_id='w-handoff-embedding'")
        check("W EMBED registration attribution committed",row['cost_phase']=='REGISTRATION' and row['stage']=='EMBED'
              and row['cost_purpose']=='DEVELOPMENT' and row['prompt_tokens']==12 and row['status']=='SUCCEEDED')

        async def receipt(key,*,store=1,run=901,purpose="EVALUATION",stage="QUERY",cost=Decimal('.002'),finish=True):
            base=UsageAttempt(context=UsageContext(store_id=str(store),evaluation_run_id=str(run),
                cost_phase="OPERATING",cost_purpose=purpose,stage=stage,logical_call_id=key),requested_model="synthetic")
            aid=await start_attempt(pool,base)
            if finish:
                final=base.model_copy(update=dict(status="FAILED",usage_status="COMPLETE",usage=ModelUsage(prompt_tokens=2)))
                await finalize_attempt(pool,aid,final,known_cost=cost,cost=cost,price_status="PRICED")
            return aid
        await receipt("query-metric")
        await receipt("answer-metric",stage="ANSWER",cost=Decimal('.003'))
        await receipt("other-store-metric",store=2,cost=Decimal(99))
        await receipt("other-purpose-metric",purpose="PRODUCT",cost=Decimal(99))
        await receipt("other-stage-metric",stage="EMBED",cost=Decimal(99))
        await receipt("other-run-metric",run=902,cost=Decimal(99))
        result=await read_run_usage(observer,1,901)
        check("read rollup excludes other store purpose stage and run",result['attempt_count']==2 and Decimal(result['total_cost_usd'])==Decimal('.005'))
        check("read stages remain separate",result['stage_counts']==dict(QUERY=1,ANSWER=1))
        await receipt("unknown-metric",finish=False)
        result=await read_run_usage(observer,1,901)
        check("STARTED blocks total without losing known subtotal",result['total_cost_usd'] is None and Decimal(result['known_cost_usd'])==Decimal('.005') and result['unknown_attempt_count']==1)
        print(f"{len(passed)}/{len(passed)} PASS PostgreSQL " + await observer.fetchval("show server_version"))
    finally:
        await pool.close()
        await observer.close()


if __name__ == '__main__':
    asyncio.run(main())
