"""실제 RERANK SDK adapter + 실제 usage DB의 저장 계약을 검증한다.

DB 부하를 운영 지연 인수로 판정하지 않는다. 짧은 실행/정리 기한과 단계별
멈춤은 test_r_reranker_lifecycle.py에서 검사하고 여기서는 여유 있는 유한 기한을 쓴다.
"""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch

from app.contracts.usage import UsageContext
from app.reg.hybrid import Candidate
from app.reg.reranker import _model,candidate_id
from app.usage import DbUsageSink
from app.usage.repository import UsageWriteError


async def verify(pool,admin,seed):
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name)
        print('PASS RERANK usage',name)
    snap=seed['snapshot']
    candidates=tuple(Candidate(c.card_id,c.card_version_id,b.block_id,.4,.3,.05) for c in snap.cards for b in c.blocks)
    ids=[candidate_id(c) for c in reversed(candidates)]
    calls=[]
    entered=asyncio.Event()
    mode='success'
    key=''

    async def generate(**kwargs):
        row=await admin.fetchrow("select status,stage,prompt_hash,config_hash from ai_usage_attempts where store_id=$1 and logical_call_id=$2",
                                 seed['store_id'],key)
        assert row and row['status']=='STARTED' and row['stage']=='RERANK'
        assert row['prompt_hash'] and row['config_hash'] and pool.get_idle_size()==pool.get_size()
        calls.append(key)
        entered.set()
        if mode=='wait':await asyncio.Event().wait()
        if mode=='timeout':raise TimeoutError('synthetic provider timeout')
        text='{' if mode=='invalid-json' else json.dumps(dict(ids=['invented'])) if mode=='invalid-ids' else json.dumps(dict(ids=ids))
        return NS(text=text,model_version='gemini-3.6-flash',response_id='synthetic-rank-response',
            usage_metadata=NS(prompt_token_count=12,candidates_token_count=3,total_token_count=15))

    close=AsyncMock()
    client=NS(aio=NS(models=NS(generate_content=generate),aclose=close))
    settings=NS(gemini_model='gemini-3.6-flash',gemini_api_key='synthetic-not-a-key')
    async def run(name,*,sink=None):
        nonlocal key
        key='r-rank-db-'+name
        context=UsageContext(store_id=str(seed['store_id']),stage='RERANK',cost_phase='OPERATING',
            cost_purpose='EVALUATION',evaluation_run_id='9901',logical_call_id=key)
        # 실제 저장/SDK adapter를 사용하되 DB 왕복에 운영의 200ms 정리 예산을 적용하지 않는다.
        return await asyncio.wait_for(_model('합성 질문',context=context,
            sink=sink or DbUsageSink(pool),candidate_ids=tuple(ids),cleanup_budget=5),timeout=30)
    async def row():
        return await admin.fetchrow('select * from ai_usage_attempts where store_id=$1 and logical_call_id=$2',seed['store_id'],key)
    # This verifier isolates usage behavior; the integrated budget verifier uses real reservations.
    with patch('app.reg.reranker.get_settings',return_value=settings),patch('google.genai.Client',return_value=client) as factory, \
            patch('app.reg.reranker.provider_budget',side_effect=lambda context,model:(context,None)):
        result=await run('success')
        saved=await row()
        check('committed before SDK and connection released',len(calls)==1)
        check('SDK retry count fixed to one',factory.call_args.kwargs['http_options'].retry_options.attempts==1)
        check('successful ranking and usage attribution',result.ids==ids and saved['status']=='SUCCEEDED'
              and saved['stage']=='RERANK' and saved['cost_purpose']=='EVALUATION' and saved['prompt_tokens']==12
              and saved['completion_tokens']==3 and saved['provider_request_id']=='synthetic-rank-response')
        check('prompt and configuration hashes recorded',bool(saved['prompt_hash']) and bool(saved['config_hash']))
        before=len(calls)
        try:await run('success')
        except UsageWriteError:check('duplicate receipt prevents another SDK call',len(calls)==before)
        else:raise AssertionError('duplicate call accepted')
        for mode in ('invalid-json','invalid-ids'):
            try:await run(mode)
            except ValueError:pass
            else:raise AssertionError('invalid ranking accepted')
            saved=await row()
            check(mode+' preserves observed tokens on failure',saved['status']=='FAILED' and saved['prompt_tokens']==12)
        mode='timeout'
        try:await run('timeout')
        except TimeoutError:pass
        else:raise AssertionError('provider timeout swallowed')
        saved=await row()
        check('timeout preserves unknown usage as failure',saved['status']=='FAILED'
              and saved['prompt_tokens'] is None and saved['cost_usd'] is None)
        mode='wait'
        entered.clear()
        task=asyncio.create_task(run('cancel'))
        try:await asyncio.wait_for(entered.wait(),10)
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        try:await task
        except asyncio.CancelledError:pass
        else:raise AssertionError('cancellation swallowed')
        saved=await row()
        check('caller cancellation propagated and recorded',saved['status']=='FAILED' and saved['cost_usd'] is None)
        mode='success'

        class FailedStart(DbUsageSink):
            async def start(self,receipt):raise OSError('synthetic write failure')
        before=len(calls)
        try:await run('start-fails',sink=FailedStart(pool))
        except UsageWriteError:check('arbitrary start failure prevents SDK call',len(calls)==before)
        else:raise AssertionError('usage start failed open')

        class DelayedStart(DbUsageSink):
            async def start(self,receipt):
                await asyncio.sleep(.25)
                return await super().start(receipt)
        before=len(calls)
        result=await run('delayed-start',sink=DelayedStart(pool))
        saved=await row()
        check('DB scheduling delay is not a production latency assertion',result.ids==ids
              and len(calls)==before+1 and saved['status']=='SUCCEEDED')

        class FailedFinalize(DbUsageSink):
            async def finalize(self,*args):raise TimeoutError('synthetic finalize timeout')
        before=len(calls)
        result=await run('finalize-fails',sink=FailedFinalize(pool))
        saved=await row()
        check('failed finalization remains unknown without rebilling',result.ids==ids
            and len(calls)==before+1 and saved['status']=='STARTED' and saved['cost_usd'] is None)
        close.side_effect=TimeoutError('synthetic SDK close timeout')
        result=await run('close-fails')
        check('SDK close failure preserves successful ranking',result.ids==ids and (await row())['status']=='SUCCEEDED')
        check('SDK cleanup attempted for every constructed client',close.await_count==factory.call_count)
    print(f'Verified {len(passed)} RERANK usage checks')
