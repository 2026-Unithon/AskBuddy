"""Case-action provenance and actual-output replay; no paid model calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.contracts.hashing import digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.errors import ApiError
from app.learn.general_semantics import GeneralProposal, general_decision
from app.learn.general_verification import Verification
from app.learn.general_wire import response_schema
from app.learn.grounded_conclusions import CaseActionReview, GroundedConclusion, missing_case_actions
from app.learn.planner import decide
from app.reg.hybrid import Candidate, SearchResult, normalize_query
from scripts.run_r_operations_http import collect, offered_choice, validate_choice_scripts
from tests.test_r_general_semantics import setup

FROZEN=json.loads((Path(__file__).parent/'fixtures/r_case_actions_live_20261008.json').read_text('utf-8'))


def review():
    return dict(scope='CASE_ACTIONS',rationale='각 사건의 상태에 따른 다음 조치를 요청함',cases=[
        dict(subject=dict(turn_id=0,quote='A'),state=dict(turn_id=0,quote='결제 상태 미확인'),
             conclusion_id=0,next_action_quote='원결제 상태를 조회'),
        dict(subject=dict(turn_id=0,quote='B'),state=dict(turn_id=0,quote='환불 승인 대기'),
             conclusion_id=1,next_action_quote='점주 승인 확인')])


def conclusions():
    raw=FROZEN['proposal']['conclusions'][0]
    return tuple(GroundedConclusion.model_validate(dict(raw,statement=text)) for text in (
        'A는 결제 상태 미확인이므로 원결제 상태를 조회합니다.',
        'B는 환불 승인 대기이므로 점주 승인 확인을 다음 조치로 기록합니다.'))


def check(value,cs=None):
    return missing_case_actions(CaseActionReview.model_validate(value),cs or conclusions(),
        question=FROZEN['proposal_request']['input']['question'],user_turns=())


def test_each_named_state_and_action_is_bound_to_its_own_conclusion():
    assert check(review())==[]
    value=review();value['cases'][1].update(conclusion_id=None,next_action_quote='')
    assert check(value)==[1]
    value=review();value['cases'][0]['conclusion_id']=1
    assert check(value)==[0]  # A cannot borrow B's conclusion/state/action.


@pytest.mark.parametrize('change',['invented_subject','invented_state','wrong_turn','duplicate','empty_cases','wrong_index','orphan_quote','nonapplicable_cases','blank_reason','unbound_evidence'])
def test_invalid_case_audit_cannot_pass(change):
    value=review();cs=conclusions()
    if change=='invented_subject':value['cases'][0]['subject']['quote']='C'
    if change=='invented_state':value['cases'][0]['state']['quote']='결제 완료'
    if change=='wrong_turn':value['cases'][0]['state']['turn_id']=9
    if change=='duplicate':value['cases'].append(deepcopy(value['cases'][0]))
    if change=='empty_cases':value['cases']=[]
    if change=='wrong_index':value['cases'][0]['conclusion_id']=7
    if change=='orphan_quote':value['cases'][0]['conclusion_id']=None
    if change=='nonapplicable_cases':value['scope']='NOT_APPLICABLE'
    if change=='blank_reason':value['rationale']=' '
    if change=='unbound_evidence':
        cs=(cs[0].model_copy(update={'user_evidence':()}),cs[1])
    with pytest.raises(ValueError):check(value,cs)


def test_missing_or_generic_application_does_not_become_complete_by_citing_policy():
    old=tuple(GroundedConclusion.model_validate(c) for c in FROZEN['proposal']['conclusions'])
    value=review()
    for c in value['cases']:
        c.update(conclusion_id=0,next_action_quote='다음 조치')
    assert check(value,old)==[0,1]  # Common fields omit the individual names/states.
    with pytest.raises(ValueError):missing_case_actions(None,old,question='q',user_turns=())
    assert check(dict(scope='NOT_APPLICABLE',rationale='일반 양식 질문',cases=[]))==[]


def test_state_correction_uses_current_evidence_and_topic_change_can_be_nonapplicable():
    value=review();value['cases']=value['cases'][:1]
    value['cases'][0]['state']=dict(turn_id=1,quote='결제 완료')
    c=GroundedConclusion.model_validate(dict(conclusions()[0].model_dump(),statement='A는 결제 완료이므로 기록을 인계합니다.',
        user_evidence=[{'turn_id':0,'quote':'A는 결제 상태 미확인'}, {'turn_id':1,'quote':'A는 결제 완료로 정정해'}]))
    value['cases'][0]['next_action_quote']='기록을 인계'
    assert missing_case_actions(CaseActionReview.model_validate(value),(c,),
        question='A는 결제 완료로 정정해',user_turns=('A는 결제 상태 미확인',))==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('new_review',[False,True])
async def test_actual_generic_handoff_no_longer_passes_without_case_application(tmp_path,new_review):
    _,_,kw,release=setup(tmp_path)
    payload=FROZEN['proposal_request']['input']
    snap=PublishedKnowledgeSnapshot.model_validate(FROZEN['snapshot'])
    candidates=tuple(Candidate(c['card_id'],c['card_version_id'],c['block']['block_id'],None,None,0) for c in payload['candidates'])
    search=SearchResult(snap,1,candidates,normalize_query(payload['question']))
    release.update(snapshot_hash=snap.snapshot_hash,response_style='grounded_conclusion')
    kw['settings'].r_general_semantics_path.write_text(json.dumps(release),encoding='utf-8')
    kw['settings'].r_general_semantics_hash=digest(release)
    kw.update(question=payload['question'],user_turns=tuple(payload['user_turns']),confirmed_slots={},context_verified=True,
        baseline=decide(search,store_id=1,question=payload['question']))
    async def provider(prompt,*,schema,**unused):
        if schema is GeneralProposal:
            raw=deepcopy(FROZEN['proposal'])
            if new_review:
                raw['case_requirements']=dict(scope='CASE_ACTIONS',rationale='Synthetic new contract question scope',cases=[
                    dict(subject=c['subject'],state=c['state']) for c in review()['cases']])
            return raw
        request=json.loads(prompt.rsplit('\n',1)[1])
        result=deepcopy(FROZEN['verification']);result['request_hash']=request['request_hash']
        if new_review:
            # Synthetic new audit of unchanged actual output, not a new Gemini result.
            # 새 계약의 합성 검증 입력이며 과거 실제 출력은 변경하지 않는다.
            for row in result['rule_coverage']:
                n=row.pop('conclusion_id');row.pop('conclusion_quote')
                row['conclusion_unit_id']=None if n is None else f'c{n}s0'
            result['situation_review']=[dict(conclusion_unit_id=u['unit_id'],status='NO_CASE_FACTS',
                user_evidence=[],rationale='Synthetic structural fixture') for u in request['conclusion_units']]
            value=review()
            for item in value['cases']:item.update(conclusion_id=None,next_action_quote='')
            result['case_action_review']=value
        return result
    with pytest.raises(ApiError) as error:await general_decision(search,provider=provider,**kw)
    assert error.value.code==('GENERAL_VERIFICATION_REJECTED' if new_review else 'GENERAL_INVALID_PROPOSAL'),repr(error.value.__cause__)


def test_provider_wire_requires_case_inspection_and_keeps_server_bounds():
    wire=response_schema(Verification)
    assert 'case_action_review' in wire['required']
    assert {'conclusion_id','next_action_quote'}<=set(wire['$defs']['CaseAction']['required'])
    assert 'maxItems' not in wire['$defs']['CaseActionReview']['properties']['cases']
    value=review();value['cases']*=6
    with pytest.raises(ValueError):CaseActionReview.model_validate(value)


def test_actual_descriptive_choice_matches_only_predeclared_unique_alias():
    row=FROZEN['clarification'];label='A는 결제 상태 미확인'
    assert offered_choice(row,'A') is None  # Original plan still stops.
    selected=offered_choice(row,'A',aliases=[label])
    assert selected==dict(option=label,context_id=row['response']['context_id'],context_revision=row['context_revision'])
    assert offered_choice(row,'A',aliases=['B는 환불 승인 대기',label]) is None
    changed=deepcopy(row);changed['response']['allowed_options']=['A',label]
    assert offered_choice(changed,'A',aliases=[label]) is None
    assert offered_choice(row,'A',aliases=['A는 결제 상태']) is None
    changed=deepcopy(row);changed['context_revision']=0
    assert offered_choice(changed,'A',aliases=[label]) is None


@pytest.mark.parametrize('aliases',[None,'A',[''],['A'],['x','x'],[1],['x']*11])
def test_invalid_frozen_choice_script_rejected_before_run(aliases):
    challenge={'cases':[{'turns':[dict(select_option='A',select_option_aliases=aliases)]}]}
    with pytest.raises(ValueError):validate_choice_scripts(challenge)


@pytest.mark.asyncio
@pytest.mark.parametrize('ambiguous',[False,True])
async def test_collector_sends_returned_choice_with_real_revision_or_stops(tmp_path,ambiguous):
    import httpx
    from app.learn.v2_router import ChatRequest
    context_id='2fc25a0f-b41d-4017-ab52-5a84436b93d7'
    state={};sent=[];label='A는 결제 상태 미확인'
    class Client:
        async def post(self,path,headers,json):
            if path.endswith('/sessions'):
                return httpx.Response(200,json={'session_id':'21'},request=httpx.Request('POST','http://test'))
            ChatRequest.model_validate(json)  # Exercise the actual endpoint DTO.
            sent.append(json)
            body=(dict(action='CLARIFY',clarification_slot='case',context_id=context_id,
                allowed_options=[label,'A' if ambiguous else 'B는 환불 승인 대기']) if len(sent)==1
                else dict(action='ANSWER',message='합성 완료',citations=[]))
            state.update(question=json['question'],response=body)
            return httpx.Response(200,json=body,headers={'x-answer-receipt-id':str(len(sent)),'x-context-revision':'9'})
        async def get(self,*args,**kwargs):
            return httpx.Response(200,json={},request=httpx.Request('GET','http://test'))
    class DB:
        async def fetchrow(self,*args):
            assert args[-2]==1
            return dict(response=state['response'],original_question=state['question'],execution_metadata={})
    case=dict(case_id='C01',title='합성',kind='dialogue',tier='hard',turns=[
        dict(question='그 건은?',expected_action='CLARIFY',required_fact_ids=[]),
        dict(question='A',select_option='A',select_option_aliases=[label],expected_action='ANSWER',required_fact_ids=[])])
    _,rows,_=await collect(Client(),DB(),dict(store_id=1,mapping=[]),{},dict(cases=[case]),tmp_path,
        controls=[dict(passed=True)])
    if ambiguous:
        assert len(sent)==1 and rows[0]['stop_reason']=='REQUIRED_CHOICE_NOT_OFFERED'
    else:
        assert len(sent)==2 and sent[1]==dict(session_id='21',request_id='ops-C01-2',question=label,
            option=label,context_id=context_id,context_revision=9)
        assert rows[0]['turns'][1]['choice_resolution']['returned_option']==label
        old_payload=dict(sent[1],question='A')
        with pytest.raises(ValueError,match='selected option only'):ChatRequest.model_validate(old_payload)
