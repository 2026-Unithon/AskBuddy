from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.learn import knowledge_loop as module
from app.reg.owner_candidates import published_owner_candidates


def context():
    return UsageContext(store_id='1', stage='RELATION', cost_phase='OPERATING',
                        logical_call_id='test-relation', operation_id='test-owner')


@pytest.mark.asyncio
async def test_query_embedding_and_candidate_contract(monkeypatch):
    embed = AsyncMock(return_value=[[1.0]+[0.0]*1535])
    candidates = [dict(id=2, version_id=3, title='공개', content='원문', score=.9,
                       category_id=4, assignment_type='MANUAL', category_name='업무')]
    search = AsyncMock(return_value=candidates)
    monkeypatch.setattr(module, 'recorded_embeddings', embed)
    monkeypatch.setattr(module, 'published_owner_candidates', search)
    result = await module.find_owner_answer_candidates('session', 1, '질문', '답변', usage_context=context(), usage_sink=object())
    assert result == candidates
    assert embed.call_args.args[0] == ['질문\n답변']
    assert embed.call_args.kwargs['context'].stage == 'EMBED'
    assert search.call_args.kwargs['query_vector'] == embed.return_value[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [ApiError(503, 'INDEX_UNAVAILABLE', 'missing'), RuntimeError('DB')])
async def test_search_failure_cannot_become_new_proposal(monkeypatch, failure):
    db = SimpleNamespace(fetch=AsyncMock(return_value=[dict(category_id=1, category_name='기타', is_system=True)]))
    monkeypatch.setattr(module, 'find_owner_answer_candidates', AsyncMock(side_effect=failure))
    generate = AsyncMock()
    monkeypatch.setattr(module, 'recorded_generate', generate)
    with pytest.raises(ApiError) as caught:
        await module.build_knowledge_plan(db, 1, '질문', '답변', usage_context=context(), usage_sink=object())
    assert caught.value.code == 'INDEX_UNAVAILABLE'
    generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [0, 101, True])
async def test_invalid_limit_never_calls_provider(monkeypatch, limit):
    embed = AsyncMock()
    monkeypatch.setattr(module, 'recorded_embeddings', embed)
    with pytest.raises(ValueError):
        await module.find_owner_answer_candidates(None, 1, '질문', '답변', top_k=limit, usage_context=context(), usage_sink=object())
    embed.assert_not_called()


@pytest.mark.asyncio
async def test_index_model_mismatch_fails_closed(monkeypatch):
    db = MagicMock()
    db.transaction.return_value.__aenter__ = AsyncMock()
    db.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
    db.fetchrow = AsyncMock(return_value=dict(embedding_model='old', index_config_version='r-block-index/v1'))
    monkeypatch.setattr('app.reg.owner_candidates.read_current_index', AsyncMock(return_value=(None, 2, 3)))
    with pytest.raises(ApiError) as caught:
        await published_owner_candidates(db, store_id=1, query_vector=[1.0]+[0.0]*1535,
                                          embedding_model='new', top_k=5)
    assert caught.value.code == 'INDEX_UNAVAILABLE'


@pytest.mark.asyncio
async def test_successful_empty_search_remains_manual_without_model(monkeypatch):
    db = SimpleNamespace(fetch=AsyncMock(return_value=[dict(category_id=1, category_name='기타', is_system=True)]))
    monkeypatch.setattr(module, 'find_owner_answer_candidates', AsyncMock(return_value=[]))
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(answer_mode='fallback'))
    result = await module.build_knowledge_plan(db, 1, '질문', '답변', usage_context=context(), usage_sink=object())
    assert result.relation_type == 'NEW' and not result.auto_publish

