from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import pytest
from app.team.evaluation_budget import EvaluationBudget, BudgetDenied, evaluation_budget_scope, provider_budget
from app.team.evaluation_usage import evaluation_usage_scope
from app.reg.embeddings import recorded_embeddings
from tests.test_r_evaluation_budget import policy
from tests.test_r_semantic_proposals import kwargs


def budget():
    raw=policy()
    raw['additional_calls']=[dict(stage='QUERY',model='text-embedding-3-small'),dict(stage='RERANK',model='synthetic')]
    return EvaluationBudget(None,raw)


def test_http_scope_maps_before_provider_and_rejects_missing_or_foreign_budget():
    ctx=kwargs()['context'].model_copy(update=dict(stage='QUERY',cost_purpose='PRODUCT',evaluation_run_id=None))
    assert provider_budget(ctx,'text-embedding-3-small')==(ctx,None)
    with evaluation_usage_scope(store_id=1,evaluation_run_id='1'):
        with pytest.raises(BudgetDenied):provider_budget(ctx,'text-embedding-3-small')
        with evaluation_budget_scope(budget()):
            mapped,selected=provider_budget(ctx,'text-embedding-3-small')
            assert mapped.cost_purpose=='EVALUATION' and mapped.evaluation_run_id=='1'
            with pytest.raises(BudgetDenied):provider_budget(ctx,'unapproved')
            with pytest.raises(BudgetDenied):provider_budget(ctx.model_copy(update={'evaluation_run_id':'2'}),'text-embedding-3-small')


@pytest.mark.asyncio
async def test_embedding_reserves_before_sdk_and_finishes_observed_usage(monkeypatch):
    b=budget();b.reserve=AsyncMock(return_value='key');b.finish=AsyncMock()
    ctx=kwargs()['context'].model_copy(update={'stage':'QUERY'})
    monkeypatch.setattr('app.reg.embeddings.get_settings',lambda:NS(openai_api_key='synthetic',embedding_model='text-embedding-3-small',query_embedding_timeout_seconds=.5))
    def embed(texts,**kw):
        b.reserve.assert_awaited_once()
        kw['recording'].observe(prompt_tokens=3)
        return [[1.]]
    provider=Mock(side_effect=embed)
    monkeypatch.setattr('app.reg.embeddings.embed_texts',provider)
    sink=NS(start=AsyncMock(return_value=1),finalize=AsyncMock())
    with pytest.raises(BudgetDenied):await recorded_embeddings(['abc'],context=ctx,sink=sink)
    provider.assert_not_called()
    with evaluation_budget_scope(b):
        assert await recorded_embeddings(['abc'],context=ctx,sink=sink)==[[1.]]
        b.finish.assert_awaited_once_with('key',input_tokens=3,output_tokens=0)
        with pytest.raises(BudgetDenied):await recorded_embeddings(['한'*100],context=ctx,sink=sink)
    assert provider.call_count==1


@pytest.mark.asyncio
async def test_reranker_missing_budget_propagates_instead_of_fallback(monkeypatch):
    from app.reg.reranker import rerank
    from tests.test_r_semantic_proposals import case
    search,_,_=case()
    monkeypatch.setattr('app.reg.reranker.get_settings',lambda:NS(gemini_model='synthetic'))
    factory=Mock();monkeypatch.setattr('google.genai.Client',factory)
    with pytest.raises(BudgetDenied):
        await rerank(search,store_id=1,question='q',context=kwargs()['context'].model_copy(update={'stage':'RERANK'}),sink=object(),timeout=1)
    factory.assert_not_called()
