"""Real failed outputs remain negative fixtures; hand-corrected copies test wiring only."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.contracts.answer import AnswerPlan
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.general_semantics import GeneralProposal,Release,general_decision,validate_interpretation
from app.learn.general_wire import parse_proposal,response_schema
from app.learn.planner import decide
from app.learn.semantic_proposals import proposal_input
from app.reg.hybrid import Candidate,SearchResult,normalize_query
from tests.test_r_general_semantics import setup,provider_for

FROZEN=json.loads((Path(__file__).parent/'fixtures/r_general_live_20261006.json').read_text('utf-8'))


def live_case(case_id,turn_number=1):
    case=next(c for c in FROZEN['cases'] if (c['case_id'],c['turn_number'])==(case_id,turn_number))
    snap=PublishedKnowledgeSnapshot.model_validate(FROZEN['snapshot'])
    candidates=tuple(Candidate(i,snap.card(i).card_version_id,'raw1',None,None,0) for i in case['candidate_card_ids'])
    search=SearchResult(snap,1,candidates,normalize_query(case['question']))
    payload=proposal_input(search,store_id=1,question=case['question'],user_turns=tuple(case['previous_user_turns']))
    assert payload['input_hash']==case['input_hash']
    baseline=decide(search,store_id=1,question=case['question'])
    return case,search,payload,baseline


@pytest.mark.parametrize('case_id,turn',[(c['case_id'],c['turn_number']) for c in FROZEN['cases']])
def test_recorded_bad_outputs_are_not_silently_repaired_into_answers(case_id,turn):
    case,search,payload,baseline=live_case(case_id,turn)
    if case['finish_reason']=='MAX_TOKENS':
        with pytest.raises(json.JSONDecodeError):json.loads(case['raw_text'])
        return
    try:
        result=validate_interpretation(search,payload=payload,proposal=case['output'],baseline=baseline,confirmed_slots={})
    except ValueError:
        return
    assert result is baseline and result.plan.action!='ANSWER'


def test_clarification_missing_context_id_is_allocated_by_server_without_weakening_public_contract():
    case,search,payload,baseline=live_case('OD06',3)
    raw=deepcopy(case['output']);raw['unresolved']=[]  # Authored protocol-only control, not corrected model accuracy.
    runtime_id=uuid4()
    with pytest.raises(ValueError):AnswerPlan.model_validate(raw['plan'])
    result=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,
        context_id=runtime_id,confirmed_slots={})
    assert result.plan.action=='CLARIFY' and result.plan.context_id==runtime_id
    assert raw['plan']['context_id'] is None  # No mutation of recorded provider data.
    raw['plan']['context_id']=str(uuid4())
    with pytest.raises(ValueError,match='cannot issue context'):parse_proposal(raw)


def test_clarification_still_rejects_selected_answer_blocks_and_invented_options():
    case,search,payload,baseline=live_case('OD03',3)
    with pytest.raises(ValueError):parse_proposal(case['output'])
    raw=deepcopy(case['output']);raw['plan']['selected_blocks']=[]
    with pytest.raises(ValueError,match='incomplete clarification'):
        validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})


def contract_corrected_copy(case):
    raw=deepcopy(case['output'])
    for part in raw.get('parts') or [raw]:
        interp=part['interpretation']
        interp.update(predicate='approved_procedure',variants=[])
        part['slots']=[dict(slot=k,value=v,question_quote=case['question'])
            for k,v in [('entity',interp['entity_id']),('predicate','approved_procedure')]]
    return raw


def test_current_question_planner_guess_does_not_block_different_relevant_entity():
    case,search,payload,baseline=live_case('OD01')
    assert baseline.confirmed_slots=={'entity':'마감'}
    raw=contract_corrected_copy(case)
    decision=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})
    assert decision.plan.action=='ANSWER' and decision.confirmed_slots=={}
    # An actual user selection remains binding; the fix is provenance, not a bypass.
    with pytest.raises(ValueError,match='entity contradicts context'):
        validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={'entity':'마감'})


def test_multiple_raw_entities_keep_separate_parts_references_and_empty_variants():
    case,search,payload,baseline=live_case('O02')
    raw=contract_corrected_copy(case)
    decision=validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})
    assert {p.resolved.entity_id for p in decision.resolved.parts}=={'2','3'}
    assert all(p.resolved.variants==() for p in decision.resolved.parts)
    from app.learn.approved_renderer import render
    rendered=render(decision.plan,search.snapshot,store_id=1,request_id='protocol-control',resolved=decision.resolved)
    assert {c.card_id for c in rendered.citations}=={'2','3'}
    assert '열쇠 소지만으로' in rendered.message and '현장 도착' in rendered.message
    raw['parts'][1]['slots'][0]['question_quote']='not present in any user turn'
    with pytest.raises(ValueError):validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline,confirmed_slots={})


@pytest.mark.asyncio
async def test_both_model_stages_receive_only_accepted_user_slots(tmp_path):
    search,raw,kw,_=setup(tmp_path)
    kw['baseline']=replace(kw['baseline'],confirmed_slots={'entity':'planner guess'})
    kw['confirmed_slots']={}
    provider=provider_for(search,raw)
    result,_=await general_decision(search,provider=provider,**kw)
    assert result.confirmed_slots=={}
    for call in provider.call_args_list:
        assert json.loads(call.args[0].rsplit('\n',1)[-1])['confirmed_slots']=={}


def test_model_schema_excludes_server_ids_and_policy_actions():
    schema=response_schema(GeneralProposal)
    plan=schema['$defs']['AnswerPlan']
    assert 'context_id' not in plan['properties']
    assert plan['properties']['action']['enum']==['ANSWER','CLARIFY','ESCALATE']
    # The model schema does not mutate the public API contract.
    assert 'context_id' in AnswerPlan.model_json_schema()['properties']


@pytest.mark.asyncio
@pytest.mark.parametrize('finish',['STOP','MAX_TOKENS','SAFETY',None])
async def test_provider_structured_output_thinking_and_incomplete_usage(tmp_path,monkeypatch,finish):
    from app.learn.general_provider import generate,IncompleteModelOutput
    from app.team.evaluation_budget import EvaluationBudget,evaluation_budget_scope
    from tests.test_r_evaluation_budget import policy
    from tests.test_r_semantic_proposals import kwargs
    _,_,_,release=setup(tmp_path);release=Release.model_validate(release)
    budget=EvaluationBudget(None,policy());budget.reserve=AsyncMock(return_value='one');budget.finish=AsyncMock()
    # Even syntactically complete JSON must be rejected when the provider says truncated.
    sdk=NS(aio=NS(models=NS(count_tokens=AsyncMock(return_value=NS(total_tokens=10)),
        generate_content=AsyncMock(return_value=NS(text='{}',candidates=[NS(finish_reason=finish)],
            usage_metadata=NS(prompt_token_count=10,candidates_token_count=3,thoughts_token_count=2)))),aclose=AsyncMock()))
    monkeypatch.setattr('google.genai.Client',lambda **kw:sdk)
    monkeypatch.setattr('app.learn.general_provider.get_settings',lambda:NS(gemini_model='synthetic',gemini_api_key='synthetic'))
    sink=NS(start=AsyncMock(return_value=1),finalize=AsyncMock())
    with evaluation_budget_scope(budget):
        if finish=='STOP':assert await generate('q',schema=GeneralProposal,release=release,context=kwargs()['context'],sink=sink)=={}
        else:
            with pytest.raises(IncompleteModelOutput):await generate('q',schema=GeneralProposal,release=release,context=kwargs()['context'],sink=sink)
    config=sdk.aio.models.generate_content.call_args.kwargs['config']
    assert config.response_json_schema==response_schema(GeneralProposal,conclusions_enabled=False)
    assert config.thinking_config.thinking_level=='LOW' and config.max_output_tokens==50
    assert config.automatic_function_calling.disable is True
    budget.finish.assert_awaited_once_with('one',input_tokens=10,output_tokens=5)
    assert sdk.aio.models.generate_content.await_count==1


@pytest.mark.asyncio
@pytest.mark.parametrize('style',['approved_original','grounded_conclusion'])
async def test_real_sdk_serializes_native_json_schema_and_low_thinking(tmp_path,monkeypatch,style):
    import httpx
    from google import genai
    from google.genai import types
    from app.learn.general_provider import generate
    from tests.test_r_semantic_proposals import kwargs
    _,_,_,release=setup(tmp_path);release=Release.model_validate(dict(release,response_style=style))
    observed=[]
    def respond(request):
        body=json.loads(request.content);observed.append((request.url.path,body))
        if request.url.path.endswith(':countTokens'):
            return httpx.Response(200,json={'totalTokens':10})
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'{}'}],'role':'model'},'finishReason':'STOP'}],
            'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':3,'thoughtsTokenCount':2}})
    # generate 는 끝나면 클라이언트를 닫는다. 호출마다 새로 만든다.
    # 원래 클래스를 미리 붙잡는다 — 패치한 이름을 부르면 자기 자신을 다시 부른다
    real_client=genai.Client
    def make_client(**kw):
        return real_client(api_key='synthetic',http_options=types.HttpOptions(
            async_client_args={'transport':httpx.MockTransport(respond)},
            retry_options=types.HttpRetryOptions(attempts=1)))
    monkeypatch.setattr('google.genai.Client',make_client)
    monkeypatch.setattr('app.learn.general_provider.get_settings',lambda:NS(gemini_model='synthetic',gemini_api_key='synthetic'))
    ctx=kwargs()['context'].model_copy(update={'cost_purpose':'DEVELOPMENT','evaluation_run_id':None})
    result=await generate('q',schema=GeneralProposal,release=release,context=ctx,sink=NS(start=AsyncMock(return_value=1),finalize=AsyncMock()))
    # 한도가 넉넉하면 countTokens 왕복을 생략한다(바이트 수가 토큰 수의 상한이다).
    # 생성 요청 하나만 나가야 한다.
    assert result=={} and len(observed)==1 and observed[0][0].endswith(':generateContent')
    wire=observed[-1][1]['generationConfig']
    assert wire['responseJsonSchema']==response_schema(GeneralProposal,conclusions_enabled=style=='grounded_conclusion')
    # This SDK sends the protobuf field name inside ThinkingConfig; both the
    # original snake_case and lowerCamelCase forms are accepted by ProtoJSON.
    assert wire['thinkingConfig'].get('thinking_level',wire['thinkingConfig'].get('thinkingLevel'))=='LOW'

    # 한도에 가까우면 실제 SDK 가 countTokens 를 먼저 보낸다 — 요청 모양까지 확인한다
    tight=Release.model_validate(dict(release.model_dump(mode='json'),max_input_tokens=100))
    observed.clear()
    await generate('q',schema=GeneralProposal,release=tight,context=ctx,
                   sink=NS(start=AsyncMock(return_value=1),finalize=AsyncMock()))
    assert [path.rsplit(':',1)[-1] for path,_ in observed]==['countTokens','generateContent']


@pytest.mark.parametrize('metadata,expected',[
    ({'prompt_token_count':3628,'candidates_token_count':5,'total_token_count':3633},(3628,5,0)),
    ({'prompt_token_count':3628,'candidates_token_count':5,'total_token_count':3700},(3628,5,None)),
    ({'prompt_token_count':10,'candidates_token_count':3},(10,3,None)),
    ({'prompt_token_count':10,'candidates_token_count':3,'thoughts_token_count':2},(10,3,2)),
    ({'prompt_token_count':10,'candidates_token_count':3,'total_token_count':13,'tool_use_prompt_token_count':2},(10,3,None)),
    ({'prompt_token_count':10,'candidates_token_count':3,'thoughts_token_count':-1,'total_token_count':13},(10,3,None)),
    (None,(None,None,None)),
])
def test_omitted_thoughts_require_reconciled_provider_total(metadata,expected):
    from app.learn.general_provider import usage_tokens
    assert usage_tokens(metadata)==expected


def test_decoder_bounds_removed_but_server_collection_bounds_stay_strict():
    def walk(value):
        if isinstance(value,dict):
            assert 'maxItems' not in value
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(response_schema(GeneralProposal))
    from app.learn.general_semantics import Verification
    walk(response_schema(Verification))
    assert GeneralProposal.model_json_schema()['properties']['parts']['maxItems']==8
    assert GeneralProposal.model_json_schema()['properties']['slots']['maxItems']==20
    case,_,_,_=live_case('O02')
    raw=contract_corrected_copy(case)
    raw['parts']=raw['parts']*5
    with pytest.raises(ValueError):parse_proposal(raw)
    with pytest.raises(ValueError):Verification.model_validate(dict(request_hash='sha256:'+'0'*64,
        supported=True,unresolved=[],checked_fact_ids=[],checked_raw_blocks=[['1','1','raw1','1','EXTRA']]))


def test_actual_transport_outputs_cannot_invent_quotes_or_raw_calculations():
    fixture=json.loads((Path(__file__).parent/'fixtures/r_gemini_transport_20261006.json').read_text('utf-8'))
    _,search,payload,baseline=live_case('O01')
    with pytest.raises(ValueError,match='slot quote outside user input'):
        validate_interpretation(search,payload=payload,proposal=fixture['missing_user_quote'],baseline=baseline,confirmed_slots={})
    with pytest.raises(ValueError,match='binary operation requires two approved quantities'):
        parse_proposal(fixture['invented_raw_calculation'])
