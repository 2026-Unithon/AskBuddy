"""실제 RERANK SDK adapter + 실제 usage DB. 외부 SDK 응답만 합성으로 대체한다."""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch

from app.contracts.usage import UsageContext
from app.reg.hybrid import Candidate,SearchResult
from app.reg.reranker import candidate_id,rerank
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
    search=SearchResult(snap,1,candidates,'합성 질문')
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
        text='{' if mode=='invalid-json' else json.dumps(dict(ids=['invented'])) if mode=='invalid-ids' else json.dumps(dict(ids=ids))
        return NS(text=text,model_version='gemini-3.6-flash',response_id='synthetic-rank-response',
            usage_metadata=NS(prompt_token_count=12,candidates_token_count=3,total_token_count=15))

    close=AsyncMock()
    client=NS(aio=NS(models=NS(generate_content=generate),aclose=close))
    settings=NS(gemini_model='gemini-3.6-flash',gemini_api_key='synthetic-not-a-key')
    async def run(name,*,sink=None,timeout=1):
        nonlocal key
        key='r-rank-db-'+name
        context=UsageContext(store_id=str(seed['store_id']),stage='RERANK',cost_phase='OPERATING',
            cost_purpose='EVALUATION',evaluation_run_id='9901',logical_call_id=key)
        return await rerank(search,store_id=seed['store_id'],question='합성 질문',context=context,
                            sink=sink or DbUsageSink(pool),timeout=timeout)
    async def row():
        return await admin.fetchrow('select * from ai_usage_attempts where store_id=$1 and logical_call_id=$2',seed['store_id'],key)
    # This verifier isolates usage behavior; the integrated budget verifier uses real reservations.
    with patch('app.reg.reranker.get_settings',return_value=settings),patch('google.genai.Client',return_value=client) as factory, \
            patch('app.reg.reranker.provider_budget',side_effect=lambda context,model:(context,None)):
        result=await run('success')
        saved=await row()
        check('committed before SDK and connection released',len(calls)==1)
        check('SDK retry count fixed to one',factory.call_args.kwargs['http_options'].retry_options.attempts==1)
        check('successful ranking and usage attribution',result.rerank_status=='APPLIED' and saved['status']=='SUCCEEDED'
              and saved['stage']=='RERANK' and saved['cost_purpose']=='EVALUATION' and saved['prompt_tokens']==12
              and saved['completion_tokens']==3 and saved['provider_request_id']=='synthetic-rank-response')
        check('prompt and configuration hashes recorded',bool(saved['prompt_hash']) and bool(saved['config_hash']))
        before=len(calls)
        try:await run('success')
        except UsageWriteError:check('duplicate receipt prevents another SDK call',len(calls)==before)
        else:raise AssertionError('duplicate call accepted')
        for mode in ('invalid-json','invalid-ids'):
            result=await run(mode)
            saved=await row()
            check(mode+' preserves observed tokens and original candidates',result.rerank_status=='FAILED'
                and result.candidates==candidates and saved['status']=='FAILED' and saved['prompt_tokens']==12)
        mode='wait'
        result=await run('timeout',timeout=.2)
        saved=await row()
        check('timeout preserves unknown usage as failure',result.rerank_status=='TIMEOUT' and saved['status']=='FAILED'
              and saved['prompt_tokens'] is None and saved['cost_usd'] is None)
        entered.clear()
        task=asyncio.create_task(run('cancel'))
        await asyncio.wait_for(entered.wait(),1)
        task.cancel()
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

        class SlowFinalize(DbUsageSink):
            async def finalize(self,*args):await asyncio.Event().wait()
        before=len(calls)
        start=asyncio.get_running_loop().time()
        result=await run('finalize-hangs',sink=SlowFinalize(pool))
        saved=await row()
        check('stalled finalization bounded without rebilling',asyncio.get_running_loop().time()-start<1.5
            and result.rerank_status=='APPLIED' and len(calls)==before+1 and saved['status']=='STARTED' and saved['cost_usd'] is None)
        async def slow_close():await asyncio.Event().wait()
        close.side_effect=slow_close
        start=asyncio.get_running_loop().time()
        result=await run('close-hangs')
        check('SDK close bounded without losing successful ranking',result.rerank_status=='APPLIED' and asyncio.get_running_loop().time()-start<1.5)
        check('SDK cleanup attempted for every constructed client',close.await_count==factory.call_count)
    print(f'Verified {len(passed)} RERANK usage checks')
