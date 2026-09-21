"""일회용 전체 schema에서 v2 5행동 저장·멱등·문맥·pending 경합을 검증한다."""
import asyncio
import json
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from app.contracts.answer import AnswerPlan,SelectedBlock
from app.errors import ApiError
from app.learn.answer_storage import save_answer,ContextChoice
from app.learn.answer_validation import ResolvedSelection,SuitabilityAssessment,question_hash


async def verify(pool,admin,seed):
    sid,mid,uid,snapshot=(seed[k] for k in ("store_id","member_id","user_id","snapshot"))
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name)
        print("PASS M3",name)
    session=await admin.fetchval("""insert into chat_sessions(store_id,member_id,contract_version)
        values($1,$2,'v2') returning session_id""",sid,mid)
    source_ids={int(p.source_id) for f in snapshot.fact_revisions for p in f.provenance}
    source_ids.update(int(r.source_id) for r in snapshot.raw_spans)
    for source in sorted(source_ids):
        await admin.execute("""insert into sources(source_id,store_id,uploaded_by,source_type,title)
            overriding system value values($1,$2,$3,'SCAN','합성 승인 자료')""",source,sid,uid)
    for raw in snapshot.raw_spans:
        await admin.execute("""insert into raw_spans(raw_span_id,store_id,source_id,span_text)
            overriding system value values($1,$2,$3,$4)""",int(raw.raw_span_id),sid,int(raw.source_id),raw.text)
    for fact in snapshot.fact_revisions:
        await admin.execute("""insert into fact_revisions(fact_revision_id,store_id,fact_id,entity_id,
            original_assertion,assertion,predicate,variant_temperature,variant_size,conditions,exceptions,
            subject,quantity_value,quantity_unit,value_text,polarity,step_order)
            overriding system value values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12,$13,$14,$15,$16,$17)""",
            int(fact.fact_revision_id),sid,int(fact.fact_id),int(fact.entity_id),fact.original_assertion,fact.assertion,
            fact.predicate,fact.variant.temperature,fact.variant.size,json.dumps(fact.conditions),json.dumps(fact.exceptions),
            fact.subject,Decimal(fact.quantity.value) if fact.quantity else None,fact.quantity.unit if fact.quantity else None,
            fact.value_text,fact.polarity,fact.order)
    for published_card in snapshot.cards:
        for published_block in published_card.blocks:
            await admin.execute("""insert into card_version_blocks(store_id,card_version_id,block_id,kind,block_order,raw_span_id)
                values($1,$2,$3,$4,$5,$6)""",sid,int(published_card.card_version_id),published_block.block_id,
                published_block.kind,published_block.order,int(published_block.raw_span_id) if published_block.raw_span_id else None)
            for position,fid in enumerate(published_block.fact_revision_ids,1):
                await admin.execute("""insert into card_block_facts(store_id,card_version_id,block_id,fact_revision_id,position)
                    values($1,$2,$3,$4,$5)""",sid,int(published_card.card_version_id),published_block.block_id,int(fid),position)
    card=next(c for c in snapshot.cards if any(b.raw_span_id for b in c.blocks))
    block=next(b for b in card.blocks if b.raw_span_id)
    selected=SelectedBlock(card_id=card.card_id,card_version_id=card.card_version_id,
                           block_id=block.block_id,raw_span_id=block.raw_span_id)
    base=dict(snapshot_id=snapshot.snapshot_id,knowledge_revision=snapshot.knowledge_revision)
    def resolved(question,answer=False):
        assessment=None
        if answer:
            assessment=SuitabilityAssessment(store_id=str(sid),snapshot_id=snapshot.snapshot_id,
                knowledge_revision=snapshot.knowledge_revision,snapshot_hash=snapshot.snapshot_hash,
                question_hash=question_hash(question),entity_id=card.entity_id,predicate="synthetic_location",
                variants=(),raw_blocks=((card.card_id,card.card_version_id,block.block_id,block.raw_span_id),))
        return ResolvedSelection(card.entity_id,"synthetic_location",(),question=question,assessment=assessment)
    async def save(key,action="ANSWER",question="  합성 위치 질문\n",**kw):
        resolved_question=kw.pop('resolved_question',question)
        plan=kw.pop("plan",None) or AnswerPlan(**base,action=action,
            **({"selected_blocks":(selected,)} if action=="ANSWER" else
               {"escalation_reason":"INSUFFICIENT_KNOWLEDGE"} if action=="ESCALATE" else {}))
        return await save_answer(pool,store_id=sid,member_id=mid,session_id=session,request_id=key,
            question=question,snapshot=snapshot,plan=plan,resolved=resolved(resolved_question,plan.action=="ANSWER"),
            confirmed_slots={},**kw)
    first=await save("m3-answer-first")
    replay=await save("m3-answer-first")
    check("answer replay does not write again",not first.replayed and replay.replayed and first.receipt_id==replay.receipt_id)
    check("exact RAW citation persisted",await admin.fetchval(
        "select raw_span_id from r_answer_citations where store_id=$1 and receipt_id=$2",sid,int(first.receipt_id))==int(block.raw_span_id))
    check("original question whitespace persisted",await admin.fetchval(
        "select original_question from r_answer_receipts where store_id=$1 and receipt_id=$2",sid,int(first.receipt_id))=="  합성 위치 질문\n")
    try:
        await save("m3-answer-first",question="다른 질문")
    except ApiError as exc:
        check("same key changed question rejected",exc.code=="IDEMPOTENCY_CONFLICT")
    else:
        raise AssertionError("idempotency conflict accepted")
    replies=await asyncio.gather(save("m3-simultaneous"),save("m3-simultaneous"))
    check("concurrent save creates one receipt",sum(r.replayed for r in replies)==1)
    for action in ("REFUSE","SAFE_ROUTE"):
        result=await save("m3-policy-"+action,action=action)
        check(action+" has no pending or citation",not result.response.pending_id and not result.response.citations)
    context_id=uuid4()
    plan=AnswerPlan(**base,action="CLARIFY",context_id=context_id,clarification_slot="temperature",allowed_options=("HOT","ICE"))
    clarified=await save("m3-clarify-first",plan=plan)
    check("clarify context persisted without pending",clarified.response.context_id==context_id and not clarified.response.pending_id)
    accepted=await save("m3-clarify-accept",action="SAFE_ROUTE",question="HOT",
                       resolved_question="  합성 위치 질문\n HOT",
                       choice=ContextChoice(context_id,1,"HOT"))
    value=await admin.fetchval("select confirmed_slots->>'temperature' from r_question_contexts where context_id=$1",context_id)
    check("accepted option and response commit together",value=="HOT" and accepted.response.action=="SAFE_ROUTE")
    sem=dict(entity="synthetic-a",predicate="quantity",variant=dict(scope="SPECIFIC",temperature="HOT"),
             conditions=[],policy_scope="work")
    a=await save("m3-pending-a",action="ESCALATE",semantic_context=sem)
    b=await save("m3-pending-b",action="ESCALATE",semantic_context=sem)
    c=await save("m3-pending-c",action="ESCALATE",semantic_context=dict(sem,entity="synthetic-b"))
    check("same confirmed context groups occurrences",a.response.pending_id==b.response.pending_id)
    check("same words different entity stay separate",a.response.pending_id!=c.response.pending_id)
    check("group notification deduplicated",await admin.fetchval(
        "select count(*) from notification_events where store_id=$1 and aggregate_id=$2 and event_type='PENDING_QUESTION'",
        sid,int(a.response.pending_id))==1)
    unknown1=await save("m3-pending-unknown1",action="ESCALATE")
    unknown2=await save("m3-pending-unknown2",action="ESCALATE")
    check("unresolved context not merged",unknown1.response.pending_id!=unknown2.response.pending_id)
    before=await admin.fetchval("select count(*) from pending_questions where store_id=$1",sid)
    try:
        with patch("app.learn.answer_storage.render",side_effect=ValueError("synthetic render failure")):
            await save("m3-failure-rollback",action="ESCALATE")
    except ValueError:
        pass
    else:
        raise AssertionError("failure not injected")
    check("render failure rolls back pending and receipt",before==await admin.fetchval(
        "select count(*) from pending_questions where store_id=$1",sid) and not await admin.fetchval(
        "select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='m3-failure-rollback')",sid))
    # Exact reviewed free expressions use the normal transactional pending path.
    from app.learn.reviewed_grouping import GroupingReview, GroupingEvidence, reviewed_context
    scope=GroupingReview(entity=card.entity_id,predicate='milk_amount',temperature='HOT',size=None,
        conditions=('합성 조건',),exceptions=(),scope_bindings=(),polarity='POSITIVE',complete=True)
    async def grouped(key,text,scope,forge=False):
        evidence=GroupingEvidence(str(sid),snapshot.snapshot_hash,text,'synthetic human review',scope)
        context=reviewed_context(snapshot,evidence=evidence,question=text)
        selected=ResolvedSelection(scope.entity,scope.predicate,((scope.temperature,scope.size),),text,
            grouping_evidence=None if forge else evidence)
        return await save_answer(pool,store_id=sid,member_id=mid,session_id=session,request_id=key,
            question=text,snapshot=snapshot,plan=AnswerPlan(**base,action='ESCALATE',escalation_reason='INSUFFICIENT_KNOWLEDGE'),
            resolved=selected,confirmed_slots={},semantic_context=context)
    a=await grouped('m3-reviewed-group-1','합성 자유 표현 하나',scope)
    b=await grouped('m3-reviewed-group-2','동일 범위의 다른 표현',scope)
    check('reviewed free expressions share pending',a.response.pending_id==b.response.pending_id)
    c=await grouped('m3-reviewed-group-3','다른 조건 표현',scope.model_copy(update={'conditions':('다른 조건',)}))
    check('reviewed conditions remain separate',a.response.pending_id!=c.response.pending_id)
    try:await grouped('m3-forged-group-1','위조 문맥',scope,forge=True)
    except ValueError:check('group context without review capability rejected',True)
    else:raise AssertionError('forged grouping accepted')
    check('rejected grouping writes no receipt',not await admin.fetchval(
        "select exists(select 1 from r_answer_receipts where store_id=$1 and request_id='m3-forged-group-1')",sid))
    # 현재 공개 판이 바뀌어도 재조회는 당시 저장 결과다. 신규 답변은 stale로 차단한다.
    await admin.execute("update knowledge_publications set knowledge_revision=knowledge_revision+1 where store_id=$1",sid)
    historical=await save("m3-answer-first")
    check("replay preserves historical response after publication change",historical.replayed and historical.response==first.response)
    try:
        await save("m3-stale-new-question")
    except ApiError as exc:
        check("new stale answer rejected",exc.code=="STALE_KNOWLEDGE")
    else:
        raise AssertionError("stale answer accepted")
    print(f"Verified {len(passed)} M3 answer DB checks")
    # 다음 독립 시나리오를 위해 이 일회용 fixture의 고의 불일치를 복원한다.
    await admin.execute("update knowledge_publications set knowledge_revision=$2 where store_id=$1",sid,int(snapshot.knowledge_revision))
