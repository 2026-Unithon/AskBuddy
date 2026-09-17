import asyncio
from dataclasses import replace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contracts.publication import ApplyOwnerAnswerResult
from app.errors import ApiError
from app.learn.owner_handoff import retry_delay,should_retry,finish_owner_event
from app.learn.planner import decide
from app.learn.answer_storage import ContextChoice,validate_context_question,pending_key
from app.learn.approved_renderer import render
from app.team.evaluation_usage import evaluation_usage_scope,request_usage_sink,EvaluationUsageSink
from tests import test_r_conditional_scope as conditional
from tests import test_r_raw_quantity as raw


def failure(code='MODEL_UNAVAILABLE',retryable=True):
    return ApplyOwnerAnswerResult(status='FAILED',retryable=retryable,error=dict(
        code=code,message='synthetic failure',retryable=code=='MODEL_UNAVAILABLE',request_id='retry-test'))


def test_retry_budget_and_error_policy():
    assert [retry_delay(n) for n in range(1,11)]==[2,4,8,16,32,60,60,60,60,60]
    assert should_retry(failure(),9)
    assert not should_retry(failure(),10)
    # A caller cannot promote a permission error by setting the outer retryable bit.
    assert not should_retry(failure('FORBIDDEN'),1)
    assert not should_retry(failure(retryable=False),1)
    with pytest.raises(ValueError):retry_delay(0)


@pytest.mark.asyncio
async def test_last_failure_is_terminal_and_alerted(monkeypatch):
    conn=MagicMock()
    conn.is_in_transaction.return_value=True
    conn.fetchrow=AsyncMock(return_value=dict(owner_answer_id=4,question_id=3,revision_no=1))
    conn.fetchval=AsyncMock(side_effect=[3,10,1,9])
    conn.execute=AsyncMock()
    alert=AsyncMock()
    monkeypatch.setattr('app.learn.owner_handoff.create_notification_event',alert)
    await finish_owner_event(conn,store_id=1,event_id=5,claim_token='claim',result=failure())
    assert alert.await_count==1
    assert alert.call_args.kwargs['store_id']==1
    assert any('TERMINAL:RETRY_EXHAUSTED' in c.args for c in conn.execute.call_args_list)
    assert not any('insert into outbox_consumptions' in c.args[0] for c in conn.execute.call_args_list)


@pytest.mark.asyncio
async def test_expired_worker_cannot_complete():
    conn=MagicMock()
    conn.is_in_transaction.return_value=True
    conn.fetchrow=AsyncMock(return_value=dict(owner_answer_id=4,question_id=3,revision_no=1))
    conn.fetchval=AsyncMock(side_effect=[3,None])
    conn.execute=AsyncMock()
    with pytest.raises(ApiError):
        await finish_owner_event(conn,store_id=1,event_id=5,claim_token='expired',result=failure())
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_evaluation_scope_is_task_local_and_resets():
    async def scoped(run):
        with evaluation_usage_scope(store_id=1,evaluation_run_id=run):
            await asyncio.sleep(0)
            sink=request_usage_sink(None,store_id=1)
            assert isinstance(sink,EvaluationUsageSink)
            assert sink._scope.evaluation_run_id==run
            with pytest.raises(ValueError):request_usage_sink(None,store_id=2)
        assert not isinstance(request_usage_sink(None,store_id=1),EvaluationUsageSink)
    await asyncio.gather(scoped('11'),scoped('12'))
    with pytest.raises(RuntimeError):
        with evaluation_usage_scope(store_id=1,evaluation_run_id='13'):raise RuntimeError()
    assert not isinstance(request_usage_sink(None,store_id=1),EvaluationUsageSink)


def test_verified_followup_preserves_assessment_and_rejects_rebinding():
    original='점주 확인 후 장비 세척 후 라테 우유 얼마나?'
    choice=ContextChoice(uuid4(),1,'HOT')
    decision=decide(conditional.search(),store_id=1,question=original+' HOT',
        confirmed_slots={'temperature':'HOT'},context_id=choice.context_id,context_verified=True)
    assert decision.plan.action=='ANSWER'
    validate_context_question(question='HOT',resolved=decision.resolved,choice=choice,original_question=original)
    for changed in ('라테 우유 얼마나?','단체 주문 라테 우유 얼마나?'):
        with pytest.raises(ApiError):
            validate_context_question(question='HOT',resolved=decision.resolved,choice=choice,original_question=changed)
    with pytest.raises(ApiError):
        validate_context_question(question='ICE',resolved=decision.resolved,choice=choice,original_question=original)


def test_explicit_disjunction_preserves_branch_in_grouping():
    result=conditional.search(conditions=('(점주 확인 후 또는 관리자 확인 후)','장비 세척 후'))
    keys=[]
    for branch in ('점주 확인 후','관리자 확인 후'):
        question=branch+' 및 장비 세척 후 HOT 라테 우유 얼마나?'
        decision=decide(result,store_id=1,question=question)
        assert decision.plan.action=='ANSWER'
        assert '(점주 확인 후 또는 관리자 확인 후)' in render(decision.plan,result.snapshot,store_id=1,request_id='or-test').message
        missing=decide(result,store_id=1,question=question.replace('HOT','ICE'))
        assert missing.semantic_context
        keys.append(pending_key(store_id=1,semantic_context=missing.semantic_context))
    assert keys[0]!=keys[1]
    for prefix in ('점주 확인 후','장비 세척 후','점주 확인 전 장비 세척 후'):
        assert decide(result,store_id=1,question=prefix+' HOT 라테 우유 얼마나?').plan.action!='ANSWER'


def test_approved_procedure_raw_is_whole_and_task_bound():
    text='라테 준비 절차:\n1. 장비를 세척한다.\n2. 점주 확인 후 준비한다.\n단체 주문은 별도로 확인한다.'
    result=raw.search(text)
    decision=decide(result,store_id=1,question='라테 준비 방법 알려줘')
    assert decision.plan.action=='ANSWER'
    assert render(decision.plan,result.snapshot,store_id=1,request_id='procedure-test').message==text
    for question in ('라테 제조 방법 알려줘','라테 준비 방법 알려줘 단체 주문도','라테 준비 방법 두 배로 알려줘'):
        assert decide(result,store_id=1,question=question).plan.action!='ANSWER'


def test_unstructured_raw_has_no_automatic_semantic_approval():
    assert decide(raw.search('장비를 세척한 후 라테를 준비한다.'),store_id=1,
        question='라테 준비 방법 알려줘').plan.action!='ANSWER'


@pytest.mark.asyncio
async def test_raw_requirement_survives_http_collection_and_report():
    import json
    import httpx
    from tests.test_r_v2_evaluation import manifest,answer
    from app.team.v2_evaluation import EvaluationManifest,collect_v2_run,build_v2_report
    payload=manifest().model_dump(mode='json')
    payload['cases'][0]['required_raw_blocks']=[dict(card_id='1',card_version_id='1',block_id='b',raw_span_id='1')]
    truth=EvaluationManifest.model_validate(payload)
    async def handle(request):
        if request.url.path.endswith('/sessions'):return httpx.Response(200,json={'session_id':'1'})
        body=answer(json.loads(request.content)['request_id'])  # typed-only citation is insufficient
        return httpx.Response(200,json=body,headers={'x-answer-receipt-id':'9'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle),base_url='http://synthetic') as client:
        run=await collect_v2_run(client,truth,headers={},configuration={},provider_mode='SYNTHETIC')
    label=dict(question_id='q1',row_hash=run['rows'][0]['row_hash'],reviewer='synthetic',reason='meaning only',semantic_correct=True)
    report=build_v2_report(run,[label])
    assert report['schema_version']=='r_v2_report/v2'
    assert report['rows'][0]['semantic_correct'] is True
    assert report['rows'][0]['required_raw_cited'] is False
    assert report['grounded_answer_count']==0
    assert run['manifest']['cases'][0]['required_raw_blocks']==payload['cases'][0]['required_raw_blocks']


@pytest.mark.asyncio
async def test_v2_faq_scope_prevents_same_followup_cross_context_merge():
    from datetime import datetime,timezone
    from app.learn.faq import v2_faq_rows,cluster_faq_rows
    base=dict(receipt_id=1,original_question='HOT',member_id=1,created_at=datetime.now(timezone.utc),
        card_id=1,published_version_id=1,card_title='synthetic',card_content='approved',category_id=1,category_name='test')
    rows=[dict(base,resolved_query=dict(entity='1',predicate='milk_amount',variants=[['HOT',None]],confirmed_slots={}),
        context_snapshot={'context':{'original_question':question}})
        for question in ('점주 확인 후 라테 우유 얼마나?','장비 세척 후 라테 우유 얼마나?')]
    conn=MagicMock()
    conn.fetch=AsyncMock(return_value=rows)
    result=await v2_faq_rows(conn,store_id=1)
    assert conn.fetch.call_args.args[1]==1
    assert len(cluster_faq_rows(result))==2
    assert result[0]['question_text'].startswith('점주 확인 후')
    assert len(cluster_faq_rows([result[0],dict(result[0],member_id=2)]))==1


@pytest.mark.asyncio
async def test_old_frozen_manifest_still_reports_without_rewriting():
    from tests.test_r_v2_evaluation import V2EvaluationTest
    from app.contracts.hashing import digest
    from app.team.v2_evaluation import build_v2_report
    run=await V2EvaluationTest().collect()
    for case in run['manifest']['cases']:case.pop('required_raw_blocks',None)
    run['manifest_hash']=digest(run['manifest'])
    run['run_hash']=digest({k:v for k,v in run.items() if k!='run_hash'})
    assert build_v2_report(run)['grounded_answer_rate'] is None


def mock_pool(conn):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def acquire():yield conn
    @asynccontextmanager
    async def transaction():yield
    conn.transaction=transaction
    pool=MagicMock()
    pool.acquire=acquire
    return pool


@pytest.mark.asyncio
async def test_manual_retry_keeps_event_and_audits_previous_attempts():
    from app.learn.owner_handoff import retry_owner_event
    conn=MagicMock()
    conn.fetchval=AsyncMock(side_effect=[9,3,1]) # owner, question lock, latest revision
    conn.fetchrow=AsyncMock(side_effect=[None,dict(owner_answer_id=4,question_id=3,revision_no=1),
        dict(attempts=10,last_error='TERMINAL:RETRY_EXHAUSTED')])
    conn.execute=AsyncMock()
    result=await retry_owner_event(mock_pool(conn),store_id=1,member_id=2,event_id=5,
        request_id='retry-manual-1',reason='공급자 복구 확인')
    assert result['event_id']=='5' and result['previous_attempts']==10
    queries=[call.args[0] for call in conn.execute.call_args_list]
    assert any('R_OWNER_RETRY' in query for query in queries)
    assert not any('insert into outbox_events' in query for query in queries)
    assert any('attempts=0' in query for query in queries)


@pytest.mark.asyncio
async def test_manual_retry_replay_never_resets_worker_again():
    from app.learn.owner_handoff import retry_owner_event
    from app.contracts.hashing import digest
    conn=MagicMock()
    conn.fetchval=AsyncMock(return_value=9)
    conn.fetchrow=AsyncMock(return_value=dict(body_hash=digest(dict(event_id=5,reason='restored')),
        response=dict(event_id='5',previous_attempts=10,status='PENDING',reason='restored')))
    conn.execute=AsyncMock()
    pool=mock_pool(conn)
    result=await retry_owner_event(pool,store_id=1,member_id=2,event_id=5,request_id='same-key-1',reason='restored')
    assert result['previous_attempts']==10
    assert not any('update outbox_leases' in call.args[0] for call in conn.execute.call_args_list)
    with pytest.raises(ApiError):
        await retry_owner_event(pool,store_id=1,member_id=2,event_id=6,request_id='same-key-1',reason='restored')


@pytest.mark.asyncio
@pytest.mark.parametrize('owner,event,expected',[(None,None,403),(9,None,404)])
async def test_manual_retry_permissions_and_foreign_event(owner,event,expected):
    from app.learn.owner_handoff import retry_owner_event
    conn=MagicMock()
    conn.fetchval=AsyncMock(return_value=owner)
    conn.fetchrow=AsyncMock(side_effect=[None,event])
    conn.execute=AsyncMock()
    with pytest.raises(ApiError) as exc:
        await retry_owner_event(mock_pool(conn),store_id=2,member_id=2,event_id=5,
            request_id='denied-key',reason='test')
    assert exc.value.status_code==expected
    assert not any('update ' in call.args[0] for call in conn.execute.call_args_list)


@pytest.mark.parametrize('yes,no',[
    ('단체 주문인 경우','단체 주문이 아닌 경우'),
    ('온도 60도 이상','온도 60도 미만'),
])
def test_mutually_exclusive_approved_branches_select_only_applicable_value(yes,no):
    from app.contracts.hashing import snapshot_digest
    result=conditional.search(conditions=(yes,))
    first=result.snapshot.fact_revisions[0]
    other=first.model_copy(update=dict(fact_id='2',fact_revision_id='2',conditions=(no,),
        quantity=first.quantity.model_copy(update=dict(value='100')),
        assertion='HOT 라테 우유 100ml',original_assertion='HOT 라테 우유 100ml'))
    card=result.snapshot.cards[0]
    block=card.blocks[0].model_copy(update=dict(fact_revision_ids=('1','2')))
    snapshot=result.snapshot.model_copy(update=dict(fact_revisions=(first,other),
        cards=(card.model_copy(update=dict(blocks=(block,))),)))
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    result=replace(result,snapshot=snapshot)
    for condition,expected in ((yes,'1'),(no,'2')):
        answer=decide(result,store_id=1,question=condition+' HOT 라테 우유 얼마나?')
        assert answer.plan.action=='ANSWER'
        assert answer.plan.selected_blocks[0].fact_revision_ids==(expected,)


def test_overlapping_numeric_or_different_axes_do_not_prove_exclusion():
    from app.learn.conditional_scope import exclusive_conditions
    assert not exclusive_conditions(('온도 60도 이상',),('온도 60도 이하',))
    assert not exclusive_conditions(('온도 60도 이상',),('수량 60개 미만',))
    assert not exclusive_conditions(('단체 주문인 경우',),())


def test_retry_http_requires_auth_and_rejects_incomplete_body(monkeypatch):
    from datetime import datetime,timedelta,timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.learn.v2_router import router
    from app.deps import create_token
    settings=SimpleNamespace(jwt_secret='synthetic-retry-test-key-'*4,jwt_algorithm='HS256')
    monkeypatch.setattr('app.deps.get_settings',lambda:settings)
    app=FastAPI()
    app.include_router(router,prefix='/learn')
    with TestClient(app) as client:
        unauth=client.post('/learn/v2/owner-events/1/retry',json=dict(request_id='retry-test',reason='test'))
        assert unauth.status_code==401 and unauth.json()['contract_version']=='v2'
        token=create_token(dict(user_id=1,store_id=1,role='OWNER',exp=datetime.now(timezone.utc)+timedelta(minutes=5)))
        invalid=client.post('/learn/v2/owner-events/1/retry',headers={'Authorization':'Bearer '+token},json={})
        assert invalid.status_code==422 and invalid.json()['error']['code']=='INVALID_CONTRACT'
