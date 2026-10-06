from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from app.errors import ApiError
from app.learn.dialogue_history import DialogueHistory, load_history, validate_history_head, retrieval_question


@pytest.mark.asyncio
async def test_history_is_chronological_user_only_and_scoped_to_session_member_store():
    conn = NS(fetchrow=AsyncMock(return_value={'session_id':3}),fetch=AsyncMock(return_value=[
        dict(receipt_id=8,original_question='A 주문만 3개로 정정'),
        dict(receipt_id=5,original_question='A는 2개, B는 4개')]))
    history = await load_history(conn,store_id=1,member_id=2,session_id=3)
    assert history == DialogueHistory((5,8),('A는 2개, B는 4개','A 주문만 3개로 정정'))
    sql,*args = conn.fetch.call_args.args
    assert args == [1,2,3] and 'limit 10' in sql and 'original_question' in sql
    assert 'response' not in sql and 'resolved_query' not in sql
    assert history.head == 8
    assert retrieval_question('B는 몇 개였지?',history).startswith('B는 몇 개였지?\n')


@pytest.mark.asyncio
@pytest.mark.parametrize('store,member,session', [(9,2,3),(1,9,3),(1,2,9)])
async def test_foreign_scope_returns_404_before_reading_history(store,member,session):
    conn=NS(fetchrow=AsyncMock(return_value=None),fetch=AsyncMock())
    with pytest.raises(ApiError) as error:
        await load_history(conn,store_id=store,member_id=member,session_id=session)
    assert error.value.status_code == 404
    assert conn.fetchrow.call_args.args[1:] == (store,member,session)
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_history_and_concurrent_turn_guard():
    conn=NS(fetchrow=AsyncMock(return_value={'session_id':3}),fetch=AsyncMock(return_value=[]),fetchval=AsyncMock(return_value=0))
    history=await load_history(conn,store_id=1,member_id=2,session_id=3)
    assert history.head==0 and retrieval_question('처음 질문',history)=='처음 질문'
    await validate_history_head(conn,store_id=1,member_id=2,session_id=3,expected_head=0)
    conn.fetchval.return_value=4
    with pytest.raises(ApiError) as error:
        await validate_history_head(conn,store_id=1,member_id=2,session_id=3,expected_head=0)
    assert error.value.code=='STALE_DIALOGUE' and error.value.retryable


def test_search_history_is_bounded_and_does_not_replace_current_question():
    history=DialogueHistory(tuple(range(10)),tuple(str(i)*1000 for i in range(10)))
    query=retrieval_question('현재 질문',history)
    assert query.startswith('현재 질문\n') and '6666' not in query and '7777' in query
    assert len(query)<3100
