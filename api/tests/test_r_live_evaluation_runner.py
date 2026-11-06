"""No-network checks of paid-run stopping and reporting denominators."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from scripts.run_r_operations_http import collect
from scripts.run_r_operations_http import offered_choice


def test_followup_uses_only_actual_case_choice_and_revision():
    from copy import deepcopy
    row=dict(http_status=200,response=dict(action='CLARIFY',clarification_slot='case',
        allowed_options=['A','B'],context_id='real-context'),context_revision=7)
    assert offered_choice(row,'A')==dict(option='A',context_id='real-context',context_revision=7)
    assert offered_choice(row,'C') is None
    for key,value in [('action','ANSWER'),('clarification_slot','entity'),('context_id',None)]:
        changed=deepcopy(row);changed['response'][key]=value
        assert offered_choice(changed,'A') is None
    assert offered_choice(dict(row,context_revision=None),'A') is None
    assert offered_choice(None,'A') is None
from scripts.report_r_operations_live_v2 import render,body_hash


def test_stops_after_three_errors_without_dropping_frozen_denominator(tmp_path):
    state={}; requests=[]
    class Client:
        async def post(self,path,headers,json):
            if path.endswith('/sessions'):return httpx.Response(200,json={'session_id':'1'},request=httpx.Request('POST','http://test'))
            requests.append(json['question'])
            if json['request_id'].startswith('ops-control'):
                state.update(question=json['question'],body={'action':'ANSWER','message':'원문'})
                return httpx.Response(200,json=state['body'],headers={'x-answer-receipt-id':'1'})
            return httpx.Response(503,json={'error':{'code':'GENERAL_INVALID_PROPOSAL'}})
        async def get(self,*a,**k):return httpx.Response(200,json={},request=httpx.Request('GET','http://test'))
    class DB:
        async def fetchrow(self,*a):return {'response':state['body'],'original_question':state['question'],'execution_metadata':{}}
    challenge={'cases':[dict(case_id=f'C{i}',title='test',kind='single',tier='hard',turns=[dict(question=f'q{i}',expected_action='ANSWER',required_fact_ids=[])]) for i in range(5)]}
    seed={'store_id':1,'mapping':[]}
    controls,rows,stop=asyncio.run(collect(Client(),DB(),seed,{},challenge,tmp_path,controls=[{'passed':True}],stop_after_errors=3))
    assert controls[0]['passed'] and len(rows)==3 and len(requests)==3
    assert stop=='CONSECUTIVE_API_ERRORS_3' and len(challenge['cases'])==5


def test_unoffered_first_choice_never_counts_empty_scenario_as_success(tmp_path):
    class Client:
        async def post(self,*a,**k):
            return httpx.Response(200,json={'session_id':'1'},request=httpx.Request('POST','http://test'))
        async def get(self,*a,**k):
            return httpx.Response(200,json={},request=httpx.Request('GET','http://test'))
    case=dict(case_id='C',title='test',kind='dialogue',tier='hard',turns=[dict(select_option='A')])
    _,rows,stop=asyncio.run(collect(Client(),None,dict(store_id=1,mapping=[]),{},
        {'cases':[case]},tmp_path,controls=[dict(passed=True)]))
    assert not rows[0]['all_actions_match'] and rows[0]['turns']==[]
    assert rows[0]['stop_reason']=='REQUIRED_CHOICE_NOT_OFFERED'


def test_missing_or_failed_controls_stop_before_requests(tmp_path):
    for controls in ([],[dict(passed=False)]):
        _,rows,stop=asyncio.run(collect(None,None,dict(store_id=1,mapping=[]),{},
            {'cases':[]},tmp_path,controls=controls))
        assert rows==[] and stop=='POSITIVE_CONTROL_FAILED'


def test_report_counts_useful_clarification_as_appropriate_but_not_resolved(tmp_path):
    body={'action':'CLARIFY','message':'대상을 선택해 주세요.'}
    turn=dict(http_status=200,response=body,elapsed_local_ms=100)
    run=dict(rows=[dict(case_id='C1',turns=[dict(turn_number=1,**turn)])],settings={'gemini_model':'test'},
        http_success=1,action_counts={'CLARIFY':1},input_hash='fixture')
    expected=dict(question='대상은?',reference_answer='확정 필요')
    data={
        'run.json':run,
        'frozen-challenge.json':{'cases':[dict(case_id='C1',title='test',turns=[expected,expected])]},
        'diagnostic-analysis.json':dict(generation_calls=1,known_cost_usd='0.01',unknown_cost_calls=0,count_tokens_calls=1,calls=[],turns_with_history=0),
        'evaluation-release.json':{'thinking_level':'low'},
        'evaluation-plan.json':{'max_krw':'10000'},
        'baseline.json':dict(successful_api_responses=0,provider_generation_calls=1,provider_verification_calls=0,known_cost_usd='0.02',latency_p50_ms=200,latency_p95_ms=200),
    }
    for name,value in data.items():(tmp_path/name).write_text(json.dumps(value),encoding='utf-8')
    import hashlib
    review=dict(run_sha256=hashlib.sha256((tmp_path/'run.json').read_bytes()).hexdigest(),judgments=[
        dict(case_id='C1',turn_number=1,response_sha256=body_hash(body),label='USEFUL_CLARIFICATION',reason='필수 대상 누락',reviewer='test')])
    (tmp_path/'review.json').write_text(json.dumps(review),encoding='utf-8')
    (tmp_path/'provider-events.jsonl').write_text('{"schema":"GeneralProposal"}\n',encoding='utf-8')
    summary=render(tmp_path,tmp_path/'baseline.json',tmp_path/'review.json')
    assert summary['planned_turns']==2 and summary['executed_turns']==1 and summary['not_run']==1
    assert summary['appropriate_turns']==1 and summary['resolved_scenarios']==[]
    assert summary['campaign_cost_per_resolved_scenario_usd'] is None
    review['judgments'][0]['response_sha256']='tampered'
    (tmp_path/'review.json').write_text(json.dumps(review),encoding='utf-8')
    with pytest.raises(AssertionError):render(tmp_path,tmp_path/'baseline.json',tmp_path/'review.json')
