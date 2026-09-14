"""공통 승인 참조 검사. 질문 적합성·DB 현재 권한/CAS 검사는 별도 책임이다.

snapshot은 서버 manifest 로더가 hash/출처를 검증한 입력이며 모델에게 받지 않는다.
"""
from __future__ import annotations
from dataclasses import dataclass
from pydantic import ValidationError
from app.contracts.answer import AnswerPlan
from app.contracts.snapshot import PublishedKnowledgeSnapshot


class AnswerPlanViolation(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_REFERENCE"):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ValidatedReferences:
    plan: AnswerPlan
    snapshot: PublishedKnowledgeSnapshot
    fact_ids: tuple[str, ...]
    raw_blocks: tuple[tuple[str, str, str, str], ...]


def validate_answer_references(
    plan: AnswerPlan, snapshot: PublishedKnowledgeSnapshot, *, store_id: str,
) -> ValidatedReferences:
    """참조 종류·승인 소속·중복·선행 closure/순서를 검사한다."""
    try:
        plan = AnswerPlan.model_validate(plan.model_dump(mode="json"))
        snapshot = PublishedKnowledgeSnapshot.model_validate(snapshot.model_dump(mode="json"))
    except ValidationError as exc:
        raise AnswerPlanViolation("계약 입력이 유효하지 않다", code="INVALID_CONTRACT") from exc
    if snapshot.store_id != store_id:
        raise AnswerPlanViolation("승인 범위를 벗어난 참조")
    if plan.snapshot_id != snapshot.snapshot_id or plan.knowledge_revision != snapshot.knowledge_revision:
        raise AnswerPlanViolation("현재 승인 판과 다른 선택", code="STALE_KNOWLEDGE")
    facts = {f.fact_revision_id: f for f in snapshot.fact_revisions}
    cards = {c.card_id: c for c in snapshot.cards}
    cited = []
    raw_blocks = []
    for sel in plan.selected_blocks:
        card = cards.get(sel.card_id)
        if card is None or card.card_version_id != sel.card_version_id:
            raise AnswerPlanViolation("승인 카드 버전이 아니다")
        block = next((b for b in card.blocks if b.block_id == sel.block_id), None)
        if block is None:
            raise AnswerPlanViolation("승인 블록이 아니다")
        if block.kind == "RAW":
            if block.fact_revision_ids or not block.raw_span_id:
                raise AnswerPlanViolation("RAW 계약이 모호하다", code="UNSUPPORTED_SCHEMA")
            if sel.fact_revision_ids or sel.raw_span_id != block.raw_span_id:
                raise AnswerPlanViolation("RAW 참조 종류 또는 원문 구간 불일치")
            raw_blocks.append((sel.card_id, sel.card_version_id, sel.block_id, sel.raw_span_id))
            continue
        if sel.raw_span_id or not set(sel.fact_revision_ids).issubset(block.fact_revision_ids):
            raise AnswerPlanViolation("블록 밖 사실 또는 잘못된 참조 종류")
        for fid in sel.fact_revision_ids:
            if facts[fid].entity_id != card.entity_id:
                raise AnswerPlanViolation("사실과 승인 카드 대상 불일치")
        # 조건/예외를 떼는 하위 선택은 DTO에 없다. 사실 자체가 선택 단위다.
        approved_order = sorted(
            (fid for fid in block.fact_revision_ids if fid in sel.fact_revision_ids),
            key=lambda fid: facts[fid].order or 0,
        )
        if tuple(approved_order) != sel.fact_revision_ids:
            raise AnswerPlanViolation("승인 사실 순서를 바꾼 선택")
        cited.extend(sel.fact_revision_ids)
    positions = {fid: i for i, fid in enumerate(cited)}
    if len(positions) != len(cited):
        raise AnswerPlanViolation("여러 블록에서 중복 사실 선택")
    for fid in cited:
        for prerequisite in facts[fid].requires:
            if prerequisite not in positions or positions[prerequisite] >= positions[fid]:
                raise AnswerPlanViolation("선행 사실 누락 또는 순서 역전")
            if facts[prerequisite].entity_id != facts[fid].entity_id:
                raise AnswerPlanViolation("명시적 대상 간 선행 계약이 필요하다", code="UNSUPPORTED_SCHEMA")
    return ValidatedReferences(plan, snapshot, tuple(cited), tuple(raw_blocks))


def validate_answer_plan(plan: AnswerPlan, snapshot: PublishedKnowledgeSnapshot, *, store_id: str) -> None:
    """기존 W 호출자의 호환 이름. 질문 적합성까지 검사하는 함수가 아니다."""
    validate_answer_references(plan, snapshot, store_id=store_id)
