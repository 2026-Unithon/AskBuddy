"""v2 참조 답변의 현재 공개 검사·멱등 receipt·문맥·pending 원자 저장.

신뢰된 서버 planner 호출용 서비스다. 모델 출력이나 HTTP body를 그대로 넘기지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.contracts.answer import AnswerPlan
from app.contracts.chat import ChatResponse
from app.contracts.hashing import digest, verify_snapshot_hash
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.errors import ApiError
from app.learn.answer_validation import ResolvedSelection,validate_answer_for_question
from app.learn.approved_renderer import render
from app.learn.question_contexts import (
    _lock_session,accept_context,create_context,offer_next_context,
)
from app.notifications.service import create_pending_question_notification
from app.learn.semantic_grouping import explicit_key, explicit_context


@dataclass(frozen=True)
class ContextChoice:
    context_id: UUID
    state_revision: int
    option: str


@dataclass(frozen=True)
class StoredReply:
    response: ChatResponse
    receipt_id: str
    replayed: bool
    context_revision:int|None=None


def pending_key(*, store_id: int, semantic_context: dict | None) -> str:
    if isinstance(semantic_context,dict) and "version" in semantic_context:
        key=explicit_key(store_id=store_id,context=semantic_context)
        return key or digest(dict(store_id=store_id,version="r-semantic/invalid",occurrence=str(uuid4())))
    required={"entity","predicate","variant","conditions","policy_scope"}
    variant=(semantic_context or {}).get("variant")
    variant_known=(isinstance(variant,dict) and (
        (variant.get("scope")=="SPECIFIC" and
         (variant.get("temperature") in ("HOT","ICE") or bool(variant.get("size"))))
        or (variant.get("scope")=="NOT_APPLICABLE" and bool(variant.get("evidence")))))
    # 불명확한 문맥은 합치지 않는다. 서버가 완전히 확정한 결과만 묶는다.
    if (semantic_context is None or set(semantic_context)!=required
            or any(semantic_context[k] is None for k in required)
            or not semantic_context["entity"] or not semantic_context["predicate"]
            or not semantic_context["policy_scope"] or not variant_known):
        return digest(dict(store_id=store_id,version="r-semantic/v1",occurrence=str(uuid4())))
    return digest(dict(store_id=store_id,version="r-semantic/v1",**semantic_context))


async def _receipt(conn, *, store_id: int,member_id: int,request_id: str,body_hash: str):
    row=await conn.fetchrow("""select receipt_id,body_hash,response,context_snapshot,
        created_at+interval '24 hours' > clock_timestamp() as cached
        from r_answer_receipts where store_id=$1 and member_id=$2 and request_id=$3""",
        store_id,member_id,request_id)
    if row is None:
        return None
    if row["body_hash"]!=body_hash:
        raise ApiError(409,"IDEMPOTENCY_CONFLICT","같은 요청 키에 다른 본문을 사용할 수 없습니다.")
    if not row["cached"]:
        raise ApiError(409,"IDEMPOTENCY_CONFLICT","응답 재시도 기간이 지났습니다. 이력에서 확인해 주세요.")
    payload=json.loads(row["response"]) if isinstance(row["response"],str) else row["response"]
    context=json.loads(row["context_snapshot"]) if isinstance(row["context_snapshot"],str) else row["context_snapshot"]
    response=await current_source_overlay(conn,store_id=store_id,response=ChatResponse.model_validate(payload))
    return StoredReply(response,str(row["receipt_id"]),True,
                       context.get("state_revision") if context and payload["action"]=="CLARIFY" else None)


async def current_source_overlay(conn,*,store_id:int,response:ChatResponse) -> ChatResponse:
    """인용 내용·버전은 보존하고 현재 원본 열람 상태만 조회 시점에 덧입힌다(D20)."""
    ids=sorted({int(c.source_id) for c in response.citations})
    if not ids:return response
    rows=await conn.fetch("select source_id,source_availability from sources where store_id=$1 and source_id=any($2::bigint[])",store_id,ids)
    availability={str(r['source_id']):r['source_availability'] for r in rows}
    payload=response.model_dump(mode='json')
    for citation in payload['citations']:
        citation['source_availability']=availability.get(citation['source_id'],'UNAVAILABLE')
    return ChatResponse.model_validate(payload)


def request_body_hash(*,session_id: int,question: str,choice: ContextChoice | None,policy_receipt_id:str|None=None):
    body=dict(session_id=session_id,question=question,choice=None if choice is None else
        dict(context_id=str(choice.context_id),state_revision=choice.state_revision,option=choice.option))
    # 기존 요청의 hash는 바꾸지 않는다.
    if policy_receipt_id is not None:body['policy_receipt_id']=policy_receipt_id
    return digest(body)


async def validate_policy_confirmation(conn,*,store_id:int,member_id:int,session_id:int,
                                       policy_receipt_id:str,question:str):
    row=await conn.fetchrow("""select original_question,response from r_answer_receipts
        where store_id=$1 and member_id=$2 and session_id=$3 and receipt_id=$4""",
        store_id,member_id,session_id,int(policy_receipt_id))
    if row is None:raise ApiError(404,'NOT_FOUND','확인할 안전 안내를 찾을 수 없습니다.')
    response=ChatResponse.model_validate_json(row['response']) if isinstance(row['response'],str) else ChatResponse.model_validate(row['response'])
    if response.action!='SAFE_ROUTE' or row['original_question']!=question:
        raise ApiError(422,'INVALID_CONTRACT','안전 안내의 원래 질문만 확인 요청할 수 있습니다.')
    previous=await conn.fetchval("""select receipt_id from r_answer_receipts
        where store_id=$1 and member_id=$2 and session_id=$3
        and execution_metadata->>'policy_receipt_id'=$4 limit 1""",
        store_id,member_id,session_id,policy_receipt_id)
    if previous is not None:
        raise ApiError(409,'IDEMPOTENCY_CONFLICT','이미 확인을 요청했습니다. 대화 이력을 확인해 주세요.')


async def saved_reply(pool,*,store_id:int,member_id:int,session_id:int,request_id:str,
                      question:str,choice:ContextChoice|None=None,policy_receipt_id:str|None=None):
    """현재 회원/세션을 재확인하고 모델 호출 전에 원래 결과를 재조회한다."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _lock_session(conn,store_id=store_id,member_id=member_id,session_id=session_id)
            return await _receipt(conn,store_id=store_id,member_id=member_id,request_id=request_id,
                body_hash=request_body_hash(session_id=session_id,question=question,choice=choice,policy_receipt_id=policy_receipt_id))


async def save_answer(pool,*,store_id:int,member_id:int,session_id:int,request_id:str,
                      question:str,snapshot:PublishedKnowledgeSnapshot,plan:AnswerPlan,
                      resolved:ResolvedSelection,confirmed_slots:dict[str,str],
                      semantic_context:dict|None=None,choice:ContextChoice|None=None,
                      execution_metadata:dict|None=None,policy_receipt_id:str|None=None) -> StoredReply:
    if (not 8<=len(request_id)<=80 or not question.strip() or len(question)>1000
            or (choice is None and resolved.question!=question)):
        raise ApiError(422,"INVALID_CONTRACT","질문과 요청 정보를 확인해 주세요.")
    body_hash=request_body_hash(session_id=session_id,question=question,choice=choice,policy_receipt_id=policy_receipt_id)
    execution_metadata=dict(execution_metadata or {})
    if 'policy_receipt_id' in execution_metadata:
        raise ApiError(422,'INVALID_CONTRACT','정책 연결은 전용 인자로 지정해야 합니다.')
    async with pool.acquire() as conn:
        async with conn.transaction():
            publication=await conn.fetchrow("select * from knowledge_publications where store_id=$1 for share",store_id)
            card_ids=sorted({int(b.card_id) for b in plan.selected_blocks})
            cards=await conn.fetch("""select card_id,published_version_id,review_status,is_verified
                from knowledge_cards where store_id=$1 and card_id=any($2::bigint[]) order by card_id for share""",
                store_id,card_ids)
            await conn.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",
                               f"r:answer:{store_id}:{member_id}:{request_id}")
            await _lock_session(conn,store_id=store_id,member_id=member_id,session_id=session_id)
            replay=await _receipt(conn,store_id=store_id,member_id=member_id,request_id=request_id,body_hash=body_hash)
            if replay is not None:
                return replay
            if policy_receipt_id is not None:
                if choice is not None or plan.action!='ESCALATE':
                    raise ApiError(422,'INVALID_CONTRACT','안전 확인 요청은 별도 이관이어야 합니다.')
                await validate_policy_confirmation(conn,store_id=store_id,member_id=member_id,
                    session_id=session_id,policy_receipt_id=policy_receipt_id,question=question)
                execution_metadata['policy_receipt_id']=policy_receipt_id
            if (not publication or str(publication["current_snapshot_id"])!=snapshot.snapshot_id
                    or str(publication["knowledge_revision"])!=snapshot.knowledge_revision):
                raise ApiError(409,"STALE_KNOWLEDGE","공개 내용이 변경됐습니다.",retryable=True)
            expected={(int(b.card_id),int(b.card_version_id)) for b in plan.selected_blocks}
            actual={(r["card_id"],r["published_version_id"]) for r in cards
                    if r["review_status"]=="APPROVED" and r["is_verified"]}
            if actual!=expected:
                raise ApiError(409,"STALE_KNOWLEDGE","선택한 카드의 승인이 변경됐습니다.",retryable=True)
            verify_snapshot_hash(snapshot)
            header=await conn.fetchrow("select snapshot_hash from knowledge_snapshots where store_id=$1 and snapshot_id=$2",
                                      store_id,int(snapshot.snapshot_id))
            if header is None or header["snapshot_hash"]!=snapshot.snapshot_hash:
                raise ApiError(409,"HASH_MISMATCH","공개 내용의 식별값이 다릅니다.")
            context=None
            if choice is not None:
                context=await accept_context(conn,store_id=store_id,member_id=member_id,session_id=session_id,
                    context_id=choice.context_id,expected_state_revision=choice.state_revision,option=choice.option,
                    knowledge_revision=int(snapshot.knowledge_revision))
                validate_context_question(question=question,resolved=resolved,choice=choice,
                    original_question=context.context.original_question)
            if isinstance(semantic_context,dict) and 'version' in semantic_context:
                expected_context=explicit_context(snapshot,question=resolved.question,entity=resolved.entity_id,
                    predicate=resolved.predicate,variants=resolved.variants,has_context=False)
                if plan.action!='ESCALATE' or expected_context is None or semantic_context!=expected_context:
                    raise ApiError(422,'INVALID_CONTRACT','질문 묶음의 확정 근거가 일치하지 않습니다.')
            validate_answer_for_question(plan,snapshot,resolved,store_id=store_id)
            if plan.action=="CLARIFY":
                if choice is not None:
                    if plan.context_id!=choice.context_id:
                        raise ApiError(422,"INVALID_CONTRACT","문맥 식별값이 다릅니다.")
                    context=await offer_next_context(conn,store_id=store_id,member_id=member_id,session_id=session_id,
                        context_id=choice.context_id,slot=plan.clarification_slot,options=plan.allowed_options)
                else:
                    context=await create_context(conn,store_id=store_id,member_id=member_id,session_id=session_id,
                        original_question=question,confirmed_slots=confirmed_slots,proposed_slots={},
                        knowledge_revision=int(snapshot.knowledge_revision),slot=plan.clarification_slot,
                        options=plan.allowed_options,issued_context_id=plan.context_id)
            # Per-store opportunistic cleanup; idle stores use the maintenance CLI.
            # Only expired diagnostics may change, never answers or policy links.
            await conn.fetchval('select purge_r_execution_metadata($1)', store_id)
            user_message=await conn.fetchval("""insert into chat_messages(session_id,sender_type,content)
                values($1,'USER',$2) returning message_id""",session_id,question)
            await conn.execute("""insert into access_logs(store_id,user_id,action_type)
                select store_id,user_id,'QUERY' from store_members where store_id=$1 and member_id=$2""",store_id,member_id)
            pending_id=None
            if plan.action=="ESCALATE":
                key=pending_key(store_id=store_id,semantic_context=semantic_context)
                await conn.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",f"r:pending:{key}")
                pending_id=await conn.fetchval("""select question_id from pending_questions
                    where store_id=$1 and semantic_key=$2 and contract_version='v2' and status='WAITING' for update""",store_id,key)
                if pending_id is None:
                    pending_id=await conn.fetchval("""insert into pending_questions(store_id,member_id,message_id,
                        question_text,miss_reason,status,contract_version,semantic_key)
                        values($1,$2,$3,$4,'no_match','WAITING','v2',$5) returning question_id""",
                        store_id,member_id,user_message,question[:500],key)
                await conn.execute("""insert into pending_question_occurrences(question_id,member_id,message_id)
                    values($1,$2,$3)""",pending_id,member_id,user_message)
                # 앱 알림이 durable 전달 원장이다. 민감 원문을 preview에 복제하지 않는다.
                await create_pending_question_notification(conn,store_id,pending_id,"업무 질문의 확인 요청이 도착했습니다.",contract_version='v2')
            source_ids=sorted({int(p.source_id) for f in snapshot.fact_revisions for p in f.provenance}
                              | {int(r.source_id) for r in snapshot.raw_spans})
            rows=await conn.fetch("select source_id,source_availability from sources where store_id=$1 and source_id=any($2::bigint[])",
                                  store_id,source_ids)
            response=render(plan,snapshot,store_id=store_id,request_id=request_id,
                pending_id=str(pending_id) if pending_id else None,
                availability={str(r["source_id"]):r["source_availability"] for r in rows})
            buddy_message=await conn.fetchval("""insert into chat_messages(session_id,sender_type,content,
                answer_type,answer_source,grounding_status) values($1,'BUDDY',$2,$3,$4,$5) returning message_id""",
                session_id,response.message,"ANSWERED" if plan.action=="ANSWER" else "NO_ANSWER",
                "CARD_ORIGINAL" if plan.action=="ANSWER" else "MISS",
                "FALLBACK" if plan.action=="ANSWER" else "NOT_APPLICABLE")
            receipt_id=await conn.fetchval("""insert into r_answer_receipts(store_id,member_id,session_id,
                request_id,body_hash,original_question,resolved_query,context_snapshot,snapshot_id,knowledge_revision,
                user_message_id,buddy_message_id,pending_id,response,execution_metadata)
                values($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13,$14::jsonb,$15::jsonb) returning receipt_id""",
                store_id,member_id,session_id,request_id,body_hash,question,
                json.dumps(dict(question=resolved.question,entity=resolved.entity_id,predicate=resolved.predicate,variants=resolved.variants,
                                confirmed_slots=confirmed_slots,semantic_context=semantic_context)),
                json.dumps(dict(state_revision=context.state_revision,context=context.context.model_dump(mode="json"))) if context else None,
                int(snapshot.snapshot_id),int(snapshot.knowledge_revision),
                user_message,buddy_message,pending_id,response.model_dump_json(),json.dumps(execution_metadata or {}))
            for order,citation in enumerate(response.citations,1):
                await conn.execute("""insert into r_answer_citations(store_id,receipt_id,citation_order,card_id,
                    card_version_id,block_id,fact_revision_id,raw_span_id,source_id) values($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                    store_id,receipt_id,order,int(citation.card_id),int(citation.card_version_id),citation.block_id,
                    int(citation.fact_revision_id) if citation.fact_revision_id else None,
                    int(citation.raw_span_id) if citation.raw_span_id else None,int(citation.source_id))
        return StoredReply(response,str(receipt_id),False,context.state_revision if context and plan.action=="CLARIFY" else None)


def validate_context_question(*,question:str,resolved:ResolvedSelection,choice:ContextChoice,original_question:str):
    if question.strip()!=choice.option or resolved.question!=original_question+' '+question:
        raise ApiError(422,'INVALID_CONTRACT','저장된 원질문과 선택 문맥이 일치하지 않습니다.')
