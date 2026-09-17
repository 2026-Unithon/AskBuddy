"""보수적인 v2 서버 planner. 검색 순위·오타 추정으로 적용 범위를 승인하지 않는다.

지원하지 못하는 RAW 의미/조건 적용성은 ESCALATE다. 모델 reranker를 추가해도
이 판정 경계를 생략할 수 없다. 실자료의 false abstention은 별도 평가해야 한다.
"""
from __future__ import annotations
import re
from decimal import Decimal
from dataclasses import dataclass
from uuid import UUID,uuid4

from app.contracts.answer import AnswerPlan,SelectedBlock
from app.learn.answer_validation import (ResolvedSelection,AnswerReferenceError,validate_answer_for_question,
    SuitabilityAssessment,FactSuitability,question_hash)
from app.reg.hybrid import SearchResult,normalize_query
from app.learn.semantic_grouping import explicit_context, supported_question
from app.learn.conditional_scope import conditional_core, prerequisite_closure, exclusive_conditions
from app.learn.raw_quantity import raw_answer_reference

PLANNER_VERSION="r-explicit-slots/v7"
PREDICATES={
    "milk_amount":("우유 양",("우유","milk")),
    "water_amount":("물 양",("물","water")),
    "location":("보관 위치",("어디","위치")),
    "price":("가격",("가격","얼마","price")),
    "quantity":("수량",("수량","몇 개","몇개")),
}


def mentioned(query:str,term:str)->bool:
    # '라테'를 '말차라테', '물'을 '선물', '얼마'를 '얼마나'로 오인하지 않는다.
    return bool(re.search(r"(?<![가-힣a-z0-9_])"+re.escape(normalize_query(term))+
        r"(?:은|는|이|가|의|을|를|에|에서|로|랑|와|과)?(?![가-힣a-z0-9_])",query))


def atomic_quantity_agrees(fact)->bool:
    """수치 속성은 승인 문장과 구조화 수치/단위가 같은 원자 사실이어야 한다."""
    if fact.quantity is None:return False
    units={"ml":("volume",Decimal(1)),"l":("volume",Decimal(1000)),
           "g":("mass",Decimal(1)),"kg":("mass",Decimal(1000)),
           "개":("count",Decimal(1)),"샷":("shot",Decimal(1))}
    def quantity(value,unit):
        item=units.get(unit.lower())
        return (item[0],Decimal(value)*item[1]) if item else None
    expected=quantity(fact.quantity.value,fact.quantity.unit)
    observed={quantity(value,unit) for value,unit in re.findall(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(ml|kg|g|l|개|샷)(?![a-z])",fact.assertion,re.I)}
    return expected is not None and observed=={expected}


@dataclass(frozen=True)
class Decision:
    plan:AnswerPlan
    resolved:ResolvedSelection
    confirmed_slots:dict[str,str]
    semantic_context:dict|None


def policy_action(question:str):
    q=normalize_query(question)
    if any(x in q for x in ("집 주소","집주소","개인 연락처","주민등록번호","개인정보")):
        return "REFUSE"
    if any(x in q for x in ("알레르기","안전한가","안전해","안전한지","먹어도","응급","다쳤")):
        return "SAFE_ROUTE"
    return None


def decide(search:SearchResult,*,store_id:int,question:str,confirmed_slots:dict[str,str]|None=None,
           context_id:UUID|None=None,clarify_turns:int=0,context_verified:bool=False) -> Decision:
    snapshot=search.snapshot
    if snapshot.store_id!=str(store_id):
        raise ValueError("planner store mismatch")
    slots=dict(confirmed_slots or {})
    q=normalize_query(question)
    entity,predicate="",""
    variants=()
    base=dict(snapshot_id=snapshot.snapshot_id,knowledge_revision=snapshot.knowledge_revision)
    def finish(action,reason=None,slot=None,options=()):
        if action=="CLARIFY" and clarify_turns>=2:
            action,reason="ESCALATE","UNRESOLVED_CONTEXT"
        kwargs=({"context_id":context_id or uuid4(),"clarification_slot":slot,"allowed_options":options}
                if action=="CLARIFY" else {"escalation_reason":reason} if action=="ESCALATE" else {})
        semantic = explicit_context(snapshot, question=question, entity=entity, predicate=predicate,
            variants=variants, has_context=(bool(confirmed_slots) or context_id is not None) and not context_verified) if action=="ESCALATE" else None
        return Decision(AnswerPlan(**base,action=action,**kwargs),
                        ResolvedSelection(entity,predicate,variants,question=question),slots,semantic)
    policy=policy_action(question)
    if policy:
        return finish(policy)
    if any(word in q for word in ("수정","변경","바꿔","아니야","않아","말아")):
        return finish("ESCALATE","UNSUPPORTED_QUESTION_INTENT")
    candidates={(c.card_id,c.card_version_id,c.block_id) for c in search.candidates}
    cards=[c for c in snapshot.cards if any(key[0]==c.card_id for key in candidates)]
    if not cards:
        return finish("ESCALATE","INSUFFICIENT_KNOWLEDGE")
    matches={c.entity_id for c in cards if mentioned(q,c.title)}
    if not matches and slots.get("entity"):
        matches={c.entity_id for c in cards if c.title==slots["entity"]}
    if not matches:
        alias_options=tuple(dict.fromkeys(c.title for c in cards if c.title in search.alias_terms))
        if 0<len(alias_options)<=10:
            return finish('CLARIFY',slot='entity',options=alias_options)
    if len(matches)!=1:
        options=tuple(dict.fromkeys(c.title for c in cards))
        if len(options)>10 or len(options)<2:
            return finish("ESCALATE","UNRESOLVED_CONTEXT")
        return finish("CLARIFY",slot="entity",options=options)
    entity=next(iter(matches))
    entity_cards=[c for c in cards if c.entity_id==entity]
    raw_match=raw_answer_reference(snapshot,entity=entity,question=question,candidates=candidates) if not confirmed_slots and context_id is None else None
    if raw_match:
        card,block,predicate,variants=raw_match
        raw_refs=((card.card_id,card.card_version_id,block.block_id,block.raw_span_id),)
        assessment=SuitabilityAssessment(store_id=str(store_id),snapshot_id=snapshot.snapshot_id,
            knowledge_revision=snapshot.knowledge_revision,snapshot_hash=snapshot.snapshot_hash,
            question_hash=question_hash(question),entity_id=entity,predicate=predicate,variants=variants,raw_blocks=raw_refs)
        resolved=ResolvedSelection(entity,predicate,variants,question=question,assessment=assessment)
        plan=AnswerPlan(**base,action='ANSWER',selected_blocks=(SelectedBlock(card_id=card.card_id,
            card_version_id=card.card_version_id,block_id=block.block_id,raw_span_id=block.raw_span_id),))
        try:validate_answer_for_question(plan,snapshot,resolved,store_id=store_id)
        except AnswerReferenceError:return finish('ESCALATE','UNVERIFIED_RAW_REFERENCE')
        return Decision(plan,resolved,slots,None)
    # 명시적인 원문 열람 요청만 지원한다. 원문 속 조건이 업무 질문에 적용된다는
    # 판단이나 RAW 첫 카드 fallback은 아니다. 문맥 추정/선택과 결합하지 않는다.
    original_cards=[c for c in entity_cards if re.fullmatch(
            re.escape(normalize_query(c.title))+r'(?:의)?\s+승인\s*원문\s*(?:보여줘|보여주세요|보기)[.!?]?',q)
            ]
    if not confirmed_slots and context_id is None and original_cards:
        originals=[(c,b) for c in original_cards for b in c.blocks if b.raw_span_id]
        if not originals or any((c.card_id,c.card_version_id,b.block_id) not in candidates for c,b in originals):
            return finish('ESCALATE','MISSING_RAW_CANDIDATE')
        predicate='approved_original'
        raw_refs=tuple((c.card_id,c.card_version_id,b.block_id,b.raw_span_id) for c,b in originals)
        assessment=SuitabilityAssessment(store_id=str(store_id),snapshot_id=snapshot.snapshot_id,
            knowledge_revision=snapshot.knowledge_revision,snapshot_hash=snapshot.snapshot_hash,
            question_hash=question_hash(question),entity_id=entity,predicate=predicate,variants=(),raw_blocks=raw_refs)
        resolved=ResolvedSelection(entity,predicate,(),question=question,assessment=assessment)
        plan=AnswerPlan(**base,action='ANSWER',selected_blocks=tuple(SelectedBlock(card_id=c.card_id,
            card_version_id=c.card_version_id,block_id=b.block_id,raw_span_id=b.raw_span_id) for c,b in originals))
        try: validate_answer_for_question(plan,snapshot,resolved,store_id=store_id)
        except AnswerReferenceError:return finish('ESCALATE','UNVERIFIED_RAW_REFERENCE')
        return Decision(plan,resolved,slots,None)
    if slots.get("entity") and slots["entity"] not in {c.title for c in entity_cards}:
        for key in ("temperature","size","predicate"):slots.pop(key,None)
    slots["entity"]=next((c.title for c in entity_cards if mentioned(q,c.title)),slots.get("entity",entity_cards[0].title))
    facts=[f for f in snapshot.fact_revisions if f.entity_id==entity]
    available={f.predicate for f in facts if f.predicate}
    matched={p for p,(label,words) in PREDICATES.items() if p in available and any(mentioned(q,w) for w in words)}
    if (not re.search(r"얼마나|몇\s*(?:ml|밀리리터|g|그램|리터)|(?:우유|물)(?:의)?\s*양|용량",q)
            or any(word in q for word in ("오래","기한","언제","보관","온도"))):
        matched.difference_update(("milk_amount","water_amount"))
    matched.update(p for p in available if mentioned(q,p))
    # Condition vocabulary (e.g. 온도) is not the requested attribute. Only a
    # full approved-condition + supported-question parse may override this guard.
    scoped_predicates={f.predicate for f in facts if conditional_core(question,snapshot=snapshot,fact=f,
        titles=tuple(c.title for c in entity_cards),sizes=tuple(sorted({x.variant.size for x in facts if x.variant.size}))) is not None}
    if scoped_predicates:matched=scoped_predicates
    if not matched and slots.get("predicate"):
        matched={p for p in available if slots["predicate"] in (p,PREDICATES.get(p,(p,()))[0])}
    if len(matched)!=1:
        options=tuple(PREDICATES.get(p,(p,()))[0] for p in sorted(available))
        if 2<=len(options)<=10:
            return finish("CLARIFY",slot="predicate",options=options)
        return finish("ESCALATE","UNRESOLVED_PREDICATE")
    predicate=next(iter(matched))
    slots["predicate"]=PREDICATES.get(predicate,(predicate,()))[0]
    facts=[f for f in facts if f.predicate==predicate]
    titles=tuple(c.title for c in entity_cards)
    declared_sizes=tuple(sorted({f.variant.size for f in facts if f.variant.size}))
    cores={f.fact_revision_id:conditional_core(question,snapshot=snapshot,fact=f,
        titles=titles,sizes=declared_sizes) for f in facts}
    known_cores={core for core in cores.values() if core is not None}
    if not known_cores:
        # Keep clarification available for an ordinary question whose evidence
        # has unresolved conditions; never convert that into an ANSWER below.
        if supported_question(question,titles=titles,predicate=predicate,sizes=declared_sizes):
            known_cores={q}
    if len(known_cores)!=1:
        return finish("ESCALATE","UNSUPPORTED_QUESTION_INTENT")
    q=next(iter(known_cores))
    temperatures=set()
    if re.search(r"\bhot\b|따뜻|뜨거운|핫",q):temperatures.add("HOT")
    if re.search(r"\bice\b|아이스|차가운",q):temperatures.add("ICE")
    if not temperatures and slots.get("temperature") in ("HOT","ICE"):
        temperatures.add(slots["temperature"])
    if len(temperatures)>1 and not any(w in q for w in ("비교","각각","둘 다","차이")):
        return finish("CLARIFY",slot="temperature",options=("HOT","ICE"))
    if len(temperatures)>1:slots.pop("temperature",None)
    if not temperatures and any(f.variant.temperature for f in facts):
        return finish("CLARIFY",slot="temperature",options=tuple(sorted({f.variant.temperature for f in facts if f.variant.temperature})))
    sizes={f.variant.size for f in facts if f.variant.size}
    chosen_sizes={s for s in sizes if mentioned(q,s)}
    if not chosen_sizes and slots.get("size") in sizes:chosen_sizes.add(slots["size"])
    if sizes and len(chosen_sizes)!=1:
        return finish("CLARIFY",slot="size",options=tuple(sorted(sizes))) if len(sizes)<=10 else finish("ESCALATE","UNRESOLVED_CONTEXT")
    size=next(iter(chosen_sizes),None)
    variants=tuple(sorted(((temp,size) for temp in temperatures),key=str)) if temperatures else ((None,size),)
    if variants==((None,None),):
        return finish("ESCALATE","UNVERIFIED_VARIANT_SCOPE")
    target=[f for f in facts if (f.variant.temperature,f.variant.size) in variants]
    if {(f.variant.temperature,f.variant.size) for f in target}!=set(variants):
        return finish("ESCALATE","INSUFFICIENT_KNOWLEDGE")
    if len(target)!=len(variants):
        matched_targets=[f for f in target if cores[f.fact_revision_id] is not None]
        if len(matched_targets)!=len(variants):return finish('ESCALATE','CONFLICTING_FACTS')
        for selected_fact in matched_targets:
            selected_conditions=tuple(c for f in prerequisite_closure(snapshot,selected_fact) for c in f.conditions)
            for other in target:
                if other.fact_revision_id==selected_fact.fact_revision_id or other.variant!=selected_fact.variant:continue
                other_conditions=tuple(c for f in prerequisite_closure(snapshot,other) for c in f.conditions)
                if not exclusive_conditions(selected_conditions,other_conditions):
                    return finish('ESCALATE','CONFLICTING_FACTS')
        target=matched_targets
    target=[f for f in target if cores[f.fact_revision_id] is not None]
    if {(f.variant.temperature,f.variant.size) for f in target}!=set(variants):
        return finish("ESCALATE","UNVERIFIED_APPLICABILITY")
    if predicate in ("milk_amount","water_amount","quantity") and not all(atomic_quantity_agrees(f) for f in target):
        return finish("ESCALATE","UNVERIFIED_QUANTITY_BINDING")
    needed=set()
    def visit(fid):
        if fid in needed:return
        needed.add(fid)
        for prerequisite in snapshot.fact(fid).requires:visit(prerequisite)
    for fact in target:visit(fact.fact_revision_id)
    selected=[]
    for card in entity_cards:
        for block in sorted(card.blocks,key=lambda b:b.order):
            chosen=tuple(fid for fid in block.fact_revision_ids if fid in needed)
            if chosen:
                # 후보 밖의 임의 본문은 쓰지 않는다. 선행 확장도 후보가 회수해야 한다.
                if (card.card_id,card.card_version_id,block.block_id) not in candidates:
                    return finish("ESCALATE","MISSING_DEPENDENCY_CANDIDATE")
                selected.append(SelectedBlock(card_id=card.card_id,card_version_id=card.card_version_id,
                                               block_id=block.block_id,fact_revision_ids=chosen))
    if not selected:return finish("ESCALATE","INSUFFICIENT_KNOWLEDGE")
    assessment=None
    if any(snapshot.fact(fid).conditions or snapshot.fact(fid).exceptions for fid in needed):
        # A follow-up is composed from multiple turns; the present assessment
        # contract binds a single exact question. Do not rewrite its hash at save.
        if context_id is not None and not context_verified:
            return finish('ESCALATE','UNVERIFIED_CONTEXT_APPLICABILITY')
        assessment=SuitabilityAssessment(store_id=str(store_id),snapshot_id=snapshot.snapshot_id,
            knowledge_revision=snapshot.knowledge_revision,snapshot_hash=snapshot.snapshot_hash,
            question_hash=question_hash(question),entity_id=entity,predicate=predicate,variants=variants,
            target_fact_ids=tuple(f.fact_revision_id for f in target),
            facts=tuple(FactSuitability(fact_revision_id=fid,variant_scope='SPECIFIC',
                conditions=snapshot.fact(fid).conditions,exceptions=snapshot.fact(fid).exceptions)
                for fid in sorted(needed)))
    resolved=ResolvedSelection(entity,predicate,variants,question=question,assessment=assessment)
    plan=AnswerPlan(**base,action="ANSWER",selected_blocks=tuple(selected))
    try:
        validate_answer_for_question(plan,snapshot,resolved,store_id=store_id)
    except AnswerReferenceError:
        return finish("ESCALATE","UNVERIFIED_APPLICABILITY")
    if len(temperatures)==1:slots["temperature"]=next(iter(temperatures))
    if size:slots["size"]=size
    return Decision(plan,resolved,slots,None)
