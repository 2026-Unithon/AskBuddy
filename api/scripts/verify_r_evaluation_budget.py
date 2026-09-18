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
    print('PASS evaluation budget: concurrency, restart, money/count limits, duplicate, policy binding, settlement, unknown/overflow halt, privileges')
