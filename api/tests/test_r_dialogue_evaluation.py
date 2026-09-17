from uuid import uuid4
import httpx
import pytest

from app.team.dialogue_evaluation import collect_dialogue


@pytest.mark.asyncio
async def test_server_context_is_used_on_next_turn():
    seen=[]
    context=str(uuid4())
    def handler(request):
        import json
        body=json.loads(request.content)
        if str(request.url).endswith('/sessions'):return httpx.Response(200,json=dict(session_id='1'))
        seen.append(body)
        base=dict(contract_version='v2',request_id=body['request_id'],snapshot_id='1',knowledge_revision='1')
        if len(seen)==1:
            return httpx.Response(200,json=dict(base,action='CLARIFY',message='선택',context_id=context,
                clarification_slot='temperature',allowed_options=['HOT','ICE']),headers={'x-answer-receipt-id':'1','x-context-revision':'4'})
        return httpx.Response(200,json=dict(base,action='ESCALATE',message='확인',pending_id='1'),headers={'x-answer-receipt-id':'2'})
    case=dict(case_id='case1',turns=[dict(turn_id='t1',question='라테 우유?',expected_action='CLARIFY'),
        dict(turn_id='t2',question='따뜻한 것',option='HOT',expected_action='ESCALATE')])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),base_url='http://test') as client:
        run=await collect_dialogue(client,case,headers={},expected_snapshot=dict(snapshot_id='1',knowledge_revision='1'),provider_mode='SYNTHETIC',configuration={})
    assert seen[1]['context_id']==context
    assert seen[1]['context_revision']==4
    assert run['action_sequence_matches']
    assert run['semantic_completion'] is None


@pytest.mark.asyncio
async def test_failed_first_turn_keeps_remaining_denominator():
    case=dict(case_id='c',turns=[dict(turn_id=str(i),question='질문',expected_action='ANSWER') for i in range(3)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(503)),base_url='http://test') as client:
        run=await collect_dialogue(client,case,headers={},expected_snapshot=dict(snapshot_id='1',knowledge_revision='1'),provider_mode='SYNTHETIC',configuration={})
    assert run['planned_turns']==3
    assert [r['status'] for r in run['rows']]==['COLLECTION_ERROR','NOT_RUN','NOT_RUN']
    assert not run['action_sequence_matches']
