from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest

from app.team.evaluation_budget import BudgetPolicy, EvaluationBudget, BudgetDenied, current_budget, evaluation_budget_scope
from tests.test_r_semantic_proposals import kwargs


def policy(**changes):
    return dict(campaign_id=str(uuid4()),store_id='1',evaluation_run_ids=['1'],model='synthetic',max_calls=2,
        max_krw='1',max_input_tokens=100,max_output_tokens=50,max_prompt_bytes=100000,
        input_krw_per_million='100',output_krw_per_million='200',approved_by='synthetic reviewer',
        price_reference='synthetic ceilings only, not actual prices',
        valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),**changes)


def test_money_and_scope_fail_closed():
    p=policy();assert BudgetPolicy.model_validate(p).call_units==20000
    for key,value in [('max_krw','NaN'),('max_calls',True),('max_krw','0.001'),('input_krw_per_million','-1')]:
        with pytest.raises(ValueError):BudgetPolicy.model_validate(dict(p,**{key:value}))
    ctx=kwargs()['context'];budget=EvaluationBudget(None,p)
    with pytest.raises(BudgetDenied):current_budget(ctx,'synthetic')
    with evaluation_budget_scope(budget):
        assert current_budget(ctx,'synthetic') is budget
        with pytest.raises(BudgetDenied):current_budget(ctx,'different-model')
        with pytest.raises(BudgetDenied):current_budget(ctx.model_copy(update={'store_id':'2'}),'synthetic')
    with pytest.raises(BudgetDenied):current_budget(ctx,'synthetic')


@pytest.mark.asyncio
async def test_sdk_never_generates_without_input_count_and_output_limit(monkeypatch):
    from app.learn.semantic_proposals import _generate
    p=BudgetPolicy.model_validate(policy());ctx=kwargs()['context']
    budget=NS(policy=p,reserve=AsyncMock(return_value='reserved'),finish=AsyncMock(),check_scope=lambda *args:None)
    generate=AsyncMock(return_value=NS(text='{}',usage_metadata=NS(prompt_token_count=10,candidates_token_count=3,thoughts_token_count=2)))
    count=AsyncMock(return_value=NS(total_tokens=101))
    client=NS(aio=NS(models=NS(count_tokens=count,generate_content=generate),aclose=AsyncMock()))
    monkeypatch.setattr('google.genai.Client',lambda **kw:client)
    monkeypatch.setattr('app.learn.semantic_proposals.get_settings',lambda:NS(gemini_api_key='synthetic',gemini_model='synthetic'))
    sink=NS(start=AsyncMock(return_value=1),finalize=AsyncMock())
    with evaluation_budget_scope(budget):
        with pytest.raises(BudgetDenied):await _generate('test',context=ctx,sink=sink,cleanup_budget=.2)
        generate.assert_not_awaited()
        count.return_value=NS(total_tokens=10)
        await _generate('test',context=ctx,sink=sink,cleanup_budget=.2)
    assert generate.call_args.kwargs['config'].max_output_tokens==50
    assert generate.call_args.kwargs['contents']==count.call_args.kwargs['contents']
    assert budget.finish.call_args.kwargs==dict(input_tokens=10,output_tokens=5)
