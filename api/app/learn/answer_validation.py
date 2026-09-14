"""CP-01 R 참조 검증. DB의 현재 권한·공개 검사와 원자 저장을 대체하지 않는다.

현 W snapshot에는 RAW span·규격 적용 범위·명시적 entity 간 dependency가 없다.
그 표현이 필요한 선택은 추정하지 않고 거절한다. 런타임 연결은 CP-02~04 후다.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.contracts.answer import AnswerPlan
from app.contracts.snapshot import PublishedKnowledgeSnapshot


class AnswerReferenceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResolvedSelection:
    """모델 출력이 아닌 서버가 확정한 질문 범위. 비교 질문은 여러 규격을 담는다."""

    entity_id: str
    predicate: str
    variants: tuple[tuple[str | None, str | None], ...]


def validate_answer_plan(
    plan: AnswerPlan,
    snapshot: PublishedKnowledgeSnapshot,
    resolved_query: ResolvedSelection,
    *,
    store_id: int,
) -> AnswerPlan:
    """승인 블록 전체·사실·규격·선행 순서가 닫힌 typed 선택만 통과시킨다."""
    # model_copy/model_construct로 검증을 우회한 입력도 신뢰하지 않는다.
    plan = AnswerPlan.model_validate(plan.model_dump(mode="json"))
    snapshot = PublishedKnowledgeSnapshot.model_validate(snapshot.model_dump(mode="json"))
    if type(store_id) is not int or store_id <= 0 or snapshot.store_id != str(store_id):
        raise AnswerReferenceError("INVALID_REFERENCE")
    if plan.snapshot_id != snapshot.snapshot_id or plan.knowledge_revision != str(snapshot.knowledge_revision):
        raise AnswerReferenceError("STALE_KNOWLEDGE")

    def unique(items, key):
        result = {}
        for item in items:
            identity = key(item)
            if identity in result:
                raise AnswerReferenceError("INVALID_REFERENCE")
            result[identity] = item
        return result

    cards = unique(snapshot.cards, lambda card: card.card_id)
    unique(snapshot.cards, lambda card: card.card_version_id)
    facts = unique(snapshot.fact_revisions, lambda fact: fact.fact_revision_id)
    blocks = {}
    linked = set()
    for card in cards.values():
        blocks[card.card_id] = unique(card.blocks, lambda block: block.block_id)
        for block in card.blocks:
            if len(set(block.fact_revision_ids)) != len(block.fact_revision_ids):
                raise AnswerReferenceError("INVALID_REFERENCE")
            linked.update(block.fact_revision_ids)
    if set(facts) != linked:
        raise AnswerReferenceError("INVALID_REFERENCE")

    # 반복 DFS로 깊은 선행 사슬도 Python 재귀 한도에 의존하지 않는다.
    done = set()
    for root in facts:
        visiting = set()
        stack = [(root, False)]
        while stack:
            fid, exiting = stack.pop()
            if exiting:
                visiting.remove(fid)
                done.add(fid)
                continue
            if fid in visiting or fid not in facts:
                raise AnswerReferenceError("INVALID_REFERENCE")
            if fid in done:
                continue
            visiting.add(fid)
            stack.append((fid, True))
            stack.extend((dependency, False) for dependency in reversed(facts[fid].requires))

    if plan.action != "ANSWER":
        return plan
    if not resolved_query.entity_id or not resolved_query.predicate or not resolved_query.variants:
        raise AnswerReferenceError("UNRESOLVED_CONTEXT")
    selected = []
    matched_predicate = False
    selected_variants = set()
    for selection in plan.selected_blocks:
        card = cards.get(selection.card_id)
        if card is None or card.card_version_id != selection.card_version_id:
            raise AnswerReferenceError("INVALID_REFERENCE")
        if card.entity_id != resolved_query.entity_id:
            raise AnswerReferenceError("INVALID_REFERENCE")
        block = blocks[card.card_id].get(selection.block_id)
        if block is None or tuple(block.fact_revision_ids) != selection.fact_revision_ids:
            raise AnswerReferenceError("INVALID_REFERENCE")
        if block.kind == "RAW":
            raise AnswerReferenceError("UNSUPPORTED_SCHEMA")
        for fid in selection.fact_revision_ids:
            fact = facts[fid]
            # 현 계약에는 질문의 확정 조건과 예외를 대조할 의미 규칙이 없다.
            if fact.conditions or fact.exceptions:
                raise AnswerReferenceError("UNSUPPORTED_SCHEMA")
            variant = (fact.variant.temperature, fact.variant.size)
            if fact.quantity is not None and fact.value_text is not None:
                raise AnswerReferenceError("INVALID_REFERENCE")
            if fact.quantity is not None and (not fact.quantity.unit or not fact.quantity.unit.strip()):
                raise AnswerReferenceError("UNRESOLVED_CONTEXT")
            if variant == (None, None) or variant not in resolved_query.variants:
                raise AnswerReferenceError("UNRESOLVED_CONTEXT")
            if fact.predicate == resolved_query.predicate:
                matched_predicate = True
                selected_variants.add(variant)
            selected.append(fid)
    if not matched_predicate or selected_variants != set(resolved_query.variants):
        raise AnswerReferenceError("INVALID_REFERENCE")
    positions = {fid: i for i, fid in enumerate(selected)}
    if len(positions) != len(selected):
        raise AnswerReferenceError("INVALID_REFERENCE")
    # 질문에 답하는 사실과 그 선행 사실만 허용한다. 같은 카드라는 이유로
    # 무관한 다른 블록의 업무 사실을 끼워 넣을 수 없다.
    allowed = set()
    pending = [fid for fid in selected if facts[fid].predicate == resolved_query.predicate]
    while pending:
        fid = pending.pop()
        if fid not in allowed:
            allowed.add(fid)
            pending.extend(facts[fid].requires)
    if set(selected) != allowed:
        raise AnswerReferenceError("INVALID_REFERENCE")
    for fid in selected:
        for dependency in facts[fid].requires:
            if dependency not in positions or positions[dependency] >= positions[fid]:
                raise AnswerReferenceError("INVALID_REFERENCE")
    return plan
