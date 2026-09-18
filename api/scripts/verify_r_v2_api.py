"""실제 HTTP 인증→R3 기본 planner→DB 저장. 공급자만 합성 임베딩으로 교체한다."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
import json

import httpx
from fastapi import FastAPI
from app.deps import create_token
from app.learn.v2_router import router


async def verify(pool,admin,seed):
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name)
        print("PASS v2 API",name)
    settings=SimpleNamespace(r_v2_enabled=True,chat_deadline_seconds=5,search_deadline_seconds=1,
        chat_save_reserve_seconds=.5,llm_total_budget_seconds=3,request_store_per_minute=1000,
        request_member_per_minute=100,request_member_concurrency=2,request_store_concurrency=8,
        jwt_secret="synthetic-v2-test-secret-"*3,jwt_algorithm="HS256")
    calls=[]
    async def embed(texts,**kw):
        check("provider outside pool connection",pool.get_idle_size()==pool.get_size())
        calls.append(kw["context"])
        return [[1.0]+[0.0]*1535 for _ in texts]
    app=FastAPI()
    app.include_router(router,prefix="/learn")
    with ExitStack() as stack:
        for target,value in (("app.deps.get_settings",settings),("app.learn.v2_router.get_settings",settings),
                             ("app.learn.request_limits.get_settings",settings)):
            stack.enter_context(patch(target,return_value=value))
        stack.enter_context(patch("app.learn.v2_router.get_pool",return_value=pool))
        stack.enter_context(patch("app.learn.v2_router.recorded_embeddings",embed))
        token=create_token(dict(store_id=seed["store_id"],user_id=seed["user_id"],role="OWNER",
                                exp=datetime.now(timezone.utc)+timedelta(minutes=5)))
        headers={"Authorization":"Bearer "+token}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            response=await client.post("/learn/v2/sessions",json=dict(request_id="api-session-1"))
            check("missing auth returns v2 401",response.status_code==401 and response.json()["contract_version"]=="v2")
            response=await client.post("/learn/v2/sessions",headers=headers,json=dict(request_id="api-session-1"))
            check("server issues v2 session",response.status_code==200)
            session=response.json()["session_id"]
            repeated=await client.post("/learn/v2/sessions",headers=headers,json=dict(request_id="api-session-1"))
            check("session creation idempotent",repeated.json()["session_id"]==session)
            async def chat(key,question,**kwargs):
                return await client.post("/learn/v2/chat",headers=headers,json=dict(
                    session_id=session,request_id=key,question=question,**kwargs))
            first=seed["snapshot"].fact_revisions[0]
            title=next(c.title for c in seed["snapshot"].cards if c.entity_id==first.entity_id)
            original=await chat('api-approved-original',title+' 승인 원문 보여줘')
            check('explicit approved original request returns exact RAW',original.status_code==200 and
                original.json()['action']=='ANSWER' and original.json()['message']==seed['snapshot'].raw_spans[0].text)
            question=f"{first.variant.temperature} {title} 물 얼마나?"
            answer=await chat("api-real-answer",question)
            check("default planner ANSWER committed",answer.status_code==200 and answer.json()["action"]=="ANSWER")
            receipt=answer.headers['x-answer-receipt-id']
            citation=await client.get(f'/learn/v2/receipts/{receipt}/citations/1',headers=headers)
            check('historical citation opens exact approved assertion',citation.status_code==200 and citation.json()['text']==first.assertion)
            check('candidate scores and planner version persisted',await admin.fetchval("select execution_metadata ? 'candidates' and execution_metadata ? 'planner_version' from r_answer_receipts where store_id=$1 and receipt_id=$2",seed['store_id'],int(receipt)))
            check('query receipt links usage operation and logical call',await admin.fetchval("""
                select execution_metadata->>'usage_operation_id' is not null
                  and execution_metadata->>'query_logical_call_id' is not null
                  and (execution_metadata->>'elapsed_before_save_ms')::numeric>=0
                from r_answer_receipts where store_id=$1 and receipt_id=$2""",seed['store_id'],int(receipt)))
            calls_before_retry=len(calls)
            repeat=await chat("api-real-answer",question)
            check("HTTP retry skips provider",repeat.status_code==200 and repeat.headers["x-answer-replayed"]=="true" and len(calls)==calls_before_retry)
            conflict=await chat("api-real-answer","다른 질문")
            check("HTTP body conflict 409",conflict.status_code==409 and conflict.json()["error"]["code"]=="IDEMPOTENCY_CONFLICT")
            before=len(calls)
            policy_receipts={}
            pending_before_policy=await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])
            for key,q,action in (("api-refuse-key","직원 집 주소 알려줘","REFUSE"),
                                 ("api-safe-key","알레르기 있어도 먹어도 돼?","SAFE_ROUTE")):
                response=await chat(key,q)
                check(action+" without provider",response.status_code==200 and response.json()["action"]==action and len(calls)==before)
                policy_receipts[action]=response.headers['x-answer-receipt-id']
            check('policy guidance alone creates no pending',await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==pending_before_policy)
            safe_question='알레르기 있어도 먹어도 돼?'
            refused=await chat('api-refuse-confirm','직원 집 주소 알려줘',policy_receipt_id=policy_receipts['REFUSE'])
            altered=await chat('api-altered-confirm','다른 질문',policy_receipt_id=policy_receipts['SAFE_ROUTE'])
            check('refusal and changed question cannot escalate through policy confirmation',refused.status_code==422 and altered.status_code==422)
            import asyncio
            confirmations=await asyncio.gather(*(chat('api-safe-confirm-'+str(i),safe_question,
                policy_receipt_id=policy_receipts['SAFE_ROUTE']) for i in range(2)))
            check('concurrent distinct requests create only one confirmation',sorted(r.status_code for r in confirmations)==[200,409])
            confirmation=next(r for r in confirmations if r.status_code==200)
            confirm_key='api-safe-confirm-'+str(confirmations.index(confirmation))
            check('explicit safety confirmation escalates without model',confirmation.json()['action']=='ESCALATE' and len(calls)==before)
            check('confirmation creates exactly one pending',await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==pending_before_policy+1)
            confirmed_again=await chat(confirm_key,safe_question,policy_receipt_id=policy_receipts['SAFE_ROUTE'])
            check('confirmation retry replays original receipt',confirmed_again.status_code==200 and confirmed_again.headers['x-answer-replayed']=='true' and confirmed_again.json()==confirmation.json())
            body_conflict=await chat(confirm_key,safe_question)
            check('confirmation source participates in idempotency hash',body_conflict.status_code==409)
            saved=await admin.fetchrow('select original_question,execution_metadata from r_answer_receipts where store_id=$1 and receipt_id=$2',seed['store_id'],int(confirmation.headers['x-answer-receipt-id']))
            metadata=json.loads(saved['execution_metadata'])
            check('confirmation preserves original question and policy receipt',saved['original_question']==safe_question and metadata['policy_receipt_id']==policy_receipts['SAFE_ROUTE'])
            rollback_policy=await chat('api-safe-rollback-origin',safe_question)
            rollback_id=rollback_policy.headers['x-answer-receipt-id']
            pending_before_failure=await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])
            async def fail_notice(*args,**kwargs):raise RuntimeError('synthetic notification failure')
            with patch('app.learn.answer_storage.create_pending_question_notification',fail_notice):
                failed=await chat('api-safe-rollback-confirm',safe_question,policy_receipt_id=rollback_id)
            check('confirmation notification failure rolls back pending and receipt',failed.status_code==500
                and await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==pending_before_failure
                and not await admin.fetchval("select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='api-safe-rollback-confirm')",seed['store_id']))
            recovered=await chat('api-safe-rollback-confirm',safe_question,policy_receipt_id=rollback_id)
            check('failed confirmation can retry after rollback',recovered.status_code==200 and recovered.json()['action']=='ESCALATE')
            foreign_store=await admin.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 격리 매장','CAFE') returning store_id",seed['user_id'])
            await admin.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER')",foreign_store,seed['user_id'])
            foreign_token=create_token(dict(store_id=foreign_store,user_id=seed['user_id'],role='OWNER',exp=datetime.now(timezone.utc)+timedelta(minutes=5)))
            foreign_headers={'Authorization':'Bearer '+foreign_token}
            foreign_session=(await client.post('/learn/v2/sessions',headers=foreign_headers,json=dict(request_id='foreign-policy-session'))).json()['session_id']
            foreign_attempt=await client.post('/learn/v2/chat',headers=foreign_headers,json=dict(session_id=foreign_session,
                request_id='foreign-store-policy',question=safe_question,policy_receipt_id=rollback_id))
            check('policy confirmation cannot cross stores even without index',foreign_attempt.status_code==404)
            clarify=await chat("api-clarify-key",f"{title} 물 얼마나?")
            check("default planner CLARIFY",clarify.status_code==200 and clarify.json()["action"]=="CLARIFY")
            payload=clarify.json()
            restored=await client.get(f'/learn/v2/sessions/{session}/history',headers=headers)
            check('history restores clarification revision',restored.json()['messages'][-1]['context_revision']==int(clarify.headers['x-context-revision']))
            selected=await chat("api-clarify-selection",first.variant.temperature,context_id=payload["context_id"],
                context_revision=int(clarify.headers["x-context-revision"]),option=first.variant.temperature)
            check("clarification choice reaches ANSWER",selected.status_code==200 and selected.json()["action"]=="ANSWER")
            escalate=await chat("api-unknown-key","존재하지 않는 업무의 위치 알려줘")
            check("default planner ESCALATE persisted",escalate.status_code==200 and escalate.json()["action"]=="ESCALATE"
                  and bool(escalate.json()["pending_id"]))
            staff_uid=await admin.fetchval("insert into users(name,role) values('합성 직원','STAFF') returning user_id")
            await admin.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF')",seed['store_id'],staff_uid)
            staff_token=create_token(dict(store_id=seed['store_id'],user_id=staff_uid,role='STAFF',
                                          exp=datetime.now(timezone.utc)+timedelta(minutes=5)))
            staff_headers={'Authorization':'Bearer '+staff_token}
            export_path='/learn/v2/knowledge/export'
            check('export requires authentication',(await client.get(export_path)).status_code==401)
            check('staff cannot export approved knowledge',(await client.get(export_path,headers=staff_headers)).status_code==403)
            audit_before=await admin.fetchval("select count(*) from access_logs where store_id=$1 and action_type='EXPORT'",seed['store_id'])
            exported=await client.get(export_path,headers=headers)
            check('owner export preserves exact approved cards',exported.status_code==200 and
                exported.json()['cards']==[c.model_dump(mode='json') for c in seed['snapshot'].cards] and
                exported.headers['cache-control']=='no-store')
            check('export success commits audit',await admin.fetchval("select count(*) from access_logs where store_id=$1 and action_type='EXPORT'",seed['store_id'])==audit_before+1)
            excluded_card=seed['snapshot'].cards[0].card_id
            await admin.execute("update knowledge_cards set review_status='EXCLUDED' where store_id=$1 and card_id=$2",seed['store_id'],int(excluded_card))
            excluded_export=await client.get(export_path,headers=headers)
            check('export omits currently excluded card',excluded_export.status_code==200 and all(c['card_id']!=excluded_card for c in excluded_export.json()['cards']))
            await admin.execute("update knowledge_cards set review_status='APPROVED' where store_id=$1 and card_id=$2",seed['store_id'],int(excluded_card))
            denied_dictionary=await client.post('/learn/v2/search-dictionaries',headers=staff_headers,
                json=dict(entries=[dict(layer='STORE',term='커피',variants=['별명'])]))
            check('staff cannot approve search dictionary',denied_dictionary.status_code==403)
            denied_citation=await client.get(f'/learn/v2/receipts/{receipt}/citations/1',headers=staff_headers)
            check('citation cannot cross member',denied_citation.status_code==404)
            staff_session=(await client.post('/learn/v2/sessions',headers=staff_headers,
                json=dict(request_id='staff-session-key'))).json()['session_id']
            foreign_policy=await client.post('/learn/v2/chat',headers=staff_headers,json=dict(
                session_id=staff_session,request_id='foreign-policy-key',question=safe_question,policy_receipt_id=policy_receipts['SAFE_ROUTE']))
            check('policy confirmation cannot cross members',foreign_policy.status_code==404)
            other_session=(await client.post('/learn/v2/sessions',headers=headers,json=dict(request_id='other-policy-session'))).json()['session_id']
            wrong_session=await client.post('/learn/v2/chat',headers=headers,json=dict(
                session_id=other_session,request_id='wrong-policy-session',question=safe_question,policy_receipt_id=policy_receipts['SAFE_ROUTE']))
            check('policy confirmation cannot cross sessions',wrong_session.status_code==404)
            staff_question=await client.post('/learn/v2/chat',headers=staff_headers,json=dict(
                session_id=staff_session,request_id='staff-question-key',question='직원 합성 미확인 업무?'))
            pending_id=staff_question.json()['pending_id']
            forbidden=await client.get(f'/learn/v2/pending/{pending_id}',headers=staff_headers)
            check('staff cannot inspect owner pending detail',forbidden.status_code==403)
            detail=await client.get(f'/learn/v2/pending/{pending_id}',headers=headers)
            check('owner sees original occurrence context',detail.status_code==200 and
                detail.json()['occurrences'][0]['original_question']=='직원 합성 미확인 업무?')
            body=dict(request_id='owner-http-answer',answer='  점주 답변\n원문  ',expected_revision=0)
            forbidden=await client.post(f'/learn/v2/pending/{pending_id}/answers',headers=staff_headers,json=body)
            check('staff cannot submit owner answer',forbidden.status_code==403)
            delivered=await client.post(f'/learn/v2/pending/{pending_id}/answers',headers=headers,json=body)
            check('owner API commits delivery with pending knowledge',delivered.status_code==200 and
                delivered.json()['knowledge_status']=='PENDING' and delivered.json()['delivered_sessions']==1)
            repeated=await client.post(f'/learn/v2/pending/{pending_id}/answers',headers=headers,json=body)
            check('owner API idempotent',repeated.json()==delivered.json())
            history=await client.get(f'/learn/v2/sessions/{staff_session}/history',headers=staff_headers)
            check('staff history preserves owner original',history.status_code==200 and
                history.json()['messages'][-1]['content']==body['answer'] and
                history.json()['messages'][-1]['knowledge_status']=='PENDING')
            foreign=await client.get(f'/learn/v2/sessions/{staff_session}/history',headers=headers)
            check('history cannot cross member',foreign.status_code==404)
            notices=await client.get('/learn/v2/notifications',headers=staff_headers)
            nid=notices.json()['notifications'][0]['notification_id']
            check('staff app notification available without push',notices.status_code==200 and
                notices.json()['notifications'][0]['push_status']=='PENDING' and not notices.json()['notifications'][0]['read'])
            denied=await client.post(f'/learn/v2/notifications/{nid}/read',headers=headers)
            read=await client.post(f'/learn/v2/notifications/{nid}/read',headers=staff_headers)
            check('only recipient can mark notification read',denied.status_code==404 and read.status_code==200)
            read_at=await admin.fetchval('select read_at from notification_events where store_id=$1 and notification_id=$2',seed['store_id'],int(nid))
            read_again=await client.post(f'/learn/v2/notifications/{nid}/read',headers=staff_headers)
            check('notification read retry preserves first read time',read_again.status_code==200 and
                await admin.fetchval('select read_at from notification_events where store_id=$1 and notification_id=$2',seed['store_id'],int(nid))==read_at)
            foreign_notices=await client.get('/learn/v2/notifications',headers=foreign_headers)
            foreign_read=await client.post(f'/learn/v2/notifications/{nid}/read',headers=foreign_headers)
            check('notification list and read cannot cross stores',foreign_notices.json()['notifications']==[] and foreign_read.status_code==404)
            owner_notices=await client.get('/learn/v2/notifications',headers=headers)
            check('notification list cannot cross recipients',all(n['notification_id']!=nid for n in owner_notices.json()['notifications']))
            source=int(answer.json()['citations'][0]['source_id'])
            await admin.execute("update sources set source_availability='DELETED',deleted_at=now() where store_id=$1 and source_id=$2",seed['store_id'],source)
            overlay=await chat('api-real-answer',question)
            check('replay overlays current deleted source',overlay.json()['citations'][0]['source_availability']=='DELETED'
                and overlay.json()['message']==answer.json()['message'])
            await admin.execute("update sources set source_availability='AVAILABLE',deleted_at=null where store_id=$1 and source_id=$2",seed['store_id'],source)
            alias=await chat('api-alias-question','합성별칭 물 얼마나?')
            check('alias does not silently confirm entity',alias.status_code==200 and alias.json()['action']=='CLARIFY'
                and alias.json()['clarification_slot']=='entity' and title in alias.json()['allowed_options'])
            settings.r_reranker_enabled=True
            rank_calls=[]
            async def rank_sdk(**kwargs):
                evidence=json.loads(kwargs['contents'].split('\n',1)[1])
                rank_calls.append(1)
                return SimpleNamespace(text=json.dumps(dict(ids=[c['id'] for c in reversed(evidence['candidates'])])),
                    model_version='gemini-3.6-flash',response_id='synthetic-api-rank',
                    usage_metadata=SimpleNamespace(prompt_token_count=12,candidates_token_count=3,total_token_count=15))
            async def close_rank():pass
            sdk=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=rank_sdk),aclose=close_rank))
            with patch('google.genai.Client',return_value=sdk),patch('app.reg.reranker.get_settings',return_value=SimpleNamespace(
                    gemini_model='gemini-3.6-flash',gemini_api_key='synthetic-not-a-key')):
                ranked=await chat('api-reranked-answer',question)
                check('enabled reranker reaches validated ANSWER',ranked.status_code==200 and ranked.json()['action']=='ANSWER' and len(rank_calls)==1)
                rid=int(ranked.headers['x-answer-receipt-id'])
                check('API persists reranker applied status',await admin.fetchval("select execution_metadata->>'rerank_status' from r_answer_receipts where store_id=$1 and receipt_id=$2",seed['store_id'],rid)=='APPLIED')
                pending_before=await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])
                from app.usage.repository import UsageWriteError
                async def fail_start(*args):raise UsageWriteError('synthetic usage failure')
                with patch('app.reg.reranker._BoundedSink.start',fail_start):
                    failed_rank=await chat('api-rerank-usage-fail',question)
                check('reranker usage failure is API error before provider',failed_rank.status_code==503
                    and failed_rank.json()['error']['code']=='USAGE_UNAVAILABLE' and len(rank_calls)==1)
                check('reranker infrastructure error creates no pending',await admin.fetchval('select count(*) from pending_questions where store_id=$1',seed['store_id'])==pending_before)
            settings.r_reranker_enabled=False
            # The real default planner creates the grouping context. No injected
            # semantic dictionary or model judgment supplies the equivalence.
            absent_temp='HOT' if first.variant.temperature=='ICE' else 'ICE'
            grouped_a=await chat('api-group-explicit-a',f'{absent_temp} {title} 물 얼마나?')
            grouped_b=await chat('api-group-explicit-b',f'{title} {absent_temp} 물 양?')
            check('explicit equivalent questions share pending through real planner',
                grouped_a.status_code==grouped_b.status_code==200
                and grouped_a.json()['action']==grouped_b.json()['action']=='ESCALATE'
                and grouped_a.json()['pending_id']==grouped_b.json()['pending_id'])
            group_id=int(grouped_a.json()['pending_id'])
            check('group keeps both original occurrences',await admin.fetchval('''
                select count(*) from pending_question_occurrences o
                join pending_questions p on p.question_id=o.question_id
                where p.store_id=$1 and p.question_id=$2''',seed['store_id'],group_id)==2)
            check('group emits one pending event',await admin.fetchval('''
                select count(*) from notification_events where store_id=$1
                and aggregate_id=$2 and event_type='PENDING_QUESTION' ''',seed['store_id'],group_id)==1)
            compound=await chat('api-quantity-extra-condition',f'{first.variant.temperature} {title} 물 두 배로 얼마나?')
            check('extra quantity condition cannot return base answer or join simple question',
                compound.status_code==200 and compound.json()['action']=='ESCALATE'
                and compound.json()['pending_id']!=str(group_id))
            from verify_r_v2_evaluation import verify as verify_evaluation
            await verify_evaluation(client,admin,seed,headers,question,title)
            wrong=await client.post(
                "/learn/v2/chat",headers=headers,json=dict(request_id="api-wrong-session",session_id="999999",question="질문"))
            check("unknown session returns 404",wrong.status_code==404)
            from app.team.evaluation_usage import evaluation_usage_scope
            from app.team.semantic_shadow import semantic_shadow_scope
            shadow_rows=[]
            async def record_shadow(row): shadow_rows.append(row)
            async def proposal_provider(prompt,**kwargs):
                data=json.loads(prompt.split('\n',1)[1])
                return dict(input_hash=data['input_hash'],snapshot_hash=data['snapshot_hash'],
                    plan=dict(snapshot_id=data['snapshot_id'],knowledge_revision=data['knowledge_revision'],
                        action='ESCALATE',escalation_reason='SYNTHETIC_UNCERTAINTY'))
            with evaluation_usage_scope(store_id=seed['store_id'],evaluation_run_id='1'):
                with semantic_shadow_scope(store_id=seed['store_id'],record=record_shadow,provider=proposal_provider):
                    observed=await chat('api-semantic-shadow',title+' 승인 원문 보여줘')
                    replay=await chat('api-semantic-shadow',title+' 승인 원문 보여줘')
            check('semantic shadow observes actual HTTP baseline without changing answer',
                observed.status_code==200 and observed.json()['action']=='ANSWER' and
                len(shadow_rows)==1 and shadow_rows[0]['proposal']['plan']['action']=='ESCALATE' and
                shadow_rows[0]['baseline_plan']['action']=='ANSWER' and not shadow_rows[0]['production_eligible'])
            check('semantic shadow replay does not call provider again',replay.headers.get('x-answer-replayed')=='true')
            settings.r_v2_enabled=False
            disabled=await chat("api-disabled-key",question)
            check("rollout flag disables v2 explicitly",disabled.status_code==503 and disabled.json()["error"]["code"]=="V2_UNAVAILABLE")
    print(f"Verified {len(passed)} v2 API checks")
