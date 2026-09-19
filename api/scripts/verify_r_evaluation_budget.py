"""Synthetic durable budget checks on the disposable schema rebuild database."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.team.evaluation_budget import EvaluationBudget, BudgetDenied
from app.contracts.usage import UsageContext


async def verify(pool, conn, seed):
    store = str(seed['store_id'])
    run = str(await conn.fetchval("""insert into evaluation_runs
        (store_id,label,code_version,prompt_version,answer_model,embedding_model,answer_mode,
         retrieval_threshold,retrieval_strong_score)
        values($1,'synthetic budget','test','test','synthetic','synthetic','test',0,0) returning run_id""", int(store)))
    raw = dict(campaign_id=str(uuid4()),store_id=store,evaluation_run_ids=[run],model='synthetic',max_calls=2,
        max_krw='1',max_input_tokens=100,max_output_tokens=50,max_prompt_bytes=100000,
        input_krw_per_million='100',output_krw_per_million='200',approved_by='synthetic reviewer',
        price_reference='synthetic ceilings only, not actual prices',
        valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    context = UsageContext(store_id=store,evaluation_run_id=run,stage='ANSWER',cost_phase='OPERATING',
        cost_purpose='EVALUATION',logical_call_id='budget-test')
    def ctx(n): return context.model_copy(update={'logical_call_id':f'budget-{n}'})
    budget = EvaluationBudget(pool,raw)
    results = await asyncio.gather(*(budget.reserve(ctx(n),'synthetic') for n in range(8)),return_exceptions=True)
    keys = [r for r in results if isinstance(r,str)]
    assert len(keys)==2 and sum(isinstance(r,BudgetDenied) for r in results)==6
    row = await conn.fetchrow('select reserved_calls,reserved_units from r_evaluation_budgets where campaign_id=$1',budget.policy.campaign_id)
    assert tuple(row)==(2,40000)
    restarted = EvaluationBudget(pool,raw)
    try: await restarted.reserve(ctx(20),'synthetic')
    except BudgetDenied: pass
    else: raise AssertionError('restart reset budget')
    await budget.finish(keys[0],input_tokens=10,output_tokens=5)
    await budget.finish(keys[0],input_tokens=10,output_tokens=5)
    try: await budget.finish(keys[0],input_tokens=11,output_tokens=5)
    except BudgetDenied: pass
    else: raise AssertionError('changed observation accepted')
    changed = EvaluationBudget(pool,dict(raw,max_calls=10))
    try: await changed.reserve(ctx(21),'synthetic')
    except BudgetDenied: pass
    else: raise AssertionError('policy mutation accepted')
    # A monetary cap can stop calls before the independent call cap.
    money = EvaluationBudget(pool,dict(raw,campaign_id=str(uuid4()),max_calls=10,max_krw='0.03'))
    key = await money.reserve(ctx(30),'synthetic')
    try: await money.reserve(ctx(31),'synthetic')
    except BudgetDenied: pass
    else: raise AssertionError('money cap exceeded')
    await money.finish(key)  # Unknown usage is not refunded and halts this campaign.
    assert await conn.fetchval('select halted from r_evaluation_budgets where campaign_id=$1',money.policy.campaign_id)
    duplicate = EvaluationBudget(pool,dict(raw,campaign_id=str(uuid4())))
    key = await duplicate.reserve(ctx(40),'synthetic')
    try: await duplicate.reserve(ctx(40),'synthetic')
    except BudgetDenied: pass
    else: raise AssertionError('duplicate provider call allowed')
    try: await duplicate.finish(key,input_tokens=101,output_tokens=1)
    except BudgetDenied: pass
    else: raise AssertionError('overflow not reported')
    try: await duplicate.reserve(ctx(41),'synthetic')
    except BudgetDenied: pass
    else: raise AssertionError('halted campaign called provider')
    assert not await conn.fetchval("select has_table_privilege('authenticated','r_evaluation_budgets','UPDATE')")
    # All three real adapters share one durable cap; only SDK responses are synthetic.
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock, Mock, patch
    from app.team.evaluation_budget import evaluation_budget_scope
    from app.team.evaluation_usage import evaluation_usage_scope
    from app.reg.embeddings import recorded_embeddings
    from app.reg.reranker import _model
    from app.learn.semantic_proposals import _generate
    from app.usage import DbUsageSink
    import json
    settings=NS(embedding_model='text-embedding-3-small',openai_api_key='synthetic',embedding_dim=1,
        embedding_timeout_seconds=1,query_embedding_timeout_seconds=1,gemini_model='synthetic',gemini_api_key='synthetic')
    shared=EvaluationBudget(pool,dict(raw,campaign_id=str(uuid4()),max_calls=3,max_krw='10',max_input_tokens=10000,
        additional_calls=[dict(stage='QUERY',model=settings.embedding_model),dict(stage='RERANK',model='synthetic')]))
    calls=[]
    async def generate(**kw):
        assert pool.get_idle_size()==pool.get_size()
        assert await conn.fetchval('select reserved_calls from r_evaluation_budgets where campaign_id=$1',shared.policy.campaign_id)==len(calls)+2
        calls.append(kw)
        return NS(text=json.dumps(dict(ids=['one'])),usage_metadata=NS(prompt_token_count=12,candidates_token_count=3,thoughts_token_count=0))
    gemini=NS(aio=NS(models=NS(count_tokens=AsyncMock(return_value=NS(total_tokens=12)),generate_content=generate),aclose=AsyncMock()))
    embedding=NS(embeddings=NS(create=Mock(return_value=NS(data=[NS(index=0,embedding=[1.])],
        usage=NS(prompt_tokens=3,total_tokens=3)))),close=Mock())
    sink=DbUsageSink(pool)
    with evaluation_budget_scope(shared),evaluation_usage_scope(store_id=int(store),evaluation_run_id=run), \
            patch('app.reg.embeddings.get_settings',return_value=settings), \
            patch('app.reg.reranker.get_settings',return_value=settings), \
            patch('app.learn.semantic_proposals.get_settings',return_value=settings), \
            patch('app.reg.embeddings.OpenAI',return_value=embedding),patch('google.genai.Client',return_value=gemini):
        await recorded_embeddings(['abc'],context=ctx(100).model_copy(update=dict(stage='QUERY',cost_purpose='PRODUCT',evaluation_run_id=None)),sink=sink)
        await _model('q',context=ctx(101).model_copy(update={'stage':'RERANK'}),sink=sink,candidate_ids=('one',),cleanup_budget=.5)
        await _generate('q',context=ctx(102),sink=sink,cleanup_budget=.5)
        try:await recorded_embeddings(['abc'],context=ctx(103).model_copy(update={'stage':'QUERY'}),sink=sink)
        except BudgetDenied:pass
        else:raise AssertionError('cross-stage total exceeded')
    assert embedding.embeddings.create.call_count==1 and len(calls)==2
    assert await conn.fetchval("select count(*) from r_evaluation_reservations where campaign_id=$1 and status='OBSERVED'",shared.policy.campaign_id)==3
    assert await conn.fetchval("select cost_purpose from ai_usage_attempts where store_id=$1 and logical_call_id='budget-100'",int(store))=='EVALUATION'
    print('PASS integrated budget: QUERY/RERANK/ANSWER share three reservations and block fourth before SDK')
    print('PASS evaluation budget: concurrency, restart, money/count limits, duplicate, policy binding, settlement, unknown/overflow halt, privileges')
