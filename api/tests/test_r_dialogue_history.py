from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from app.errors import ApiError
from app.learn.dialogue_history import DialogueHistory, load_history, validate_history_head, retrieval_question


@pytest.mark.asyncio
async def test_history_is_chronological_user_only_and_scoped_to_session_member_store():
    conn = NS(fetchrow=AsyncMock(return_value={'session_id':3}),fetch=AsyncMock(return_value=[
        dict(receipt_id=8,created_at=2,original_question='A 주문만 3개로 정정'),
        dict(receipt_id=5,created_at=1,original_question='A는 2개, B는 4개')]))
    history = await load_history(conn,store_id=1,member_id=2,session_id=3)
    assert history == DialogueHistory((5,8),('A는 2개, B는 4개','A 주문만 3개로 정정'))
    sql,*args = conn.fetch.call_args.args
    assert args == [1,2,3] and 'limit 10' in sql and 'original_question' in sql
    assert "case when response->>'action'='CLARIFY'" in sql and 'resolved_query' not in sql
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
    from app.contracts.errors import error as envelope
    body=envelope(error.value.code,error.value.message,request_id='dialogue-race')
    assert body.http_status==409 and body.error.retryable


def test_search_history_is_bounded_and_does_not_replace_current_question():
    history=DialogueHistory(tuple(range(10)),tuple(str(i)*1000 for i in range(10)))
    query=retrieval_question('현재 질문',history)
    assert query.startswith('현재 질문\n') and '6666' not in query and '7777' in query
    assert len(query)<3100


@pytest.mark.asyncio
async def test_reply_order_is_preserved_without_reusing_past_factual_answers():
    from app.learn.dialogue_history import reply_context
    conn=NS(fetchrow=AsyncMock(return_value={'session_id':3}),fetch=AsyncMock(return_value=[
        dict(receipt_id=4,created_at=4,original_question='보관 위치',action='ANSWER',cited='[["1","2"],["1","2"],["7","1"]]'),
        dict(receipt_id=3,created_at=3,original_question='그라인더 청소',action='CLARIFY',prompt='어떤 정보인가요?',
            slot='predicate',options='["제조 순서","보관 위치"]')]))
    history=await load_history(conn,store_id=1,member_id=2,session_id=3)
    snapshot=NS(cards=[NS(card_id='1',card_version_id='2',title='그라인더'),NS(card_id='7',card_version_id='3',title='다른 장비')])
    assert reply_context(history,snapshot)==[
        dict(after_user_turn=0,action='CLARIFY',prompt='어떤 정보인가요?',asked_for='predicate',displayed_options=['제조 순서','보관 위치']),
        dict(after_user_turn=1,action='ANSWER',cited_subjects=['그라인더'])]
    assert '그라인더' in retrieval_question('그건 어디에 보관해?',history,snapshot=snapshot)
    assert retrieval_question('다른 장비 청소법은?',history,snapshot=snapshot)=='다른 장비 청소법은?'
    assert '보관 위치' in retrieval_question('다른 장비는?',history,snapshot=snapshot)


def test_fallback_for_second_named_subject_or_ambiguous_reference_uses_staff_order():
    from app.learn.dialogue_history import followup_subjects, scoped_fallback
    from app.learn.planner import Decision
    from app.learn.answer_validation import ResolvedSelection
    from app.contracts.answer import AnswerPlan
    from uuid import uuid4
    snap=NS(cards=[NS(entity_id='2',title='세척솔'),NS(entity_id='1',title='그라인더')],snapshot_id='1',knowledge_revision='1')
    prior=DialogueHistory(user_turns=('그라인더랑 세척솔을 둘 다 청소하려고 해.',))
    q='그럼 두 번째 장비는 어디에 보관해?'
    baseline=Decision(AnswerPlan(snapshot_id='1',knowledge_revision='1',action='CLARIFY',context_id=uuid4(),
        clarification_slot='entity',allowed_options=('모든 장비','다른 메뉴')),ResolvedSelection('','',(),question=q),{},None)
    miss=scoped_fallback(baseline,q,prior,snap)
    assert miss.plan.action=='ESCALATE' and miss.resolved.entity_id=='2' and not miss.confirmed_slots
    ambiguous=scoped_fallback(baseline,'그건 어디에 보관해?',prior,snap)
    assert ambiguous.plan.allowed_options==('그라인더','세척솔')
    for new_topic in ('그라인더 청소 순서는?', '두 번째 단계는?', '영수증 용지 위치는?'):
        assert scoped_fallback(baseline,new_topic,prior,snap) is baseline
    unknown=DialogueHistory(user_turns=('행주랑 그라인더랑 세척솔은?',))
    assert not followup_subjects(q,unknown,snap)
    assert not followup_subjects(q,DialogueHistory(user_turns=(*prior.user_turns,'다른 질문이야')),snap)
