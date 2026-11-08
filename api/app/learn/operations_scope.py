"""A named product is a useful clarification only if its approved text addresses the task."""
from dataclasses import replace
import re

from app.contracts.answer import AnswerPlan
from app.learn.entity_names import entity_names
from app.reg.hybrid import normalize_query


REFUND = re.compile(r'환불|반품|결제\s*취소|주문\s*취소|대금\s*반환')
OPENING = re.compile(r'오픈|개점|영업\s*(?:전|시작)|문\s*(?:열기|열\s*때)')
OPENING_TASK = re.compile(r'비품|시재|준비|체크|점검|첫\s*근무|할\s*일|해야|뭐부터')
REFUND_DETAIL = re.compile(r'영수증.{0,8}(?:없|있)|원결제\s*수단|결제한\s*주문|결제했')
OPENING_DETAIL = re.compile(r'시재.{0,12}(?:세지|안\s*셌|확인)|혼자\s*문을\s*열|첫\s*근무라')


def task_patterns(question):
    text=normalize_query(question)
    sentences=[s.strip() for s in re.split(r'[.?!。？！]',text) if s.strip()]
    if sentences and re.search(r'제조|레시피|샷\s*수|판매가',sentences[-1]):
        text=sentences[-1]
    # Opening time can just be background to a recipe/price question.
    patterns=[]
    if REFUND.search(text):
        patterns.append(REFUND)
    if OPENING.search(text) and OPENING_TASK.search(text):
        patterns.append(OPENING)
    return patterns


def handoff_detail(previous, question):
    """Recognize a statement supplying circumstances of one immediately prior task."""
    text=normalize_query(question)
    if (not text or re.search(r'다른\s*(?:질문|건|주문)|별개|새\s*질문|[?？]|알려\s*줘|어떻게|뭐부터|나요[.!]?$',text)):
        return False
    tasks=task_patterns(previous)
    if tasks==[REFUND]:
        return bool(REFUND_DETAIL.search(text))
    if tasks==[OPENING]:
        return bool(OPENING_DETAIL.search(text))
    return False


def relevant_entity_offer(decision, search, question):
    plan=decision.plan
    if plan.action!='CLARIFY' or plan.clarification_slot!='entity':
        return decision
    patterns=task_patterns(question)
    if not patterns:
        return decision
    supported=set()
    snap=search.snapshot
    for c in search.candidates:
        card=snap.card(c.card_id)
        names=set(entity_names(snap,card.entity_id)).intersection(plan.allowed_options)
        if not names:
            continue
        block=next(b for b in card.blocks if b.block_id==c.block_id)
        text=[card.title]
        for fid in block.fact_revision_ids:
            fact=snap.fact(fid)
            text.extend([fact.predicate or '',fact.assertion,fact.original_assertion,
                         *fact.conditions,*fact.exceptions])
        text.extend(r.text for r in snap.raw_spans if r.raw_span_id==block.raw_span_id)
        content=normalize_query(' '.join(text))
        if any(pattern.search(content) for pattern in patterns):
            supported.update(names)
    options=tuple(option for option in plan.allowed_options if option in supported)
    if not options:
        return replace(decision,plan=AnswerPlan(snapshot_id=plan.snapshot_id,
            knowledge_revision=plan.knowledge_revision,action='ESCALATE',
            escalation_reason='NO_RELEVANT_TASK_OPTION'),semantic_context=None)
    if options!=plan.allowed_options:
        return replace(decision,plan=plan.model_copy(update={'allowed_options':options}))
    return decision
