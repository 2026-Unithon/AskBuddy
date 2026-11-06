from copy import deepcopy
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest

from app.errors import ApiError
from app.learn.dialogue_history import load_history
from app.learn.failed_user_turns import validate_failed_request,validate_failed_head
from app.learn.general_semantics import general_decision,validate_interpretation
from app.learn.grounded_conclusions import RuleCoverage,missing_conclusion_rules,selected_rules
from app.learn.semantic_proposals import proposal_input
from tests.test_r_grounded_conclusions import enabled,modified_verifier
from tests.test_r_general_semantics import setup,provider_for


@pytest.mark.asyncio
async def test_single_wrapped_part_has_same_validated_plan_as_flat_answer(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    flat,_=await general_decision(search,provider=provider_for(search,raw),**kw)
    raw['parts']=[dict(plan=deepcopy(raw['plan']),interpretation=raw.pop('interpretation'),slots=raw.pop('slots'))]
    raw.update(interpretation=None,slots=[])
    wrapped,_=await general_decision(search,provider=provider_for(search,raw),**kw)
    assert wrapped.plan==flat.plan and wrapped.resolved==flat.resolved
    raw['slots']=[dict(slot='entity',value='200',question_quote=kw['question'])]
    with pytest.raises(ValueError):validate_interpretation(search,payload=proposal_input(search,store_id=1,question=kw['question']),proposal=raw,baseline=kw['baseline'])


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['missing_step','invented_quote','omit','duplicate','wrong_rule','wrong_index','none_required'])
async def test_rule_coverage_cannot_hide_missing_application_behind_raw_citation(tmp_path,change):
    search,raw,kw=enabled(tmp_path)
    def corrupt(v):
        rows=v['rule_coverage']
        if change=='missing_step':rows[0].update(conclusion_unit_id=None)
        if change=='invented_quote':rows[0]['conclusion_quote']='원거래 상태를 먼저 확인하세요'
        if change=='omit':rows.pop(0)
        if change=='duplicate':rows.append(deepcopy(rows[0]))
        if change=='wrong_rule':rows[0]['rule_id']='unretrieved'
        if change=='wrong_index':rows[0]['conclusion_unit_id']='c7s0'
        if change=='none_required':
            for row in rows:row['required']=False
    with pytest.raises(ApiError) as error:await general_decision(search,provider=modified_verifier(search,raw,corrupt),**kw)
    assert error.value.code==('GENERAL_VERIFICATION_REJECTED' if change=='missing_step' else 'GENERAL_INVALID_PROPOSAL')
    if change=='missing_step':assert error.value.details['reason_code']=='INCOMPLETE_ANSWER'


@pytest.mark.asyncio
async def test_failed_user_only_history_merges_in_time_order_and_is_bounded():
    now=datetime.now(timezone.utc)
    receipts=[dict(receipt_id=4,original_question='성공한 질문',created_at=now)]
    failures=[dict(failed_turn_id=9,question='A 상태 미확인, B 대기',created_at=now-timedelta(seconds=1))]
    conn=NS(fetchrow=AsyncMock(return_value={'session_id':3}),fetch=AsyncMock(side_effect=[receipts,failures]))
    history=await load_history(conn,store_id=1,member_id=2,session_id=3,include_failed=True,exclude_request_id='current-key')
    assert history.user_turns==('A 상태 미확인, B 대기','성공한 질문')
    assert history.head==4 and history.failed_head==9 and history.failed_turn_ids==(9,)
    sql,*args=conn.fetch.call_args.args
    assert args==[1,2,3,'current-key'] and 'expires_at' in sql and 'not exists' in sql


@pytest.mark.asyncio
async def test_recovery_request_identity_and_concurrent_error_guard():
    conn=NS(fetchrow=AsyncMock(return_value={'session_id':3,'question':'원래 질문'}),fetch=AsyncMock(return_value=[{'failed_turn_id':5}]))
    await validate_failed_request(conn,store_id=1,member_id=2,session_id=3,request_id='request-1',question='원래 질문')
    for session,q in ((9,'원래 질문'),(3,'변경된 질문')):
        with pytest.raises(ApiError) as error:await validate_failed_request(conn,store_id=1,member_id=2,session_id=session,request_id='request-1',question=q)
        assert error.value.code=='IDEMPOTENCY_CONFLICT'
    with pytest.raises(ApiError) as error:await validate_failed_head(conn,store_id=1,member_id=2,session_id=3,request_id='next-key',expected_head=4)
    assert error.value.code=='STALE_DIALOGUE'
