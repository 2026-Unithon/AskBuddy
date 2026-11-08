from dataclasses import replace
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest

from app.contracts.common import Quantity
from app.contracts.hashing import snapshot_digest
from app.learn.answer_validation import AnswerReferenceError,validate_answer_for_question
from app.learn.general_semantics import general_decision
from app.learn.grounded_calculations import calculable_unit
from app.learn.planner import decide
from app.learn.approved_renderer import render
from tests.test_r_general_semantics import setup
from tests import test_r_planner as fixtures

def unitless_search():
    search=fixtures.PlannerTest().search()
    old=search.snapshot.fact_revisions[0]
    fact=old.model_copy(update={'quantity':Quantity(value='225',unit=None)})
    snapshot=search.snapshot.model_copy(update={'fact_revisions':(fact,)})
    snapshot=snapshot.model_copy(update={'snapshot_hash':snapshot_digest(snapshot)})
    return replace(search,snapshot=snapshot)

@pytest.mark.asyncio
async def test_unitless_candidate_does_not_block_provider_dispatch(tmp_path,monkeypatch):
    search=unitless_search(); _,__,kwargs,release=setup(tmp_path)
    from app.learn.general_semantics import Release
    monkeypatch.setattr('app.learn.general_semantics.load_release',lambda *_:Release(**release))
    class ProviderReached(Exception):pass
    provider=AsyncMock(side_effect=ProviderReached())
    from app.errors import ApiError
    with pytest.raises(ApiError) as caught:await general_decision(search,**kwargs,provider=provider)
    provider.assert_awaited_once()
    assert provider.await_args.kwargs['calculation_fact_ids']==()
    assert caught.value.details==dict(phase='proposal_provider',error_type='ProviderReached')

@pytest.mark.asyncio
async def test_preparation_error_keeps_its_phase(tmp_path,monkeypatch):
    from app.errors import ApiError
    search,_,kwargs,_=setup(tmp_path)
    provider=AsyncMock()
    def fail(*args,**kwargs):
        raise AttributeError('test preparation error')
    monkeypatch.setattr('app.learn.general_semantics.proposal_input',fail)
    with pytest.raises(ApiError) as caught:
        await general_decision(search,**kwargs,provider=provider)
    provider.assert_not_awaited()
    assert caught.value.details==dict(phase='proposal_input',error_type='AttributeError')

def test_unitless_fact_can_be_read_verbatim_but_not_invented_as_operand():
    search=unitless_search()
    decision=decide(search,store_id=1,question='라테 카드 원문 보여줘.')
    assert decide(search,store_id=1,question='이번엔 라테 카드 원문 보여줘.').plan==decision.plan
    assert decision.plan.action=='ANSWER' and not calculable_unit(None)
    response=render(decision.plan,search.snapshot,store_id=1,request_id='literal-regression',resolved=decision.resolved)
    assert search.snapshot.fact_revisions[0].assertion in response.message
    assert response.citations[0].fact_revision_id=='1'
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(decision.plan,search.snapshot,replace(decision.resolved,question='라테를 3배로 계산해줘'),store_id=1)

def test_unknown_menu_or_unretrieved_block_does_not_get_a_whole_card_answer():
    search=unitless_search()
    assert decide(search,store_id=1,question='말차라테 카드 원문 보여줘.').plan.action!='ANSWER'
    assert decide(replace(search,candidates=()),store_id=1,question='라테 카드 원문 보여줘.').plan.action!='ANSWER'


@pytest.mark.parametrize('menu,first,reply',[
    ('할메가커피','할메가커피','요금'),('딸기요거트스무디','금액','딸기요거트스무디')])
def test_price_turn_order_names_the_menu_and_cites_its_approved_price(menu,first,reply):
    search=fixtures.PlannerTest().search()
    fact=search.snapshot.fact_revisions[0].model_copy(update={
        'predicate':'금액','subject':menu,'quantity':None,'value_text':'3,000원',
        'assertion':'금액=3,000원','original_assertion':'금액=3,000원'})
    card=search.snapshot.cards[0].model_copy(update={'title':menu})
    snapshot=search.snapshot.model_copy(update={'cards':(card,),'fact_revisions':(fact,)})
    snapshot=snapshot.model_copy(update={'snapshot_hash':snapshot_digest(snapshot)})
    search=replace(search,snapshot=snapshot)
    offer=decide(search,store_id=1,question=first)
    assert offer.plan.action=='CLARIFY'
    slots={**offer.confirmed_slots,offer.plan.clarification_slot:reply}
    result=decide(search,store_id=1,question=f'{first} {reply}',confirmed_slots=slots,
                  context_id=uuid4(),context_verified=True,clarify_turns=1)
    answer=render(result.plan,snapshot,store_id=1,request_id='two-turn-price',resolved=result.resolved)
    assert answer.action=='ANSWER' and menu in answer.message and '3,000원' in answer.message
    assert [c.fact_revision_id for c in answer.citations]==[fact.fact_revision_id]

    # Receipt 56 had a price predicate on a rendered identity line with no price.
    wrong=fact.model_copy(update={'assertion':f'구분=커피ICE ; 제품명={menu}'})
    snapshot=snapshot.model_copy(update={'fact_revisions':(wrong,)})
    snapshot=snapshot.model_copy(update={'snapshot_hash':snapshot_digest(snapshot)})
    invalid=decide(replace(search,snapshot=snapshot),store_id=1,question=f'{first} {reply}',
                   confirmed_slots=slots,context_id=uuid4(),context_verified=True,clarify_turns=1)
    assert invalid.plan.action=='ESCALATE'


def test_model_evidence_keeps_revisions_variants_and_constraints():
    from copy import deepcopy
    from app.learn.general_semantics import model_evidence
    from app.learn.semantic_proposals import proposal_input
    payload=proposal_input(unitless_search(),store_id=1,question='라테 원문')
    fact=payload['candidates'][0]['facts'][0]
    fact.update(conditions=['HOT만'],exceptions=['마감 제외'],requires=['2'])
    original=deepcopy(payload)
    wire=model_evidence(payload)
    visible=wire['candidates'][0]['facts'][0]
    assert payload==original and wire['input_hash']==payload['input_hash']
    for key in ('fact_revision_id','assertion','variant','quantity','conditions','exceptions','requires'):
        assert visible[key]==fact[key]
    assert visible['provenance'][0]['source_id']==fact['provenance'][0]['source_id']
    assert 'source_content_hash' not in visible['provenance'][0]
    fact['original_assertion']='다르게 적힌 원문'
    assert model_evidence(payload)['candidates'][0]['facts'][0]['original_assertion']==fact['original_assertion']


def test_dense_evidence_keeps_every_row_and_constraint_with_one_column_header():
    from copy import deepcopy
    from app.learn.general_semantics import model_evidence
    from app.learn.semantic_proposals import proposal_input
    p=proposal_input(unitless_search(),store_id=1,question='오픈 준비')
    f=p['candidates'][0]['facts'][0]
    f.update(conditions=['영업 전'],exceptions=['휴무일 제외'],requires=['2'])
    one=model_evidence(p)['candidates'][0]['facts'][0]
    p['candidates'][0]['facts']=[dict(deepcopy(f),fact_revision_id=str(i)) for i in range(1,51)]
    dense=model_evidence(p)
    c=dense['candidates'][0]
    rows=[{**c['fact_defaults'],**dict(zip(c['fact_columns'],r,strict=True))} for r in c['fact_rows']]
    assert rows==[dict(one,fact_revision_id=str(i)) for i in range(1,51)]


@pytest.mark.asyncio
async def test_prompt_limit_is_reported_before_sdk_and_not_as_an_invalid_model_proposal(tmp_path,monkeypatch):
    from app.errors import ApiError
    from app.learn.general_provider import generate
    from app.learn.general_semantics import Release
    search,_,kw,raw=setup(tmp_path)
    kw['context']=kw['context'].model_copy(update={'cost_purpose':'PRODUCT','evaluation_run_id':None})
    release=Release.model_validate(dict(raw,max_prompt_bytes=500))
    monkeypatch.setattr('app.learn.general_semantics.load_release',lambda *_:release)
    monkeypatch.setattr('app.learn.general_provider.get_settings',lambda:type('Settings',(),{'gemini_model':release.model})())
    client=AsyncMock()
    monkeypatch.setattr('google.genai.Client',client)
    with pytest.raises(ApiError) as caught:
        await general_decision(search,**kw,provider=generate)
    assert caught.value.code=='GENERAL_INPUT_LIMIT'
    assert caught.value.details==dict(phase='proposal_provider',error_type='InputByteLimitExceeded')
    client.assert_not_called()
