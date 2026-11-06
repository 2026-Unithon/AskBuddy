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
        request=json.loads(kw['contents'].split('\nJSON schema:\n')[0].rsplit('\n',1)[1])
        if 'proposal' in request:
            refs=validate_answer_references(current['original'].plan,current['search'].snapshot,store_id=str(seed['store_id']))
            raw=dict(request_hash=request['request_hash'],supported=True,unresolved=[],checked_fact_ids=refs.fact_ids,
                situation_review=[dict(conclusion_unit_id=u['unit_id'],status='NO_CASE_FACTS',user_evidence=[],rationale='Synthetic structural fixture only') for u in request['conclusion_units']],
                case_action_review=dict(scope='NOT_APPLICABLE',rationale='synthetic fixture without case actions',cases=[]),
                rule_coverage=[dict(rule_id=r['rule_id'],required=True,conclusion_unit_id='c0s0',
                    rationale='synthetic structural fixture only') for r in request.get('selected_rules',[])],
                candidate_coverage=[dict(reference=b,required=b in request['proposal']['plan']['selected_blocks'],rationale='synthetic fixture') for b in request['candidate_reference_units']],
                checked_conclusion_ids=list(range(len(request['proposal'].get('conclusions',[])))),
                checked_raw_blocks=refs.raw_blocks,checked_user_turn_ids=[t['turn_id'] for t in request['dialogue_turns']])
            if mode in ('CONTEXT_CONFLICT','INCOMPLETE_ANSWER','UNVERIFIABLE','MISSING_KNOWLEDGE'):
                raw.update(supported=False,reason_code=mode,reason_detail='synthetic verifier explanation')
            if mode=='coverage-missing':
                omitted=next(c for c in raw['candidate_coverage'] if not c['required'])
                omitted.update(required=True,rationale='synthetic required prerequisite omitted by proposal')
            if mode=='rule-missing':raw['rule_coverage'][0].update(conclusion_unit_id=None)
            if mode=='situation-unsupported':raw['situation_review'][0]['status']='UNSUPPORTED_CASE_FACTS'
            if mode in ('case-action-missing','case-action-complete'):
                q=request['input']['question'];at=len(request['input']['user_turns'])
                raw['case_action_review']=dict(scope='CASE_ACTIONS',rationale='synthetic case action omitted',cases=[
                    dict(subject=dict(turn_id=at,quote='A'),state=dict(turn_id=at,quote='미확인'),conclusion_id=None,next_action_quote='')])
                if mode=='case-action-complete':raw['case_action_review']['cases'][0].update(conclusion_id=0,next_action_quote='승인된 준비 절차를 확인')
            if mode=='case':
                turns=request['input']['user_turns']
                at=turns.index('A는 결제 상태 미확인, B는 환불 승인 대기야.')
                raw.update(supported=False,reason_code='MISSING_USER_INFO',reason_detail='A/B 대상 확인',
                    clarification=dict(slot='case',scope_supported=True,allowed_options=['A','B'],
                        case_options=[dict(label=x,turn_id=at,question_quote=turns[at]) for x in ('A','B')]))
        else:
            search=current['search'];original=current['original'];q=request['input']['question'];a=original.resolved.assessment
            if mode=='case-selected':
                assert request['confirmed_slots']=={'case':'A'}
                assert 'A는 결제 상태 미확인, B는 환불 승인 대기야.' in request['input']['user_turns']
                assert request['input']['question']=='그 건은 메시지 읽었대. 인계 완료로 해도 돼? A'
            else:assert request['confirmed_slots']=={},'planner guesses must not become accepted user context'
            raw=dict(input_hash=request['input']['input_hash'],snapshot_hash=search.snapshot.snapshot_hash,
                plan=original.plan.model_dump(mode='json'),interpretation=dict(entity_id=a.entity_id,predicate=a.predicate,
                    variants=a.variants,target_fact_ids=a.target_fact_ids),
                slots=[dict(slot='entity',value=a.entity_id,question_quote=q),dict(slot='predicate',value=a.predicate,question_quote=q)])
            if mode=='bad':raw['plan']['selected_blocks'][0]['raw_span_id']='999999'
            if mode in ('conclusion','rule-missing','case-action-missing','case-action-complete','situation-unsupported'):
                raw['conclusions']=[dict(statement='현재 질문은 아래 승인된 준비 절차를 따르세요.',question_quote=q,
                    user_evidence=[dict(turn_id=len(request['input']['user_turns']),quote=q)],
                    references=raw['plan']['selected_blocks'])]
                raw['case_requirements']=dict(scope='NOT_APPLICABLE',rationale='Synthetic general procedure',cases=[])
                if mode in ('case-action-missing','case-action-complete'):
                    raw['case_requirements']=dict(scope='CASE_ACTIONS',rationale='Synthetic named case',cases=[
                        dict(subject=dict(turn_id=len(request['input']['user_turns']),quote='A'),
                             state=dict(turn_id=len(request['input']['user_turns']),quote='미확인'))])
                if mode=='case-action-complete':raw['conclusions'][0]['statement']='A는 미확인 상태이므로 승인된 준비 절차를 확인하세요.'
        return NS(text=json.dumps(raw),candidates=[NS(finish_reason='STOP')],usage_metadata=NS(prompt_token_count=10,candidates_token_count=10,thoughts_token_count=0))
    sdk=NS(aio=NS(models=NS(count_tokens=AsyncMock(return_value=NS(total_tokens=10)),generate_content=generate),aclose=AsyncMock()))
    with TemporaryDirectory() as directory:
        path=Path(directory)/'synthetic-release.json'
        async def adapted(search,**kw):
            current.update(search=search,original=decide(search,store_id=seed['store_id'],question=title+' 승인 원문 보여줘'))
            raw=dict(store_id=str(seed['store_id']),snapshot_hash=search.snapshot.snapshot_hash,source_hash=source_hash(),
                response_style='grounded_conclusion' if mode in ('conclusion','rule-missing','case-action-missing','case-action-complete','situation-unsupported') else 'approved_original',
                model=settings.gemini_model,acceptance_reference='SYNTHETIC ONLY',approved_by='synthetic',
                valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),max_input_tokens=100000,max_output_tokens=1000,max_prompt_bytes=200000)
            path.write_text(json.dumps(raw),encoding='utf-8')
            settings.r_general_semantics_enabled=True;settings.r_general_semantics_path=str(path);settings.r_general_semantics_hash=digest(raw)
            return await general_decision(search,**kw)
        try:
            with patch('app.learn.general_semantics.general_decision',side_effect=adapted), \
                    patch('app.learn.general_provider.get_settings',return_value=settings),patch('google.genai.Client',return_value=sdk):
                before=await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])
                first_question=title+' 준비 절차를 설명해주세요'
                for n,q in enumerate((first_question,'방금 입사했는데 준비 작업을 알려줄래요')):
                    response=await chat('general-free-'+str(n),q)
                    assert response.status_code==200 and response.json()['action']=='ANSWER',response.text
                    rid=int(response.headers['x-answer-receipt-id'])
                    audit=await admin.fetchval("select execution_metadata->'general_semantics'->>'status' from r_answer_receipts where receipt_id=$1",rid)
                    assert audit=='STRUCTURE_AND_MODEL_CHECKED'
                    citation=await client.get(f'/learn/v2/receipts/{rid}/citations/1',headers=headers)
                    assert citation.status_code==200
                    if n:
                        proposal_input_payload=json.loads(calls[-2]['contents'].split('\nJSON schema:\n')[0].rsplit('\n',1)[1])['input']
                        assert proposal_input_payload['user_turns'][-1]==first_question
                        history=await admin.fetchval("select execution_metadata->'dialogue_receipt_ids' from r_answer_receipts where receipt_id=$1",rid)
                        assert json.loads(history) if isinstance(history,str) else history
                assert len(calls)==4
                replay=await chat('general-free-0',first_question)
                assert replay.headers.get('x-answer-replayed')=='true' and len(calls)==4
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before
                mode='bad'
                response=await chat('general-invalid','처음 보는 준비 업무를 설명해 주세요')
                assert response.status_code==503 and response.json()['error']['code']=='GENERAL_INVALID_PROPOSAL',response.text
                assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where request_id='general-invalid')")
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before
                assert await admin.fetchval("select count(*) from ai_usage_attempts where store_id=$1 and logical_call_id like 'general:%' and stage='ANSWER'",seed['store_id'])==5
                for mode in ('CONTEXT_CONFLICT','INCOMPLETE_ANSWER','UNVERIFIABLE'):
                    key='general-rejected-'+mode
                    response=await chat(key,'아, 앞에서 말한 건 어제 거래였어. 금액은 같아.')
                    assert response.status_code==503 and response.json()['error']['code']=='GENERAL_VERIFICATION_REJECTED',response.text
                    assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where store_id=$1 and request_id=$2)",seed['store_id'],key)
                    assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before
                mode='MISSING_KNOWLEDGE'
                response=await chat('general-missing-rule','자료에 없는 업무 조건도 알려줘')
                assert response.status_code==200 and response.json()['action']=='ESCALATE',response.text
                rid=int(response.headers['x-answer-receipt-id'])
                audit=await admin.fetchval("select execution_metadata->'general_semantics' from r_answer_receipts where store_id=$1 and receipt_id=$2",seed['store_id'],rid)
                audit=json.loads(audit) if isinstance(audit,str) else audit
                assert audit['reason_code']=='MISSING_KNOWLEDGE' and audit['reason_detail']=='synthetic verifier explanation'
                assert audit['proposal_ms']>=0 and audit['verification_ms']>=0
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='success'
                assert (await chat('general-case-original','A는 결제 상태 미확인, B는 환불 승인 대기야.')).status_code==200
                mode='case'
                response=await chat('general-case-clarify','그 건은 메시지 읽었대. 인계 완료로 해도 돼?')
                assert response.status_code==200 and response.json()['action']=='CLARIFY',response.text
                body=response.json()
                assert body['clarification_slot']=='case' and body['allowed_options']==['A','B']
                assert body['pending_id'] is None and '어느 건' in body['message']
                cid=body['context_id'];revision=int(response.headers['x-context-revision'])
                calls_before=len(calls)
                other=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id='general-case-other-session'))
                foreign=await client.post('/learn/v2/chat',headers=headers,json=dict(
                    request_id='general-case-foreign-session',session_id=other.json()['session_id'],question='A',
                    option='A',context_id=cid,context_revision=revision))
                assert foreign.status_code==404 and len(calls)==calls_before
                invented=await chat('general-case-invented','C',option='C',context_id=cid,context_revision=revision)
                assert invented.status_code==422 and len(calls)==calls_before
                mode='case-selected'
                selected=await chat('general-case-selected','A',option='A',context_id=cid,context_revision=revision)
                assert selected.status_code==200 and selected.json()['action']=='ANSWER',selected.text
                calls_before=len(calls)
                replay=await chat('general-case-selected','A',option='A',context_id=cid,context_revision=revision)
                assert replay.headers.get('x-answer-replayed')=='true' and len(calls)==calls_before
                stale=await chat('general-case-stale','B',option='B',context_id=cid,context_revision=revision)
                assert stale.status_code==422 and len(calls)==calls_before
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='MISSING_KNOWLEDGE'
                calls_before=len(calls)
                replay=await chat('general-missing-rule','자료에 없는 업무 조건도 알려줘')
                assert replay.headers.get('x-answer-replayed')=='true' and len(calls)==calls_before
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='conclusion'
                response=await chat('general-conclusion','현재 상황에 적용할 준비 절차를 설명해 주세요')
                assert response.status_code==200 and response.json()['action']=='ANSWER',response.text
                assert '현재 질문에 대한 안내' in response.json()['message'] and '[출처 1]' in response.json()['message']
                assert '승인 근거' in response.json()['message']
                rid=int(response.headers['x-answer-receipt-id'])
                stored=await admin.fetchrow('''select m.answer_source,m.grounding_status,r.resolved_query
                    from r_answer_receipts r join chat_messages m on m.message_id=r.buddy_message_id and m.session_id=r.session_id
                    where r.store_id=$1 and r.receipt_id=$2''',seed['store_id'],rid)
                assert stored['answer_source']=='GROUNDED_LLM' and stored['grounding_status']=='VERIFIED'
                resolved=json.loads(stored['resolved_query']) if isinstance(stored['resolved_query'],str) else stored['resolved_query']
                assert resolved['conclusions'][0]['statement']=='현재 질문은 아래 승인된 준비 절차를 따르세요.'
                citation=await client.get(f'/learn/v2/receipts/{rid}/citations/1',headers=headers)
                assert citation.status_code==200
                calls_before=len(calls)
                replay=await chat('general-conclusion','현재 상황에 적용할 준비 절차를 설명해 주세요')
                assert replay.headers.get('x-answer-replayed')=='true' and len(calls)==calls_before
                assert replay.json()==response.json()
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='coverage-missing'
                response=await chat('general-coverage-missing','준비하기 전 확인할 사항까지 모두 설명해 주세요')
                assert response.status_code==503 and response.json()['error']['code']=='GENERAL_VERIFICATION_REJECTED',response.text
                assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='general-coverage-missing')",seed['store_id'])
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='rule-missing'
                missing_rule=await chat('general-rule-missing','선행 확인을 포함한 준비 절차를 알려주세요')
                assert missing_rule.status_code==503 and missing_rule.json()['error']['code']=='GENERAL_VERIFICATION_REJECTED',missing_rule.text
                assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='general-rule-missing')",seed['store_id'])
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='situation-unsupported'
                unsupported=await chat('general-situation-unsupported','현재 상황에 적용할 준비 절차를 설명해 주세요')
                assert unsupported.status_code==503 and unsupported.json()['error']['code']=='GENERAL_VERIFICATION_REJECTED',unsupported.text
                assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='general-situation-unsupported')",seed['store_id'])
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='case-action-missing'
                missing_case=await chat('general-case-action-missing','A는 미확인 상태야. 다음 담당자에게 어떤 조치를 인계해?')
                assert missing_case.status_code==503 and missing_case.json()['error']['code']=='GENERAL_VERIFICATION_REJECTED',missing_case.text
                assert not await admin.fetchval("select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='general-case-action-missing')",seed['store_id'])
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                mode='case-action-complete'
                complete_case=await chat('general-case-action-complete','A는 미확인 상태야. 다음 담당자에게 어떤 조치를 인계해?')
                assert complete_case.status_code==200 and 'A는 미확인' in complete_case.json()['message'],complete_case.text
                case_audit=await admin.fetchval("select execution_metadata from r_answer_receipts where store_id=$1 and request_id='general-case-action-complete'",seed['store_id'])
                if isinstance(case_audit,str):case_audit=json.loads(case_audit)
                assert case_audit['general_semantics']['case_action_review']['cases'][0]['next_action_quote']=='승인된 준비 절차를 확인'
                recovery_session=await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id='recover-error-session'))
                recovery_sid=recovery_session.json()['session_id']
                async def recover_chat(key,q,**extra):
                    return await client.post('/learn/v2/chat',headers=headers,json=dict(request_id=key,session_id=recovery_sid,question=q,**extra))
                mode='bad'
                original_q='A는 결제 상태 미확인, B는 환불 승인 대기야.'
                failed=await recover_chat('recover-error-original',original_q)
                assert failed.status_code==503,failed.text
                assert await admin.fetchval('select count(*) from r_failed_user_turns where store_id=$1 and session_id=$2',seed['store_id'],int(recovery_sid))==1
                failed=await recover_chat('recover-error-original',original_q)
                assert failed.status_code==503
                assert await admin.fetchval('select count(*) from r_failed_user_turns where store_id=$1 and session_id=$2',seed['store_id'],int(recovery_sid))==1
                calls_before=len(calls)
                conflict=await recover_chat('recover-error-original','다른 본문')
                assert conflict.status_code==409 and len(calls)==calls_before
                history=await client.get(f'/learn/v2/sessions/{recovery_sid}/history',headers=headers)
                assert history.json()['messages']==[]  # No fake successful message/answer.
                mode='case'
                clarified=await recover_chat('recover-error-case','그 건은 메시지 읽었대. 인계 완료로 해도 돼?')
                assert clarified.status_code==200 and clarified.json()['allowed_options']==['A','B'],clarified.text
                audit=await admin.fetchval("select execution_metadata->'dialogue_failed_turn_ids' from r_answer_receipts where store_id=$1 and request_id='recover-error-case'",seed['store_id'])
                assert (json.loads(audit) if isinstance(audit,str) else audit)
                mode='case-selected'
                selected=await recover_chat('recover-error-selected','A',option='A',context_id=clarified.json()['context_id'],context_revision=int(clarified.headers['x-context-revision']))
                assert selected.status_code==200 and selected.json()['action']=='ANSWER',selected.text
                assert await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==before+1
                from app.learn.failed_user_turns import failed_turns,validate_failed_head
                from app.errors import ApiError
                recovery_mid=await admin.fetchval('select member_id from chat_sessions where store_id=$1 and session_id=$2',seed['store_id'],int(recovery_sid))
                async with pool.acquire() as conn:
                    for other in (dict(store_id=seed['store_id']+100000,member_id=recovery_mid,session_id=int(recovery_sid)),
                                  dict(store_id=seed['store_id'],member_id=recovery_mid+100000,session_id=int(recovery_sid)),
                                  dict(store_id=seed['store_id'],member_id=recovery_mid,session_id=int(recovery_sid)+100000)):
                        assert not await failed_turns(conn,**other)
                    try:await validate_failed_head(conn,store_id=seed['store_id'],member_id=recovery_mid,session_id=int(recovery_sid),request_id='next-request',expected_head=0)
                    except ApiError as exc:assert exc.code=='STALE_DIALOGUE'
                    else:raise AssertionError('concurrent failed history accepted')
                mode='success'
                calls_before=len(calls)
                retried=await recover_chat('recover-error-original',original_q)
                # Existing usage idempotency prevents charging the same logical
                # request twice; recovery must not bypass this guard.
                assert retried.status_code==503 and retried.json()['error']['code']=='USAGE_UNAVAILABLE',retried.text
                assert len(calls)==calls_before
                from app.learn.failed_user_turns import record_failed_turn
                await record_failed_turn(pool,store_id=seed['store_id'],member_id=recovery_mid,session_id=int(recovery_sid),
                    request_id='recover-error-selected',question='A',error_code='GENERAL_INVALID_PROPOSAL')
                async with pool.acquire() as conn:
                    assert len(await failed_turns(conn,store_id=seed['store_id'],member_id=recovery_mid,session_id=int(recovery_sid)))==1
                import asyncpg
                for wrong_store,code,expected_error in ((seed['store_id']+100000,'GENERAL_INVALID_PROPOSAL',asyncpg.ForeignKeyViolationError),
                                                       (seed['store_id'],'ANSWER',asyncpg.CheckViolationError)):
                    try:
                        async with admin.transaction():
                            await admin.execute('''insert into r_failed_user_turns(store_id,member_id,session_id,request_id,question,error_code)
                                values($1,$2,$3,'invalid-recovery','합성 검증',$4)''',wrong_store,recovery_mid,int(recovery_sid),code)
                    except expected_error:pass
                    else:raise AssertionError('failed recovery DB guard accepted invalid row')
                for role in ('anon','authenticated'):
                    assert not await admin.fetchval("select has_table_privilege($1,'r_failed_user_turns','SELECT')",role)
                mode='bad'
                await recover_chat('recover-expired-test','만료될 사용자 질문')
                await admin.execute("update r_failed_user_turns set expires_at=clock_timestamp()-interval '1 second' where store_id=$1 and request_id='recover-expired-test'",seed['store_id'])
                async with pool.acquire() as conn:
                    assert all(r['question']!='만료될 사용자 질문' for r in await failed_turns(conn,store_id=seed['store_id'],member_id=recovery_mid,session_id=int(recovery_sid)))
        finally:settings.r_general_semantics_enabled=original_enabled
    print('PASS general HTTP: grounded conclusion/original/citation persistence and replay; required evidence omission overrides supported verdict with no receipt/pending; A/B frozen context, foreign-session/invented/stale choice blocked; owner handoff audit')
