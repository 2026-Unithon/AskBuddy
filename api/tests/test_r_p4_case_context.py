"""P4 regression: exact evidence, independent case scope and paraphrase binding."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import pytest

from app.contracts.answer import AnswerPlan
from app.contracts.hashing import snapshot_digest
from app.learn.grounded_conclusions import (CaseActionReview,CaseRequirements,GroundedConclusion,
    SituationReview,case_requirement_keys,conclusion_units,missing_case_actions,unsupported_situations)
from app.learn.general_semantics import validate_interpretation
from app.learn.semantic_proposals import proposal_input
from app.learn.clarification_scope import validate_options
from app.learn.planner import decide
from app.reg.hybrid import Candidate
from tests.test_r_fact_consumption import split_search

FROZEN=json.loads((Path(__file__).parent/'fixtures/r_p4_state_expression_live_20261008.json').read_text('utf-8'))


def live_state():
    cs=tuple(GroundedConclusion.model_validate(c) for c in FROZEN['proposal']['conclusions'])
    review=deepcopy(FROZEN['verification']['case_action_review'])
    request=FROZEN['request']['input']
    return cs,review,dict(question=request['question'],user_turns=tuple(request['user_turns']))


def test_historical_paraphrase_is_not_accepted_without_sentence_and_user_binding():
    cs,raw,kw=live_state()
    assert raw['cases'][0]['state']['quote']=='메시지 읽었대'
    assert missing_case_actions(CaseActionReview.model_validate(raw),cs,**kw)==[0]
    # Synthetic v12 audit of unchanged output. Not a corrected historical model verdict.
    unit=next(u for u in conclusion_units(cs) if '메시지를 읽었다는' in u['text'])
    raw['cases'][0]['state_unit_id']=unit['unit_id']
    audit=SituationReview(conclusion_unit_id=unit['unit_id'],status='GROUNDED_CASE_FACTS',
        user_evidence=cs[unit['conclusion_id']].user_evidence,rationale='Synthetic state paraphrase binding only')
    assert missing_case_actions(CaseActionReview.model_validate(raw),cs,situation_review=(audit,),**kw)==[]
    for changed in (audit.model_copy(update={'status':'NO_CASE_FACTS','user_evidence':()}),
                    audit.model_copy(update={'user_evidence':()})):
        assert missing_case_actions(CaseActionReview.model_validate(raw),cs,situation_review=(changed,),**kw)==[0]
    raw['cases'][0]['state_unit_id']='c7s0'
    with pytest.raises(ValueError):missing_case_actions(CaseActionReview.model_validate(raw),cs,**kw)


def requirements():
    return CaseRequirements(scope='CASE_ACTIONS',rationale='Named states in handoff question',cases=[
        dict(subject=dict(turn_id=0,quote=n),state=dict(turn_id=0,quote=s))
        for n,s in [('A','결제 미확인'),('B','환불 승인 대기')]])


def test_verifier_cannot_narrow_named_case_question_to_common_form_or_omit_b():
    q='A 결제 미확인, B 환불 승인 대기를 인계할 때 무엇을 적나?'
    req=requirements()
    for review in (CaseActionReview(scope='NOT_APPLICABLE',rationale='Only general fields',cases=[]),
                   CaseActionReview(scope='CASE_ACTIONS',rationale='Only A',cases=[
                       dict(subject=req.cases[0].subject,state=req.cases[0].state)])):
        assert missing_case_actions(review,(),question=q,user_turns=(),requirements=req)
    with pytest.raises(ValueError):case_requirement_keys(req,question='다른 질문',user_turns=())
    with pytest.raises(ValueError,match='selected case'):
        case_requirement_keys(req,question=q,user_turns=(),selected_case='A')
    b=req.model_copy(update={'cases':(req.cases[1],)})
    with pytest.raises(ValueError,match='selected case'):
        case_requirement_keys(b,question=q,user_turns=(),selected_case='A')


def test_latest_state_correction_cannot_match_old_requirement_and_general_topic_stays_general():
    req=CaseRequirements(scope='CASE_ACTIONS',rationale='A corrected now',cases=[
        dict(subject=dict(turn_id=1,quote='A'),state=dict(turn_id=1,quote='결제 완료'))])
    stale=CaseActionReview(scope='CASE_ACTIONS',rationale='Old state',cases=[
        dict(subject=dict(turn_id=0,quote='A'),state=dict(turn_id=0,quote='결제 미확인'))])
    assert missing_case_actions(stale,(),question='A는 결제 완료로 정정',user_turns=('A 결제 미확인',),requirements=req)
    general=CaseRequirements(scope='NOT_APPLICABLE',rationale='New unrelated general question',cases=[])
    assert missing_case_actions(CaseActionReview(**general.model_dump()),(),question='일반 양식은?',
        user_turns=('A 결제 미확인',),requirements=general)==[]


def test_supported_verdict_still_cannot_approve_unconfirmed_case_state():
    cs,_,kw=live_state()
    reviews=[SituationReview(conclusion_unit_id=u['unit_id'],status='UNSUPPORTED_CASE_FACTS',
        user_evidence=(),rationale='Synthetic unconfirmed completion assertion') for u in conclusion_units(cs)]
    assert unsupported_situations(reviews,cs,**kw)


def test_general_fact_answer_accepts_canonical_subject_of_split_cards_but_not_other_entity():
    search=split_search();snap=search.snapshot
    facts=tuple(f.model_copy(update={'requires':()}) for f in snap.fact_revisions)
    snap=snap.model_copy(update={'fact_revisions':facts})
    snap=snap.model_copy(update={'snapshot_hash':snapshot_digest(snap)})
    search=replace(search,snapshot=snap);q='HOT 라테 우유 투입량 설명'
    payload=proposal_input(search,store_id=1,question=q)
    raw=dict(input_hash=payload['input_hash'],snapshot_hash=snap.snapshot_hash,
        plan=dict(snapshot_id=snap.snapshot_id,knowledge_revision=snap.knowledge_revision,action='ANSWER',
            selected_blocks=[dict(card_id='1',card_version_id='1',block_id='b',fact_revision_ids=['1'])]),
        interpretation=dict(entity_id='1',predicate='milk_amount',variants=[['HOT',None]],target_fact_ids=['1']),
        slots=[dict(slot=k,value=v,question_quote=q) for k,v in [('entity','1'),('predicate','milk_amount'),('temperature','HOT')]])
    kw=dict(payload=payload,proposal=raw,baseline=decide(search,store_id=1,question=q))
    assert validate_interpretation(search,confirmed_slots={'entity':'라테'},**kw).plan.action=='ANSWER'
    with pytest.raises(ValueError,match='contradicts context'):
        validate_interpretation(search,confirmed_slots={'entity':'다른대상'},**kw)


def test_entity_choice_is_one_subject_per_entity_not_one_option_per_split_card():
    search=split_search();snap=search.snapshot
    f=snap.fact_revisions[0].model_copy(update={'fact_revision_id':'3','fact_id':'3','entity_id':'3','subject':'다른음료','requires':()})
    c=snap.cards[0].model_copy(update={'card_id':'3','card_version_id':'3','entity_id':'3','title':'다른음료 1/2',
        'blocks':(snap.cards[0].blocks[0].model_copy(update={'fact_revision_ids':('3',)}),)})
    search=replace(search,snapshot=snap.model_copy(update={'cards':(*snap.cards,c),'fact_revisions':(*snap.fact_revisions,f)}),
        candidates=(*search.candidates,Candidate('3','3','b',None,None,0)))
    from uuid import uuid4
    plan=AnswerPlan(snapshot_id=snap.snapshot_id,knowledge_revision=snap.knowledge_revision,action='CLARIFY',
        clarification_slot='entity',allowed_options=('라테','다른음료'),context_id=uuid4())
    validate_options(search,plan=plan,slots={})
    with pytest.raises(ValueError):validate_options(search,plan=plan.model_copy(update={
        'allowed_options':tuple(c.title for c in search.snapshot.cards)}),slots={})


@pytest.mark.asyncio
async def test_grounded_answer_requires_question_scope_before_verification(tmp_path):
    from tests.test_r_grounded_conclusions import enabled
    from tests.test_r_general_semantics import provider_for
    from app.learn.general_semantics import general_decision
    from app.errors import ApiError
    search,raw,kw=enabled(tmp_path);raw.pop('case_requirements')
    provider=provider_for(search,raw)
    with pytest.raises(ApiError) as error:await general_decision(search,provider=provider,**kw)
    assert error.value.code=='GENERAL_INVALID_PROPOSAL' and provider.await_count==1
