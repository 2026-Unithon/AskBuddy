"""v2 chat: JWT scope → immutable index → server plan → atomic receipt.

첫 rollout은 명시 슬롯 planner다. 미지원 RAW/조건 의미는 추정 승인하지 않는다.
"""
from __future__ import annotations
import asyncio
import json
import logging
import asyncpg
from dataclasses import replace,asdict
from uuid import UUID,uuid4

from fastapi import APIRouter,HTTPException,Request,Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field,model_validator

from app.config import get_settings
from app.contracts.common import Contract,EntityId,RawText
from app.contracts.hashing import digest
from app.contracts.usage import UsageContext
from app.deps import Claims,CurrentUserId,get_pool,get_store_id
from app.errors import ApiError
from app.learn.answer_storage import ContextChoice,save_answer,saved_reply,current_source_overlay,validate_policy_confirmation
from app.contracts.answer import AnswerPlan
from app.contracts.chat import ChatResponse
from app.contracts.snapshot import KnowledgeContent
from app.learn.planner import decide,policy_action,PLANNER_VERSION
from app.learn.question_contexts import load_context,accept_selection
from app.learn.request_limits import request_lease
from app.learn.owner_delivery import require_owner,submit_owner_answer
from app.learn.owner_handoff import retry_owner_event
from app.reg.embeddings import recorded_embeddings
from app.team.evaluation_budget import BudgetDenied
from app.reg.hybrid import SearchResult,hybrid_search,read_current_index,NORMALIZATION_VERSION,RRF_VERSION,LEXICAL_QUERY_VERSION
from app.reg.reranker import rerank
from app.reg.lexicon import LexiconEntry,approve_lexicon
from app.learn.knowledge_export import export_approved_knowledge
from app.team.evaluation_usage import request_usage_sink
from app.usage.repository import UsageWriteError


class V2Route(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def handler(request:Request):
            try:
                return await original(request)
            except (ApiError,HTTPException,RequestValidationError) as exc:
                status=exc.status_code if not isinstance(exc,RequestValidationError) else 422
                code=exc.code if isinstance(exc,ApiError) else {
                    401:"AUTH_REQUIRED",403:"FORBIDDEN",404:"NOT_FOUND"}.get(status,"INVALID_CONTRACT")
                message=exc.message if isinstance(exc,ApiError) else "요청 또는 현재 접근 권한을 확인해 주세요."
                body=dict(code=code,message=message,retryable=getattr(exc,"retryable",False),
                          request_id=getattr(request.state,"r_request_id",uuid4().hex))
                if isinstance(exc,ApiError) and code=="RATE_LIMITED":
                    body["retry_after_ms"]=exc.details.get("retry_after_ms",60000)
                return JSONResponse(status_code=status,content=dict(contract_version="v2",error=body))
            except Exception as exc:
                logging.getLogger(__name__).error("v2 request failed type=%s",type(exc).__name__)
                database=isinstance(exc,asyncpg.PostgresError)
                return JSONResponse(status_code=503 if database else 500,content=dict(contract_version="v2",
                    error=dict(code="STORAGE_FAILED" if database else "INTERNAL_ERROR",
                        message="요청을 완료하지 못했습니다.",retryable=database,
                        request_id=getattr(request.state,"r_request_id",uuid4().hex))))
        return handler


router=APIRouter(route_class=V2Route)


@router.get('/v2/receipts/{receipt_id}/citations/{order}')
async def citation_detail(receipt_id:EntityId,order:int,claims:Claims,user_id:CurrentUserId):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""select c.*,i.content,s.source_availability
                from r_answer_receipts r join store_members m on m.store_id=r.store_id and m.member_id=r.member_id
                join r_answer_citations c on c.store_id=r.store_id and c.receipt_id=r.receipt_id
                join r_index_publications p on p.store_id=r.store_id and p.snapshot_id=r.snapshot_id
                join r_index_preparations i on i.store_id=p.store_id and i.prepared_id=p.prepared_id
                left join sources s on s.store_id=c.store_id and s.source_id=c.source_id
                where r.store_id=$1 and r.member_id=$2 and r.receipt_id=$3 and c.citation_order=$4
                for share of m""",store_id,member_id,int(receipt_id),order)
            if row is None:raise ApiError(404,'NOT_FOUND','인용을 찾을 수 없습니다.')
            content=KnowledgeContent.model_validate_json(row['content']) if isinstance(row['content'],str) else KnowledgeContent.model_validate(row['content'])
            card=next(c for c in content.cards if c.card_id==str(row['card_id']) and c.card_version_id==str(row['card_version_id']))
            if row['raw_span_id']:
                text=next(r.text for r in content.raw_spans if r.raw_span_id==str(row['raw_span_id']))
            else:
                fact=next(f for f in content.fact_revisions if f.fact_revision_id==str(row['fact_revision_id']))
                text='\n'.join((fact.assertion,*fact.conditions,*fact.exceptions))
            await conn.execute("insert into access_logs(store_id,user_id,card_id,action_type) values($1,$2,$3,'VIEW')",store_id,user_id,row['card_id'])
            return dict(contract_version='v2',title=card.title,text=text,card_version_id=card.card_version_id,
                        source_availability=row['source_availability'] or 'UNAVAILABLE')


@router.get('/v2/sessions')
async def sessions(claims:Claims,user_id:CurrentUserId):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        rows=await conn.fetch("""select s.session_id from chat_sessions s join store_members m
            on m.store_id=s.store_id and m.member_id=s.member_id where s.store_id=$1 and s.member_id=$2
            and s.contract_version='v2' order by s.session_id desc limit 100""",store_id,member_id)
        return dict(contract_version='v2',sessions=[dict(session_id=str(r['session_id'])) for r in rows])


@router.get('/v2/pending')
async def pending_list(claims:Claims,user_id:CurrentUserId,after:EntityId|None=None):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_owner(conn,store_id=store_id,member_id=member_id)
            rows=await conn.fetch("""select question_id,question_text,status from pending_questions
                where store_id=$1 and contract_version='v2' and question_id>$2 order by question_id limit 100""",
                store_id,int(after) if after else 0)
            await conn.execute("insert into access_logs(store_id,user_id,action_type) values($1,$2,'VIEW')",store_id,user_id)
            return dict(contract_version='v2',questions=[dict(pending_id=str(r['question_id']),
                question=r['question_text'],status=r['status']) for r in rows],
                next_after=str(rows[-1]['question_id']) if len(rows)==100 else None)


class SessionRequest(Contract):
    request_id:str=Field(min_length=8,max_length=80)


class DictionaryRequest(Contract):
    entries:tuple[LexiconEntry,...]=Field(max_length=500)


@router.post('/v2/search-dictionaries')
async def approve_dictionary(req:DictionaryRequest,claims:Claims,user_id:CurrentUserId):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    try:version=await approve_lexicon(pool,store_id=store_id,member_id=member_id,entries=req.entries)
    except ValueError as exc:raise ApiError(422,'INVALID_CONTRACT','중복되거나 모호한 별칭을 확인해 주세요.') from exc
    return dict(contract_version='v2',glossary_version=version,activation='NEXT_APPROVED_SNAPSHOT')


class ChatRequest(SessionRequest):
    session_id:EntityId
    question:RawText=Field(min_length=1,max_length=1000)
    context_id:UUID|None=None
    context_revision:int|None=Field(default=None,ge=1)
    option:str|None=Field(default=None,min_length=1,max_length=1000)
    policy_receipt_id:EntityId|None=None

    @model_validator(mode="after")
    def complete_choice(self):
        flags=[self.context_id is not None,self.context_revision is not None,self.option is not None]
        if any(flags) and not all(flags):raise ValueError("context choice fields must be supplied together")
        if self.policy_receipt_id is not None and any(flags):raise ValueError('policy confirmation cannot select context')
        if not self.question.strip():raise ValueError("empty question")
        if self.option is not None and self.question.strip()!=self.option:
            raise ValueError("choice turn must contain the selected option only")
        return self


class OwnerAnswerRequest(SessionRequest):
    answer:RawText=Field(min_length=1,max_length=10000)
    expected_revision:int=Field(ge=0)


class OwnerRetryRequest(SessionRequest):
    reason:str=Field(min_length=1,max_length=300)


@router.post('/v2/owner-events/{event_id}/retry')
async def owner_retry(event_id:EntityId,req:OwnerRetryRequest,request:Request,claims:Claims,user_id:CurrentUserId):
    request.state.r_request_id=req.request_id
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    return await retry_owner_event(pool,store_id=store_id,member_id=member_id,event_id=int(event_id),
        request_id=req.request_id,reason=req.reason)


@router.post("/v2/pending/{question_id}/answers")
async def owner_answer(question_id:EntityId,req:OwnerAnswerRequest,request:Request,
                       claims:Claims,user_id:CurrentUserId):
    request.state.r_request_id=req.request_id
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    return await submit_owner_answer(pool,store_id=store_id,member_id=member_id,
        question_id=int(question_id),request_id=req.request_id,answer=req.answer,
        expected_revision=req.expected_revision)


@router.get("/v2/pending/{question_id}")
async def pending_detail(question_id:EntityId,claims:Claims,user_id:CurrentUserId):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_owner(conn,store_id=store_id,member_id=member_id)
            pending=await conn.fetchrow("""select question_id,status from pending_questions
                where store_id=$1 and question_id=$2 and contract_version='v2'""",store_id,int(question_id))
            if pending is None:raise ApiError(404,"NOT_FOUND","질문을 찾을 수 없습니다.")
            occurrences=await conn.fetch("""select receipt_id,original_question,resolved_query,context_snapshot
                from r_answer_receipts where store_id=$1 and pending_id=$2 order by receipt_id""",store_id,int(question_id))
            answers=await conn.fetch("""select a.answer_id,a.answer_text,r.revision_no,k.status as knowledge_status,
                    e.event_id,l.attempts,l.last_error
                from r_owner_answer_revisions r join owner_answers a on a.answer_id=r.owner_answer_id
                join r_owner_knowledge_states k on k.store_id=r.store_id and k.owner_answer_id=r.owner_answer_id
                left join outbox_events e on e.store_id=r.store_id and e.owner_answer_id=r.owner_answer_id
                    and e.event_type='OWNER_ANSWER_SUBMITTED'
                left join outbox_leases l on l.store_id=e.store_id and l.event_id=e.event_id and l.consumer='W_OWNER_ANSWER_V2'
                where r.store_id=$1 and r.question_id=$2 order by r.revision_no""",store_id,int(question_id))
            await conn.execute("insert into access_logs(store_id,user_id,action_type) values($1,$2,'VIEW')",store_id,user_id)
            return dict(contract_version="v2",pending_id=str(pending['question_id']),status=pending['status'],
                occurrences=[dict(receipt_id=str(r['receipt_id']),original_question=r['original_question'],
                    resolved_query=json.loads(r['resolved_query']) if isinstance(r['resolved_query'],str) else r['resolved_query'],
                    context_snapshot=json.loads(r['context_snapshot']) if isinstance(r['context_snapshot'],str) else r['context_snapshot']) for r in occurrences],
                answers=[dict(owner_answer_id=str(r['answer_id']),answer=r['answer_text'],revision=r['revision_no'],
                    knowledge_status=r['knowledge_status'],event_id=str(r['event_id']) if r['event_id'] else None,
                    attempts=r['attempts'] or 0,retry_available=(r['last_error'] or '').startswith('TERMINAL:')) for r in answers])


@router.get("/v2/sessions/{session_id}/history")
async def history(session_id:EntityId,claims:Claims,user_id:CurrentUserId,
                  after:EntityId|None=None,limit:int=Query(default=100,ge=1,le=100)):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    from app.learn.question_contexts import _lock_session
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _lock_session(conn,store_id=store_id,member_id=member_id,session_id=int(session_id))
            rows=await conn.fetch("""select m.message_id,m.sender_type,m.content,m.owner_answer_id,
                r.response,r.receipt_id,r.original_question,r.context_snapshot,k.status as knowledge_status,rev.revision_no
                from chat_messages m join chat_sessions s on s.session_id=m.session_id
                left join r_answer_receipts r on r.store_id=s.store_id and r.buddy_message_id=m.message_id
                left join r_owner_knowledge_states k on k.store_id=s.store_id and k.owner_answer_id=m.owner_answer_id
                left join r_owner_answer_revisions rev on rev.store_id=s.store_id and rev.owner_answer_id=m.owner_answer_id
                where s.store_id=$1 and s.member_id=$2 and s.session_id=$3 and m.message_id>$4
                order by m.message_id limit $5""",
                store_id,member_id,int(session_id),int(after) if after else 0,limit)
            responses={}
            for row in rows:
                if row['response']:
                    response=ChatResponse.model_validate_json(row['response']) if isinstance(row['response'],str) else ChatResponse.model_validate(row['response'])
                    responses[row['message_id']]=(await current_source_overlay(conn,store_id=store_id,response=response)).model_dump(mode='json')
            await conn.execute("insert into access_logs(store_id,user_id,action_type) values($1,$2,'VIEW')",store_id,user_id)
            return dict(contract_version="v2",session_id=session_id,messages=[dict(
                message_id=str(r['message_id']),sender=r['sender_type'],content=r['content'],
                receipt_id=str(r['receipt_id']) if r['receipt_id'] else None,
                original_question=r['original_question'],
                owner_answer_id=str(r['owner_answer_id']) if r['owner_answer_id'] else None,
                revision=r['revision_no'],knowledge_status=r['knowledge_status'],
                context_revision=(json.loads(r['context_snapshot']) if isinstance(r['context_snapshot'],str) else r['context_snapshot'] or {}).get('state_revision'),
                response=responses.get(r['message_id'])) for r in rows],
                next_after=str(rows[-1]['message_id']) if len(rows)==limit else None)


@router.get("/v2/notifications")
async def notifications(claims:Claims,user_id:CurrentUserId,after:EntityId|None=None):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        rows=await conn.fetch("""select n.notification_id,n.title,n.body,n.destination,n.status,n.read_at
            from notification_events n join store_members m on m.store_id=n.store_id and m.user_id=n.recipient_user_id
            where n.store_id=$1 and m.member_id=$2 and n.recipient_user_id=$3 and n.notification_id>$4
            order by n.notification_id limit 100""",store_id,member_id,user_id,int(after) if after else 0)
        return dict(contract_version='v2',notifications=[dict(notification_id=str(r['notification_id']),
            title=r['title'],body=r['body'],destination=r['destination'],push_status=r['status'],
            read=r['read_at'] is not None) for r in rows],
            next_after=str(rows[-1]['notification_id']) if len(rows)==100 else None)


@router.post("/v2/notifications/{notification_id}/read")
async def read_notification(notification_id:EntityId,claims:Claims,user_id:CurrentUserId):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        found=await conn.fetchval("""update notification_events n set read_at=coalesce(n.read_at,now())
            where n.store_id=$1 and n.recipient_user_id=$2 and n.notification_id=$3
            and exists(select 1 from store_members m where m.store_id=n.store_id and m.user_id=n.recipient_user_id and m.member_id=$4)
            returning n.notification_id""",store_id,user_id,int(notification_id),member_id)
        if found is None:raise ApiError(404,'NOT_FOUND','알림을 찾을 수 없습니다.')
        return dict(contract_version='v2',notification_id=str(found),read=True)


def enabled():
    if not get_settings().r_v2_enabled:
        raise ApiError(503,"V2_UNAVAILABLE","새 답변 경로가 아직 활성화되지 않았습니다.")


# store-isolation-ok: JWT로 store를 확정하고 현재 membership을 검사하는 인증 경계다.
async def scope(pool,claims,user_id):
    async with pool.acquire() as conn:
        store_id=await get_store_id(claims,conn)
        member_id=await conn.fetchval("select member_id from store_members where store_id=$1 and user_id=$2",store_id,user_id)
    if member_id is None:raise ApiError(403,"FORBIDDEN","현재 매장 회원 권한이 필요합니다.")
    return store_id,member_id


@router.post("/v2/sessions")
async def create_session(req:SessionRequest,request:Request,claims:Claims,user_id:CurrentUserId):
    request.state.r_request_id=req.request_id
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",f"r:session:{store_id}:{member_id}:{req.request_id}")
            member=await conn.fetchval("select member_id from store_members where store_id=$1 and member_id=$2 for share",store_id,member_id)
            if member is None:raise ApiError(403,"FORBIDDEN","현재 회원 권한이 필요합니다.")
            row=await conn.fetchrow("""select response from operations where store_id=$1 and member_id=$2
                and operation='R_V2_SESSION' and idempotency_key=$3""",store_id,member_id,req.request_id)
            if row:
                return json.loads(row["response"]) if isinstance(row["response"],str) else row["response"]
            session=await conn.fetchval("""insert into chat_sessions(store_id,member_id,contract_version)
                values($1,$2,'v2') returning session_id""",store_id,member_id)
            result=dict(contract_version="v2",session_id=str(session))
            await conn.execute("""insert into operations(store_id,member_id,operation,idempotency_key,body_hash,status,response,finished_at)
                values($1,$2,'R_V2_SESSION',$3,$4,'SUCCEEDED',$5::jsonb,now())""",
                store_id,member_id,req.request_id,digest(dict(contract_version="v2")),json.dumps(result))
    return result


@router.get('/v2/knowledge/export')
async def export_knowledge(claims:Claims,user_id:CurrentUserId):
    enabled()
    pool=get_pool()
    store_id,member_id=await scope(pool,claims,user_id)
    try:
        async with request_lease(pool,store_id,user_id):
            async with asyncio.timeout(get_settings().chat_deadline_seconds):
                payload=await export_approved_knowledge(pool,store_id=store_id,member_id=member_id)
    except TimeoutError as exc:
        raise ApiError(504,'DEADLINE_EXCEEDED','내보내기 처리 시간이 초과되었습니다.',retryable=True) from exc
    return JSONResponse(content=payload,headers={'Cache-Control':'no-store',
        'Content-Disposition':'attachment; filename="approved-knowledge.json"'})


@router.post("/v2/chat")
async def chat(req:ChatRequest,request:Request,claims:Claims,user_id:CurrentUserId):
    request.state.r_request_id=req.request_id
    enabled()
    pool=get_pool()
    settings=get_settings()
    loop=asyncio.get_running_loop()
    deadline=loop.time()+settings.chat_deadline_seconds
    stale=False
    completed=None
    choice=ContextChoice(req.context_id,req.context_revision,req.option) if req.context_id else None
    try:
        async with asyncio.timeout_at(deadline):
            store_id,member_id=await scope(pool,claims,user_id)
            async with request_lease(pool,store_id,user_id):
                completed=await saved_reply(pool,store_id=store_id,member_id=member_id,session_id=int(req.session_id),
                    request_id=req.request_id,question=req.question,choice=choice,policy_receipt_id=req.policy_receipt_id)
                if completed is None:
                    for requery in range(2):
                        usage=None
                        async with pool.acquire() as conn:
                            async with conn.transaction():
                                context=None
                                if req.policy_receipt_id is not None:
                                    await validate_policy_confirmation(conn,store_id=store_id,member_id=member_id,
                                        session_id=int(req.session_id),policy_receipt_id=req.policy_receipt_id,question=req.question)
                                snapshot,_,index_revision=await read_current_index(conn,store_id=store_id)
                                if choice:
                                    stored=await load_context(conn,store_id=store_id,member_id=member_id,
                                        session_id=int(req.session_id),context_id=choice.context_id)
                                    context=accept_selection(stored,option=choice.option,
                                        expected_state_revision=choice.state_revision,
                                        knowledge_revision=int(snapshot.knowledge_revision),
                                        now=await conn.fetchval("select clock_timestamp()"))
                        question=req.question
                        slots={}
                        if context:
                            slots=context.context.confirmed_slots
                            question=context.context.original_question+" "+req.question
                        if req.policy_receipt_id is not None or policy_action(question):
                            search=SearchResult(snapshot,index_revision,(),question)
                        else:
                            remaining=min(deadline-loop.time()-settings.chat_save_reserve_seconds,
                                settings.llm_total_budget_seconds-(loop.time()-(deadline-settings.chat_deadline_seconds)))
                            if remaining<=0:raise TimeoutError()
                            usage=UsageContext(store_id=str(store_id),cost_phase="OPERATING",stage="QUERY",
                                operation_id=digest(dict(member_id=member_id,request_id=req.request_id)),
                                logical_call_id="v2:"+digest(dict(member_id=member_id,request_id=req.request_id))[7:]+f":q{requery}")
                            try:
                                vectors=await asyncio.wait_for(recorded_embeddings([question],context=usage,sink=request_usage_sink(pool,store_id=store_id)),
                                    timeout=min(settings.search_deadline_seconds,remaining))
                            except (TimeoutError,BudgetDenied):raise
                            except UsageWriteError as exc:
                                raise ApiError(503,"USAGE_UNAVAILABLE","검색 계측을 시작하지 못했습니다.",retryable=True) from exc
                            except Exception as exc:
                                raise ApiError(503,"MODEL_UNAVAILABLE","질문 검색을 완료하지 못했습니다.",retryable=True) from exc
                            search=await hybrid_search(pool,store_id=store_id,question=question,query_vector=vectors[0])
                            if getattr(settings,'r_reranker_enabled',False):
                                remaining=min(deadline-loop.time()-settings.chat_save_reserve_seconds,
                                    settings.llm_total_budget_seconds-(loop.time()-(deadline-settings.chat_deadline_seconds)))
                                rank_context=usage.model_copy(update=dict(stage='RERANK',logical_call_id=usage.logical_call_id+':rank'))
                                try:
                                    search=await rerank(search,store_id=store_id,question=question,context=rank_context,
                                        sink=request_usage_sink(pool,store_id=store_id),timeout=remaining)
                                except UsageWriteError as exc:
                                    raise ApiError(503,'USAGE_UNAVAILABLE','재정렬 계측을 시작하지 못했습니다.',retryable=True) from exc
                        decision=decide(search,store_id=store_id,question=question,confirmed_slots=slots,
                            context_id=choice.context_id if choice else None,
                            context_verified=context is not None,
                            clarify_turns=context.context.clarify_turns if context else 0)
                        if req.policy_receipt_id is not None:
                            decision=replace(decision,plan=AnswerPlan(snapshot_id=search.snapshot.snapshot_id,
                                knowledge_revision=search.snapshot.knowledge_revision,action='ESCALATE',
                                escalation_reason='USER_REQUESTED_SAFETY_CONFIRMATION'))
                        from app.learn.reviewed_semantics import product_decision
                        semantic_approval=None
                        if req.policy_receipt_id is None:
                            decision,semantic_approval=product_decision(search,settings=settings,
                                store_id=store_id,question=question,baseline=decision,
                                user_turns=(context.context.original_question,req.question) if context else (),
                                context_id=choice.context_id if choice else None,context_verified=context is not None,
                                clarify_turns=context.context.clarify_turns if context else 0)
                        from app.learn.general_semantics import general_decision
                        general_audit=None
                        if req.policy_receipt_id is None and usage is not None:
                            decision,general_audit=await general_decision(search,settings=settings,
                                store_id=store_id,question=question,user_turns=(context.context.original_question,req.question) if context else (),
                                baseline=decision,context=usage.model_copy(update={'stage':'ANSWER'}),
                                sink=request_usage_sink(pool,store_id=store_id),timeout=max(0,min(
                                    deadline-loop.time()-settings.chat_save_reserve_seconds,
                                    settings.llm_total_budget_seconds-(loop.time()-(deadline-settings.chat_deadline_seconds)))),
                                context_verified=context is not None,context_id=choice.context_id if choice else None,
                                clarify_turns=context.context.clarify_turns if context else 0)
                        if stale and decision.plan.action=="ESCALATE":
                            raise ApiError(409,"STALE_KNOWLEDGE","변경된 근거로 답변을 확정하지 못했습니다.",retryable=True)
                        from app.team.semantic_shadow import observe_decision
                        await observe_decision(pool=pool,store_id=store_id,search=search,question=question,
                            user_turns=(context.context.original_question,req.question) if context else (),
                            baseline=decision,request_id=req.request_id,
                            timeout=max(0,deadline-loop.time()-settings.chat_save_reserve_seconds))
                        await scope(pool,claims,user_id)
                        try:
                            completed=await save_answer(pool,store_id=store_id,member_id=member_id,session_id=int(req.session_id),
                                request_id=req.request_id,question=req.question,snapshot=search.snapshot,plan=decision.plan,
                                resolved=decision.resolved,confirmed_slots=decision.confirmed_slots,
                                semantic_context=decision.semantic_context,choice=choice,
                                policy_receipt_id=req.policy_receipt_id,
                                execution_metadata=dict(planner_version=PLANNER_VERSION,normalization_version=NORMALIZATION_VERSION,
                                    semantic_approval_id=semantic_approval,
                                    general_semantics=general_audit,
                                    semantic_catalog_hash=getattr(settings,'r_reviewed_semantics_hash','') if semantic_approval else None,
                                    usage_operation_id=usage.operation_id if usage else None,
                                    query_logical_call_id=usage.logical_call_id if usage else None,
                                    rerank_logical_call_id=usage.logical_call_id+':rank' if usage and getattr(settings,'r_reranker_enabled',False) else None,
                                    elapsed_before_save_ms=round((loop.time()-(deadline-settings.chat_deadline_seconds))*1000,3),
                                    rrf_version=RRF_VERSION,lexical_query_version=LEXICAL_QUERY_VERSION,
                                    glossary_version=search.snapshot.glossary_version,alias_terms_hash=digest(search.alias_terms),
                                    index_revision=search.index_revision,rerank_status=search.rerank_status,
                                    candidates=[asdict(c) for c in search.candidates]))
                            break
                        except ApiError as exc:
                            if exc.code!="STALE_KNOWLEDGE":raise
                            stale=True
                            if requery:raise
                # commit한 응답은 lease 정리 timeout 때문에 실패로 뒤집지 않는다.
    except BudgetDenied as exc:
        raise ApiError(429,'EVALUATION_BUDGET_DENIED','평가 예산을 확인하거나 추가 실행 승인이 필요합니다.',retryable=False) from exc
    except TimeoutError as exc:
        if completed is None:
            raise ApiError(409 if stale else 504,"STALE_KNOWLEDGE" if stale else "DEADLINE_EXCEEDED",
                           "처리 시간 안에 공개 내용을 확인하지 못했습니다.",retryable=True) from exc
    except ApiError as exc:
        if stale and exc.code=="INDEX_UNAVAILABLE":
            raise ApiError(409,"STALE_KNOWLEDGE","공개 내용이 변경됐습니다.",retryable=True) from exc
        raise
    assert completed is not None
    headers={"X-Answer-Receipt-Id":completed.receipt_id,"X-Answer-Replayed":str(completed.replayed).lower()}
    if completed.context_revision is not None:headers["X-Context-Revision"]=str(completed.context_revision)
    return JSONResponse(content=completed.response.model_dump(mode="json"),headers=headers)
