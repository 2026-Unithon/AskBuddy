"""Disposable HTTP/DB integration; only external Gemini responses are synthetic."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import json
from app.contracts.hashing import digest
from app.contracts.validate import validate_answer_references
from app.learn.planner import decide
from app.learn.general_semantics import general_decision,source_hash
from app.learn.semantic_proposals import proposal_input


async def verify(chat,client,headers,pool,admin,seed,settings,title):
    original_enabled=getattr(settings,'r_general_semantics_enabled',False)
    settings.gemini_model='synthetic-general'
    settings.gemini_api_key='synthetic'
    calls=[]
    current={}
    mode='success'
    async def generate(**kw):
        assert pool.get_idle_size()==pool.get_size()
        calls.append(kw)
        request=json.loads(kw['contents'].split('\nJSON schema:\n')[0].split('\n',1)[1])
        if 'proposal' in request:
            refs=validate_answer_references(current['original'].plan,current['search'].snapshot,store_id=str(seed['store_id']))
            raw=dict(request_hash=request['request_hash'],supported=True,unresolved=[],checked_fact_ids=refs.fact_ids,checked_raw_blocks=refs.raw_blocks)
        else:
            search=current['search'];original=current['original'];q=request['input']['question'];a=original.resolved.assessment
            raw=dict(input_hash=request['input']['input_hash'],snapshot_hash=search.snapshot.snapshot_hash,
                plan=original.plan.model_dump(mode='json'),interpretation=dict(entity_id=a.entity_id,predicate=a.predicate,
                    variants=a.variants,target_fact_ids=a.target_fact_ids),
                slots=[dict(slot='entity',value=a.entity_id,question_quote=q),dict(slot='predicate',value=a.predicate,question_quote=q)])
            if mode=='bad':raw['plan']['selected_blocks'][0]['raw_span_id']='999999'
        return NS(text=json.dumps(raw),usage_metadata=NS(prompt_token_count=10,candidates_token_count=10,thoughts_token_count=0))
    sdk=NS(aio=NS(models=NS(count_tokens=AsyncMock(return_value=NS(total_tokens=10)),generate_content=generate),aclose=AsyncMock()))
    with TemporaryDirectory() as directory:
        path=Path(directory)/'synthetic-release.json'
        async def adapted(search,**kw):
            current.update(search=search,original=decide(search,store_id=seed['store_id'],question=title+' 승인 원문 보여줘'))
            raw=dict(store_id=str(seed['store_id']),snapshot_hash=search.snapshot.snapshot_hash,source_hash=source_hash(),
                model=settings.gemini_model,acceptance_reference='SYNTHETIC ONLY',approved_by='synthetic',
                valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),max_input_tokens=100000,max_output_tokens=1000,max_prompt_bytes=200000)
            path.write_text(json.dumps(raw),encoding='utf-8')
            settings.r_general_semantics_enabled=True;settings.r_general_semantics_path=str(path);settings.r_general_semantics_hash=digest(raw)
            return await general_decision(search,**kw)
        try:
            with patch('app.learn.general_semantics.general_decision',side_effect=adapted), \
                    patch('app.learn.general_provider.get_settings',return_value=settings),patch('google.genai.Client',return_value=sdk):
                before=await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])
                for n,q in enumerate(('이 매장의 해당 준비 절차를 설명해주세요','방금 입사했는데 준비 작업을 알려줄래요')):
                    response=await chat('general-free-'+str(n),q)
                    assert response.status_code==200 and response.json()['action']=='ANSWER',response.text
                    rid=int(response.headers['x-answer-receipt-id'])
                    audit=await admin.fetchval("select execution_metadata->'general_semantics'->>'status' from r_answer_receipts where receipt_id=$1",rid)
                    assert audit=='STRUCTURE_AND_MODEL_CHECKED'
                    citation=await client.get(f'/learn/v2/receipts/{rid}/citations/1',headers=headers)
                    assert citation.status_code==200
                assert len(calls)==4
                replay=await chat('general-free-0','이 매장의 해당 준비 절차를 설명해주세요')
                assert replay.headers.get('x-answer-replayed')=='true' and len(calls)==4
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before
                mode='bad'
                response=await chat('general-invalid','처음 보는 준비 업무를 설명해 주세요')
                assert response.status_code==503 and response.json()['error']['code']=='GENERAL_INVALID_PROPOSAL',response.text
                assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where request_id='general-invalid')")
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before
                assert await admin.fetchval("select count(*) from ai_usage_attempts where store_id=$1 and logical_call_id like 'general:%' and stage='ANSWER'",seed['store_id'])==5
        finally:settings.r_general_semantics_enabled=original_enabled
    print('PASS general HTTP: two unregistered phrasings, two model calls, durable usage/answer/citation/audit, replay, invalid-reference rollback')
