"""Real HTTP/general validation with synthetic proposal+verdict; never model quality."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

from app.contracts.hashing import digest
from app.learn.general_semantics import GeneralProposal, source_hash
from scripts.r_fact_evaluation import cited_fact_ids


async def semantic_control(client, db, seeded, settings, headers, output):
    snap=seeded['snapshot']
    item=next(m for m in seeded['mapping'] if m['fact_id']=='CONTROL_HOT')
    ref=item['references'][0]
    selected=dict(card_id=ref['card_id'],card_version_id=ref['card_version_id'],
                  block_id=ref['block_id'],fact_revision_ids=[item['fact_revision_id']])
    release=dict(store_id=str(seeded['store_id']),snapshot_hash=snap.snapshot_hash,
        source_hash=source_hash(),model='synthetic-no-provider',response_style='approved_original',
        acceptance_reference='Synthetic structural control only; not model or production acceptance',
        approved_by='synthetic fixture',valid_until=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),
        max_input_tokens=100000,max_output_tokens=1000,max_prompt_bytes=200000)
    path=output/'synthetic-control-release.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(release,stream,ensure_ascii=False,indent=2)
    calls=[]
    invalid=False
    async def provider(prompt,*,schema,**kw):
        request=json.loads(prompt.rsplit('\n',1)[1])
        calls.append(schema.__name__)
        if schema is GeneralProposal:
            question=request['input']['question']
            return dict(input_hash=request['input']['input_hash'],snapshot_hash=snap.snapshot_hash,
                plan=dict(snapshot_id=snap.snapshot_id,knowledge_revision=snap.knowledge_revision,action='ANSWER',
                    selected_blocks=[dict(selected,fact_revision_ids=['999999999']) if invalid else selected]),
                interpretation=dict(entity_id=item['entity_id'],predicate='milk_amount',variants=[['HOT',None]],
                    target_fact_ids=[item['fact_revision_id']]),
                slots=[dict(slot=k,value=v,question_quote=question) for k,v in
                       [('entity',item['entity_id']),('predicate','milk_amount'),('temperature','HOT')]])
        return dict(request_hash=request['request_hash'],supported=True,unresolved=[],
            checked_fact_ids=[item['fact_revision_id']],checked_raw_blocks=[],checked_conclusion_ids=[],
            situation_review=[],case_action_review=dict(scope='NOT_APPLICABLE',rationale='synthetic control',cases=[]),
            rule_coverage=[],candidate_coverage=[dict(reference=b,
                required=item['fact_revision_id'] in b.get('fact_revision_ids',[]),rationale='synthetic control')
                for b in request['candidate_reference_units']],
            checked_user_turn_ids=[t['turn_id'] for t in request['dialogue_turns']])
    results=[]
    with patch.multiple(settings,r_general_semantics_enabled=True,gemini_model=release['model']), \
         patch.object(settings,'r_general_semantics_path',str(path.resolve()),create=True), \
         patch.object(settings,'r_general_semantics_hash',digest(release),create=True), \
         patch('app.learn.general_provider.generate',provider):
        for invalid in (False,True):
            start=len(calls)
            session=await client.post('/learn/v2/sessions',headers=headers,
                json=dict(request_id=f'semantic-control-session-{invalid}'))
            session.raise_for_status()
            session_id=session.json()['session_id']
            request=dict(session_id=session_id,request_id=f'semantic-control-{invalid}',
                question='HOT 검증음료에 쓰는 우유 투입량을 설명해줘')
            response=await client.post('/learn/v2/chat',headers=headers,json=request)
            body=response.json()
            if invalid:
                count=await db.fetchval('select count(*) from r_answer_receipts where store_id=$1 and session_id=$2',
                    seeded['store_id'],int(session_id))
                pending=await db.fetchval('select count(*) from pending_questions where store_id=$1',seeded['store_id'])
                ok=(response.status_code==503 and body.get('error',{}).get('code')=='GENERAL_INVALID_PROPOSAL'
                    and count==0 and pending==0 and calls[start:]==['GeneralProposal'])
            else:
                ok=response.status_code==200 and body.get('action')=='ANSWER' and calls[start:]==['GeneralProposal','Verification']
                if ok:
                    receipt=int(response.headers['x-answer-receipt-id'])
                    saved=await db.fetchrow('select response,original_question,execution_metadata from r_answer_receipts where store_id=$1 and receipt_id=$2',seeded['store_id'],receipt)
                    stored=json.loads(saved['response'])
                    metadata=json.loads(saved['execution_metadata'])
                    ok=stored==body and saved['original_question']==request['question'] and cited_fact_ids(seeded['mapping'],body['citations'])==['CONTROL_HOT']
                    ok=ok and metadata['general_semantics']['status']=='STRUCTURE_AND_MODEL_CHECKED'
                    for n in range(1,len(body['citations'])+1):
                        detail=await client.get(f'/learn/v2/receipts/{receipt}/citations/{n}',headers=headers)
                        ok=ok and detail.status_code==200 and detail.json()['source_kind']=='OWNER_TEXT'
            results.append(dict(control='GENERAL_INVALID_REFERENCE' if invalid else 'GENERAL_FACT_ANSWER',
                request=request,http_status=response.status_code,response=body,passed=ok,
                synthetic_adapter_calls=calls[start:],paid_provider_calls=0))
    return results
