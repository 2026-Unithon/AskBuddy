"""Real W split cards → canonical entity choice → temperature choice → general answer."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
from app.contracts.hashing import digest
from app.deps import create_token
from app.learn.general_semantics import GeneralProposal,source_hash
from scripts.r_fact_evaluation import seed,controls_challenge,challenge_hash


async def verify_split(client,db,pool,settings,output):
    fixture=controls_challenge();other=deepcopy(fixture['facts'][0])
    other.update(fact_id='OTHER',category='비교음료',assertion='HOT 비교음료 우유 225ml')
    other['w_assertion'].update(local_ref='OTHER',subject='비교음료',original_assertion=other['assertion'])
    fixture['facts'].append(other);fixture['content_sha256']=challenge_hash(fixture)
    with patch('app.ingest.card_plan.MAX_FACTS_PER_BLOCK',1),patch('app.ingest.card_plan.MAX_BLOCKS_PER_CARD',1):
        seeded=await seed(pool,db,fixture)
    snap=seeded['snapshot'];target=next(m for m in seeded['mapping'] if m['fact_id']=='CONTROL_HOT')
    assert len([c for c in snap.cards if c.entity_id==target['entity_id']])==2
    release=dict(store_id=str(seeded['store_id']),snapshot_hash=snap.snapshot_hash,source_hash=source_hash(),model='synthetic-p4-split',
        acceptance_reference='SYNTHETIC SPLIT CONTEXT ONLY',approved_by='synthetic',valid_until=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),
        max_input_tokens=100000,max_output_tokens=1000,max_prompt_bytes=200000)
    from scripts.run_r_operations_http import write_new
    path=output/'split-release.json';write_new(path,release);write_new(output/'split-snapshot.json',snap.model_dump(mode='json'))
    step=0;requests=[];results=[]
    async def provider(prompt,*,schema,**kw):
        req=json.loads(prompt.rsplit('\n',1)[1]);requests.append(req)
        if schema is GeneralProposal:
            p=req['input'];base=dict(snapshot_id=p['snapshot_id'],knowledge_revision=p['knowledge_revision'])
            raw=dict(input_hash=p['input_hash'],snapshot_hash=p['snapshot_hash'])
            if step==0:
                return dict(raw,plan=dict(**base,action='CLARIFY',clarification_slot='entity',allowed_options=['검증음료','비교음료']))
            assert req['confirmed_slots']['entity']=='검증음료'
            raw.update(interpretation=dict(entity_id=target['entity_id'],predicate='milk_amount',variants=[],target_fact_ids=[]),
                slots=[dict(slot=k,value=v,question_quote=p['question']) for k,v in [('entity',target['entity_id']),('predicate','milk_amount')]])
            if step==1:
                return dict(raw,plan=dict(**base,action='CLARIFY',clarification_slot='temperature',allowed_options=['HOT','ICE']))
            assert req['confirmed_slots']=={'entity':'검증음료','temperature':'HOT'}
            ref=target['references'][0]
            raw['interpretation'].update(variants=[['HOT',None]],target_fact_ids=[target['fact_revision_id']])
            return dict(raw,plan=dict(**base,action='ANSWER',selected_blocks=[dict(card_id=ref['card_id'],
                card_version_id=ref['card_version_id'],block_id=ref['block_id'],fact_revision_ids=[target['fact_revision_id']])]))
        selected=req['selected_reference_check']
        return dict(request_hash=req['request_hash'],supported=True,unresolved=[],**selected,
            checked_user_turn_ids=[t['turn_id'] for t in req['dialogue_turns']],checked_conclusion_ids=[],
            candidate_coverage=[dict(reference=r,required=target['fact_revision_id'] in r['fact_revision_ids'],rationale='Synthetic HOT fact')
                for r in req['candidate_reference_units']] if step==2 else [])
    headers={'Authorization':'Bearer '+create_token(dict(store_id=seeded['store_id'],user_id=seeded['user_id'],role='STAFF',
        exp=datetime.now(timezone.utc)+timedelta(minutes=10)))}
    with patch.multiple(settings,r_general_semantics_enabled=True,gemini_model=release['model']), \
         patch.object(settings,'r_general_semantics_path',str(path.resolve())), \
         patch.object(settings,'r_general_semantics_hash',digest(release)),patch('app.learn.general_provider.generate',provider):
        session=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id='split-context-session'))
        session.raise_for_status();choice={}
        try:
            for step,(q,action) in enumerate([('음료에 쓰는 우유 투입량을 설명해줘','CLARIFY'),('검증음료','CLARIFY'),('HOT','ANSWER')]):
                r=await client.post('/learn/v2/chat',headers=headers,json=dict(session_id=session.json()['session_id'],
                    request_id=f'p4-split-{step}',question=q,**choice))
                body=r.json();results.append(dict(http_status=r.status_code,response=body))
                assert r.status_code==200 and body['action']==action,body
                if step<2:choice=dict(context_id=body['context_id'],context_revision=int(r.headers['x-context-revision']),option='검증음료' if step==0 else 'HOT')
                else:
                    assert [c['fact_revision_id'] for c in body['citations']]==[target['fact_revision_id']]
                    rid=int(r.headers['x-answer-receipt-id'])
                    saved=await db.fetchval('select response from r_answer_receipts where store_id=$1 and receipt_id=$2',seeded['store_id'],rid)
                    assert json.loads(saved)==body
                    detail=await client.get(f'/learn/v2/receipts/{rid}/citations/1',headers=headers)
                    assert detail.status_code==200 and detail.json()['source_kind']=='OWNER_TEXT'
        finally:
            write_new(output/'split-turns.json',results);write_new(output/'split-adapter-inputs.json',requests)
    return [dict(control='W split canonical entity → temperature → general fact answer and citation',passed=True)]
