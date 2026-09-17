"""승인 원문·조건·예외를 보존하는 v2 서버 렌더러. 의미 판정은 R 검증기가 수행한다."""
from app.contracts.answer import AnswerPlan
from app.contracts.chat import ChatResponse, Citation, POLICY_MESSAGES
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.validate import validate_answer_references

RENDERER_VERSION = "r-approved/v1"


def render(plan: AnswerPlan, snapshot: PublishedKnowledgeSnapshot, *, store_id: int,
           request_id: str, pending_id: str | None = None, availability=None) -> ChatResponse:
    if snapshot.renderer_version != RENDERER_VERSION:
        raise ValueError("unsupported approved renderer version")
    validate_answer_references(plan,snapshot,store_id=str(store_id))
    fields = dict(request_id=request_id,action=plan.action,snapshot_id=snapshot.snapshot_id,
                  knowledge_revision=snapshot.knowledge_revision)
    if plan.action in POLICY_MESSAGES:
        return ChatResponse(**fields,message=POLICY_MESSAGES[plan.action])
    if plan.action=="CLARIFY":
        return ChatResponse(**fields,message="어느 경우인지 선택해 주세요.",context_id=plan.context_id,
                            clarification_slot=plan.clarification_slot,allowed_options=plan.allowed_options)
    if plan.action=="ESCALATE":
        return ChatResponse(**fields,message="확인된 자료만으로 답하기 어려워 사장님께 확인을 요청했어요.",pending_id=pending_id)
    lines,citations=[],[]
    availability=availability or {}
    for selected in plan.selected_blocks:
        card=snapshot.card(selected.card_id)
        if selected.raw_span_id:
            span=next(s for s in snapshot.raw_spans if s.raw_span_id==selected.raw_span_id)
            lines.append(span.text)
            citations.append(Citation(card_id=card.card_id,card_version_id=card.card_version_id,
                block_id=selected.block_id,raw_span_id=span.raw_span_id,source_id=span.source_id,
                source_availability=availability.get(span.source_id,"UNAVAILABLE")))
        else:
            for fid in selected.fact_revision_ids:
                fact=snapshot.fact(fid)
                heading=" / ".join(s for s in (card.title,fact.variant.temperature,fact.variant.size) if s)
                # 승인 부정문을 휴리스틱으로 덧쓰거나 뒤집지 않는다.
                lines.extend((heading,fact.assertion,*fact.conditions,*fact.exceptions))
                source=fact.provenance[0].source_id
                citations.append(Citation(card_id=card.card_id,card_version_id=card.card_version_id,
                    block_id=selected.block_id,fact_revision_id=fid,source_id=source,
                    source_availability=availability.get(source,"UNAVAILABLE")))
    return ChatResponse(**fields,message="\n".join(lines),citations=tuple(citations))
