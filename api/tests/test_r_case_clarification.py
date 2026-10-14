"""Case grounding, stored provenance and routing; synthetic model verdicts only."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import pytest
from app.contracts.chat import QuestionContext
from app.errors import ApiError
from app.learn.case_clarification import CaseOption, CONTEXT_KEY, case_context_data, case_context_turns, validate_case_options
from app.learn.general_semantics import general_decision, validate_interpretation
from app.learn.question_contexts import StoredContext, accept_selection
from app.learn.semantic_proposals import proposal_input
from tests.test_r_general_semantics import setup,provider_for
from tests.test_r_verification_routing import rejecting_provider

PRIOR='A는 결제 상태 미확인, B는 환불 승인 대기야.'
QUESTION='그 건은 메시지 읽었대. 인계 완료로 해도 돼?'

def options():
    return tuple(CaseOption(label=x,turn_id=0,question_quote=PRIOR) for x in ('A','B'))

def authored(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    kw.update(question=QUESTION,user_turns=(PRIOR,),context_verified=True,confirmed_slots={})
    payload=proposal_input(search,store_id=1,question=QUESTION,user_turns=(PRIOR,))
    raw['input_hash']=payload['input_hash']
    for slot in raw['slots']:slot['question_quote']=PRIOR
    return search,raw,kw,payload

@pytest.mark.asyncio
async def test_real_failure_shape_now_offers_grounded_cases_without_owner_pending(tmp_path):
    search,raw,kw,_=authored(tmp_path)
    result,audit=await general_decision(search,provider=rejecting_provider(search,raw,
        reason_code='MISSING_USER_INFO',reason_detail='A/B 중 대상 미확정',
        clarification=dict(slot='case',allowed_options=['A','B'],scope_supported=True,
            case_options=[x.model_dump() for x in options()])),**kw)
    assert result.plan.action=='CLARIFY' and result.plan.clarification_slot=='case'
    assert result.confirmed_slots=={} and result.resolved.entity_id==''
    assert result.plan.allowed_options==('A','B') and result.semantic_context is None
    assert audit['fallback_action']=='CLARIFY'
    stored=case_context_data(result.plan,result.resolved)
    now=datetime.now(timezone.utc)
    ctx=StoredContext(QuestionContext(context_id=result.plan.context_id,store_id='1',member_id='2',
        chat_session_id='3',contract_version='v2',expires_at=now+timedelta(minutes=10),original_question=QUESTION,
        proposed_slots=stored,clarify_turns=1),0,1,'case',('A','B'))
    accepted=accept_selection(ctx,option='A',expected_state_revision=0,knowledge_revision=2,now=now)
    assert accepted.context.confirmed_slots=={'case':'A'}
    assert case_context_turns(accepted.context)==(PRIOR,)
    assert CONTEXT_KEY in accepted.context.proposed_slots  # User provenance survives publication refresh.
    assert ctx.context.confirmed_slots=={}  # No mutable context leakage.

@pytest.mark.asyncio
async def test_proposer_can_offer_cases_and_requires_independent_verification(tmp_path):
    search,raw,kw,payload=authored(tmp_path)
    raw.update(plan=dict(snapshot_id=payload['snapshot_id'],knowledge_revision=payload['knowledge_revision'],
        action='CLARIFY',clarification_slot='case',allowed_options=['A','B']),
        interpretation=None,slots=[],case_options=[o.model_dump() for o in options()])
    # Fixture helper validates public plans; server owns the model context ID.
    from app.learn.general_wire import parse_proposal
    parsed=parse_proposal(raw)
    provider=provider_for(search,parsed.model_dump(mode='json'))
    from unittest.mock import AsyncMock
    original=provider.side_effect
    async def call(prompt,*,schema,**kwargs):
        from app.learn.general_semantics import GeneralProposal
        if schema is GeneralProposal:return raw
        return await original(prompt,schema=schema,**kwargs)
    result,audit=await general_decision(search,provider=AsyncMock(side_effect=call),**kw)
    assert result.plan.action=='CLARIFY' and audit['status']=='STRUCTURE_AND_MODEL_CHECKED'
    assert result.resolved.case_user_turns==(PRIOR,)
    limited=validate_interpretation(search,payload=payload,proposal=raw,baseline=kw['baseline'],
        confirmed_slots={},clarify_turns=2)
    assert limited.plan.action=='ESCALATE'

@pytest.mark.parametrize('change',['invented','foreign_turn','forged_quote','duplicate','wrong_order','confirmed','word_fragment'])
def test_case_labels_cannot_come_from_candidates_or_invented_turns(change):
    data=[x.model_dump() for x in options()];allowed=['A','B'];slots={}
    if change=='invented':data[1]['label']='C';allowed=['A','C']
    if change=='foreign_turn':data[0]['turn_id']=2
    if change=='forged_quote':data[0]['question_quote']='A는 완료야'
    if change=='duplicate':data[1]=data[0];allowed=['A','A']
    if change=='wrong_order':allowed=['B','A']
    if change=='confirmed':slots={'case':'A'}
    turns=(PRIOR,)
    if change=='word_fragment':
        turns=('APP 결제와 B 건',)
        for o in data:o['question_quote']=turns[0]
    with pytest.raises(ValueError):validate_case_options(tuple(CaseOption(**x) for x in data),
        allowed_options=allowed,question=QUESTION,user_turns=turns,confirmed_slots=slots)

@pytest.mark.asyncio
async def test_case_evidence_cannot_be_attached_to_an_answer(tmp_path):
    search,raw,kw,_=authored(tmp_path)
    raw['case_options']=[x.model_dump() for x in options()]
    with pytest.raises(ApiError) as error:await general_decision(search,provider=provider_for(search,raw),**kw)
    assert error.value.code=='GENERAL_INVALID_PROPOSAL'
