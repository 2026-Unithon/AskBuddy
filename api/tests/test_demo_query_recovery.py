from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock,patch
import httpx
from openai import APITimeoutError
import pytest
from app.errors import ApiError
from app.learn.demo_retrieval import retrieve
from app.learn.demo_outcome import outcome
from app.reg import embeddings
from app.team.evaluation_budget import BudgetDenied
from app.usage.repository import UsageWriteError

@pytest.mark.asyncio
async def test_timeout_uses_only_same_store_lexical_channel_without_retry():
    embed=AsyncMock(side_effect=APITimeoutError(request=httpx.Request('POST','https://example.invalid')))
    search=AsyncMock(return_value=NS(candidates=[object()]))
    result,mode,reason=await retrieve(None,store_id=9,question='카페모카',embed=embed,search_fn=search,timeout=1,allow_fallback=True)
    embed.assert_awaited_once()
    search.assert_awaited_once_with(None,store_id=9,question='카페모카',query_vector=None)
    assert result.candidates and (mode,reason)==('LEXICAL_AFTER_EMBEDDING_FAILURE','APITimeoutError')

@pytest.mark.asyncio
async def test_no_lexical_hit_after_timeout_is_retryable_not_missing_knowledge():
    with pytest.raises(ApiError) as e:
        await retrieve(None,store_id=9,question='그럼?',embed=AsyncMock(side_effect=TimeoutError()),
            search_fn=AsyncMock(return_value=NS(candidates=())),timeout=1,allow_fallback=True)
    assert e.value.code=='MODEL_UNAVAILABLE' and e.value.retryable

@pytest.mark.asyncio
@pytest.mark.parametrize('error',(UsageWriteError('test'),BudgetDenied('test')))
async def test_budget_and_usage_fail_closed(error):
    search=AsyncMock()
    with pytest.raises(type(error)):
        await retrieve(None,store_id=9,question='카페모카',embed=AsyncMock(side_effect=error),search_fn=search,timeout=1,allow_fallback=True)
    search.assert_not_awaited()

@pytest.mark.asyncio
async def test_success_keeps_vector_and_db_failure_is_not_reported_as_embedding_error():
    search=AsyncMock(side_effect=RuntimeError('db test'))
    with pytest.raises(RuntimeError,match='db test'):
        await retrieve(None,store_id=9,question='카페모카',embed=AsyncMock(return_value=[[1.0]]),search_fn=search,timeout=1,allow_fallback=True)
    search.assert_awaited_once_with(None,store_id=9,question='카페모카',query_vector=[1.0])

def test_query_client_shared_then_closed_at_shutdown():
    embeddings.close_query_client()
    with patch.object(embeddings,'OpenAI') as factory:
        one=embeddings._pooled_query_client(NS(openai_api_key='test'))
        assert one is embeddings._pooled_query_client(NS(openai_api_key='test'))
        factory.assert_called_once()
        embeddings.close_query_client()
        one.close.assert_called_once()

@pytest.mark.asyncio
async def test_outcome_binds_ledger_keys_to_authenticated_member():
    db=NS(fetchval=AsyncMock(return_value=4),fetch=AsyncMock(return_value=[]),fetchrow=AsyncMock(return_value=None))
    from app.contracts.hashing import digest
    with pytest.raises(ApiError) as e:await outcome(db,store_id=9,user_id=31,request_id='same-request')
    assert e.value.status_code==404
    assert db.fetchval.await_args.args[1:]==(9,31)
    assert db.fetch.await_args.args[-1]==digest(dict(member_id=4,request_id='same-request'))
    assert db.fetchrow.await_args.args[1:]==(9,4,'same-request')

@pytest.mark.asyncio
async def test_outcome_rejects_non_staff_without_querying_ledger():
    db=NS(fetchval=AsyncMock(return_value=None),fetch=AsyncMock())
    with pytest.raises(ApiError) as e:await outcome(db,store_id=9,user_id=31,request_id='same-request')
    assert e.value.status_code==403
    db.fetch.assert_not_awaited()
