import json
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from app.contracts.hashing import digest
from app.contracts.validate import validate_answer_references
from app.errors import ApiError
from app.learn.general_semantics import GeneralProposal, general_decision, source_hash, validate_interpretation
from app.learn.semantic_proposals import proposal_input
from tests.test_r_reviewed_semantics import fixture
from tests.test_r_semantic_proposals import kwargs


def setup(tmp_path):
    search,q,baseline,catalog=fixture()
    entry=catalog.entries[0]
    interp=entry.interpretation
    raw=dict(entry.proposal.model_dump(mode='json'),interpretation=dict(entity_id=interp.entity_id,
        predicate=interp.predicate,variants=interp.variants,target_fact_ids=interp.target_fact_ids),
        slots=[dict(slot='entity',value=interp.entity_id,question_quote=q),dict(slot='predicate',value=interp.predicate,question_quote=q)])
    release=dict(store_id='1',snapshot_hash=search.snapshot.snapshot_hash,source_hash=source_hash(),model='synthetic',
        acceptance_reference='synthetic test only',approved_by='synthetic reviewer',
        valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),max_input_tokens=100000,max_output_tokens=1000,max_prompt_bytes=200000)
    path=tmp_path/'release.json';path.write_text(json.dumps(release),encoding='utf-8')
    settings=NS(r_general_semantics_enabled=True,r_general_semantics_path=path,r_general_semantics_hash=digest(release),gemini_model='synthetic')
    values=dict(settings=settings,store_id=1,question=q,user_turns=(),baseline=baseline,context=kwargs()['context'],sink=object(),timeout=2)
    return search,raw,values,release


def provider_for(search,raw,*,reject=False):
    async def call(prompt,*,schema,**kwargs):
        if schema is GeneralProposal:return raw
        request=json.loads(prompt.split('\n',1)[1])
        refs=validate_answer_references(GeneralProposal.model_validate(raw).plan,search.snapshot,store_id='1')
        return dict(request_hash=request['request_hash'],supported=not reject,unresolved=[],checked_fact_ids=refs.fact_ids,checked_raw_blocks=refs.raw_blocks)
    return AsyncMock(side_effect=call)


@pytest.mark.asyncio
async def test_unregistered_free_question_reaches_server_decision_without_catalog(tmp_path):
    search,raw,kw,_=setup(tmp_path);provider=provider_for(search,raw)
    decision,audit=await general_decision(search,provider=provider,**kw)
    assert decision.plan.action=='ANSWER' and decision.confirmed_slots==kw['baseline'].confirmed_slots
    assert decision.semantic_context is None and audit['status']=='STRUCTURE_AND_MODEL_CHECKED'
    assert provider.await_count==2
    assert provider.call_args_list[0].kwargs['context'].logical_call_id!=provider.call_args_list[1].kwargs['context'].logical_call_id


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['off','context','baseline'])
async def test_ineligible_path_never_calls_provider(tmp_path,change):
    search,raw,kw,_=setup(tmp_path)
    if change=='off':kw['settings'].r_general_semantics_enabled=False
    if change=='context':kw['user_turns']=('unverified turn',)
    if change=='baseline':kw['baseline']=replace(kw['baseline'],plan=GeneralProposal.model_validate(raw).plan)
    provider=AsyncMock()
    assert await general_decision(search,provider=provider,**kw)==(kw['baseline'],None)
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['pin','expired','store','source','model'])
async def test_release_gate_blocks_before_provider(tmp_path,change):
    search,raw,kw,release=setup(tmp_path)
    if change=='pin':release['approved_by']='changed'
    if change=='expired':release['valid_until']='2020-01-01T00:00:00Z'
    if change=='store':release['store_id']='2'
    if change=='source':release['source_hash']='sha256:'+'0'*64
    if change=='model':release['model']='wrong-model'
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release),encoding='utf-8')
    if change!='pin':kw['settings'].r_general_semantics_hash=digest(release)
    provider=AsyncMock()
    with pytest.raises(ApiError) as error:await general_decision(search,provider=provider,**kw)
    assert error.value.code=='GENERAL_RELEASE_UNAVAILABLE'
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['quote','candidate','group','context','assessment','raw','policy'])
async def test_invalid_model_interpretation_is_error_not_answer_or_pending(tmp_path,change):
    search,raw,kw,_=setup(tmp_path)
    if change=='quote':raw['slots'][0]['question_quote']='not in user text'
    if change=='candidate':search=replace(search,candidates=()) # validate directly below
    if change=='group':raw['equivalent_question_ids']=['1']
    if change=='context':kw['baseline']=replace(kw['baseline'],confirmed_slots={'entity':'another entity'})
    if change=='assessment':raw['assessment']={'approved':True}
    if change=='raw':raw['plan']['selected_blocks'][0]['raw_span_id']='9999'
    if change=='policy':raw['plan']=dict(snapshot_id=search.snapshot.snapshot_id,knowledge_revision=search.snapshot.knowledge_revision,action='SAFE_ROUTE')
    payload=proposal_input(search,store_id=1,question=kw['question'])
    with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,baseline=kw['baseline'])


@pytest.mark.asyncio
async def test_rejection_uncertainty_timeout_and_bad_verifier_are_distinct(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    decision,audit=await general_decision(search,provider=provider_for(search,raw,reject=True),**kw)
    assert decision is kw['baseline'] and audit['status']=='VERIFIER_REJECTED'
    raw['unresolved']=['unknown condition']
    provider=provider_for(search,raw)
    decision,audit=await general_decision(search,provider=provider,**kw)
    assert decision is kw['baseline'] and provider.await_count==1
    raw['unresolved']=[]
    with pytest.raises(ApiError) as error:await general_decision(search,provider=AsyncMock(side_effect=TimeoutError()),**kw)
    assert error.value.code=='GENERAL_DEADLINE'
    provider=AsyncMock(side_effect=[raw,dict(request_hash='sha256:'+'0'*64,supported=True,unresolved=[],checked_fact_ids=[],checked_raw_blocks=[])])
    with pytest.raises(ApiError) as error:await general_decision(search,provider=provider,**kw)
    assert error.value.code=='GENERAL_INVALID_PROPOSAL'
    from app.usage.repository import UsageWriteError
    with pytest.raises(ApiError) as error:
        await general_decision(search,provider=AsyncMock(side_effect=UsageWriteError('synthetic')),**kw)
    assert error.value.code=='USAGE_UNAVAILABLE'


@pytest.mark.parametrize('missing',['condition','exception','quote',None])
def test_nested_numeric_conditions_require_all_obligations(missing):
    from tests.test_r_planner import PlannerTest
    from app.contracts.hashing import snapshot_digest
    from app.learn.planner import decide
    search=PlannerTest().search(conditions=('주문 2잔 이상이고 주말인 경우',))
    fact=search.snapshot.fact_revisions[0].model_copy(update={'exceptions':('단, 5잔 이상이면 적용 제외',)})
    snap=search.snapshot.model_copy(update={'fact_revisions':(fact,)})
    search=replace(search,snapshot=snap.model_copy(update={'snapshot_hash':snapshot_digest(snap)}))
    q='주말 두 잔 주문, 다섯 잔 미만일 때 따뜻한 음료의 양을 알려줘'
    baseline=decide(search,store_id=1,question=q)
    payload=proposal_input(search,store_id=1,question=q)
    raw=dict(input_hash=payload['input_hash'],snapshot_hash=search.snapshot.snapshot_hash,
        plan=dict(snapshot_id='1',knowledge_revision='1',action='ANSWER',selected_blocks=[dict(card_id='1',card_version_id='1',block_id='b',fact_revision_ids=['1'])]),
        interpretation=dict(entity_id='1',predicate='milk_amount',variants=[['HOT',None]],target_fact_ids=['1']),
        slots=[dict(slot=k,value=v,question_quote=q) for k,v in [('entity','1'),('predicate','milk_amount'),('temperature','HOT')]],
        obligations=[dict(fact_revision_id='1',kind=k,statement=s,question_quote=q) for k,s in [('condition',fact.conditions[0]),('exception',fact.exceptions[0])]])
    if missing in ('condition','exception'):raw['obligations']=[o for o in raw['obligations'] if o['kind']!=missing]
    if missing=='quote':raw['obligations'][0]['question_quote']='평일'
    if missing:
        with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)
    else:
        result=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)
        assert result.resolved.assessment.facts[0].exceptions==fact.exceptions


def test_clarification_uses_snapshot_options_and_runtime_context():
    from tests.test_r_planner import PlannerTest
    from app.contracts.hashing import snapshot_digest
    from app.learn.planner import decide
    from uuid import uuid4
    search=PlannerTest().search()
    f=search.snapshot.fact_revisions[0]
    second=f.model_copy(update={'fact_revision_id':'2','fact_id':'2','variant':f.variant.model_copy(update={'temperature':'ICE'})})
    card=search.snapshot.cards[0]
    card=card.model_copy(update={'blocks':(card.blocks[0].model_copy(update={'fact_revision_ids':('1','2')}),)})
    snap=search.snapshot.model_copy(update={'cards':(card,),'fact_revisions':(f,second)})
    search=replace(search,snapshot=snap.model_copy(update={'snapshot_hash':snapshot_digest(snap)}))
    q='그 음료에 들어가는 액체가 궁금해요';payload=proposal_input(search,store_id=1,question=q)
    baseline=decide(search,store_id=1,question=q);runtime=uuid4();model_id=uuid4()
    raw=dict(input_hash=payload['input_hash'],snapshot_hash=search.snapshot.snapshot_hash,
        plan=dict(snapshot_id='1',knowledge_revision='1',action='CLARIFY',clarification_slot='temperature',allowed_options=['HOT','ICE'],context_id=str(model_id)),
        interpretation=dict(entity_id='1',predicate='milk_amount',variants=[],target_fact_ids=[]),
        slots=[dict(slot=k,value=v,question_quote=q) for k,v in [('entity','1'),('predicate','milk_amount')]])
    result=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,context_id=runtime)
    assert result.plan.context_id==runtime and result.plan.context_id!=model_id
    assert validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,clarify_turns=2) is baseline
    raw['plan']['allowed_options']=['HOT','INVENTED']
    with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)


def test_null_variant_cannot_implicitly_become_not_applicable():
    from tests.test_r_planner import PlannerTest
    from app.learn.planner import decide
    search=PlannerTest().search(temperature=None);q='이 음료에 들어가는 양을 설명해주세요'
    payload=proposal_input(search,store_id=1,question=q);baseline=decide(search,store_id=1,question=q)
    raw=dict(input_hash=payload['input_hash'],snapshot_hash=search.snapshot.snapshot_hash,
        plan=dict(snapshot_id='1',knowledge_revision='1',action='ANSWER',selected_blocks=[dict(card_id='1',card_version_id='1',block_id='b',fact_revision_ids=['1'])]),
        interpretation=dict(entity_id='1',predicate='milk_amount',variants=[],target_fact_ids=['1']),
        slots=[dict(slot=k,value=v,question_quote=q) for k,v in [('entity','1'),('predicate','milk_amount')]])
    with pytest.raises(ValueError,match='null variant'):validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)


@pytest.mark.asyncio
async def test_provider_requires_eval_budget_and_honors_token_caps(tmp_path,monkeypatch):
    from app.learn.general_provider import generate
    from app.learn.general_semantics import Release
    from app.team.evaluation_budget import evaluation_budget_scope,BudgetDenied
    from tests.test_r_evaluation_budget import policy
    from app.team.evaluation_budget import EvaluationBudget
    _,_,_,release=setup(tmp_path);release=Release.model_validate(release)
    ctx=kwargs()['context'];budget=EvaluationBudget(None,policy())
    budget.reserve=AsyncMock(return_value='reserved');budget.finish=AsyncMock()
    sdk=NS(aio=NS(models=NS(count_tokens=AsyncMock(return_value=NS(total_tokens=10)),
        generate_content=AsyncMock(return_value=NS(text='{}',usage_metadata=NS(prompt_token_count=10,candidates_token_count=3,thoughts_token_count=2)))),aclose=AsyncMock()))
    monkeypatch.setattr('google.genai.Client',lambda **kw:sdk)
    monkeypatch.setattr('app.learn.general_provider.get_settings',lambda:NS(gemini_model='synthetic',gemini_api_key='synthetic'))
    sink=NS(start=AsyncMock(return_value=1),finalize=AsyncMock())
    with pytest.raises(BudgetDenied):await generate('q',schema=GeneralProposal,release=release,context=ctx,sink=sink)
    sdk.aio.models.count_tokens.assert_not_awaited()
    with evaluation_budget_scope(budget):
        await generate('q',schema=GeneralProposal,release=release,context=ctx,sink=sink)
    assert sdk.aio.models.generate_content.call_args.kwargs['config'].max_output_tokens==50
    budget.finish.assert_awaited_once_with('reserved',input_tokens=10,output_tokens=5)
