"""계약 모양을 넘어선 검증 — 신뢰 범위와 실제 snapshot 을 대조한다 (CP-01/RV-04).

**pydantic 은 모양만 본다.** `AnswerPlan` 이 형식을 통과했다는 것은 "ID 가 숫자
문자열이다" 라는 뜻이지 "그 카드가 이 매장의 승인 카드다" 라는 뜻이 아니다.
임의의 snapshot_id·card_id 를 넣어도 모양은 통과한다.

그래서 답변을 내보내기 전에 **서버가 쥐고 있는 값**과 대조한다:
  - `store_id` 는 JWT 에서 꺼낸 값이다. 요청 본문의 값을 쓰지 않는다 (불변식 4)
  - snapshot 은 서버가 조회한 현재 공개 판이다. 모델이 준 것이 아니다

여기를 통과해도 DB 의 공개 포인터·권한 재확인은 저장 시점에 다시 한다.
계약 검증은 필요조건이지 충분조건이 아니다.
"""
from __future__ import annotations

from app.contracts.answer import AnswerPlan
from app.contracts.snapshot import PublishedKnowledgeSnapshot


class AnswerPlanViolation(ValueError):
    """답변 계획이 승인 지식과 어긋난다. 이 예외를 삼키고 답하지 않는다."""


def validate_answer_plan(
    plan: AnswerPlan,
    snapshot: PublishedKnowledgeSnapshot,
    *,
    store_id: str,
) -> None:
    """계획이 이 매장의 이 승인 판 안에서만 인용하는지 검사한다.

    통과하면 아무것도 돌려주지 않고, 어긋나면 `AnswerPlanViolation` 을 던진다.
    """
    if snapshot.store_id != store_id:
        raise AnswerPlanViolation(
            f"다른 매장의 snapshot 이다: {snapshot.store_id} ≠ {store_id}")
    if plan.snapshot_id != snapshot.snapshot_id:
        raise AnswerPlanViolation(
            f"계획이 다른 snapshot 을 가리킨다: {plan.snapshot_id}")
    if plan.knowledge_revision != snapshot.knowledge_revision:
        # 판이 어긋나면 답변 시점과 인용 시점의 지식이 다르다. 재현이 깨진다
        raise AnswerPlanViolation(
            f"knowledge_revision 이 다르다: {plan.knowledge_revision} "
            f"≠ {snapshot.knowledge_revision}")

    cited: set[str] = set()
    for sel in plan.selected_blocks:
        card = snapshot.card(sel.card_id)
        if card is None:
            raise AnswerPlanViolation(f"승인 카드가 아니다: {sel.card_id}")
        if card.card_version_id != sel.card_version_id:
            raise AnswerPlanViolation(
                f"카드 {sel.card_id} 의 버전이 다르다: {sel.card_version_id} "
                f"≠ {card.card_version_id}")
        block = next((b for b in card.blocks if b.block_id == sel.block_id), None)
        if block is None:
            raise AnswerPlanViolation(
                f"카드 {sel.card_id} 에 없는 블록이다: {sel.block_id}")
        outside = [f for f in sel.fact_revision_ids
                   if f not in block.fact_revision_ids]
        if outside:
            # 블록 밖 사실을 끌어오면 검수된 조합이 아닌 것을 보여주게 된다
            raise AnswerPlanViolation(
                f"블록 {sel.block_id} 이 담지 않은 사실을 인용한다: {outside}")
        cited.update(sel.fact_revision_ids)

    missing = _missing_prerequisites(cited, snapshot)
    if missing:
        # snapshot 에 실려 있어도 **인용하지 않으면 신입에게 보이지 않는다**.
        # "약품을 넣는다" 만 인용하고 "먼저 전원을 끈다" 를 빼면 위험한 절반만 간다
        raise AnswerPlanViolation(f"선행 사실을 함께 인용하지 않았다: {sorted(missing)}")


def _missing_prerequisites(
    cited: set[str], snapshot: PublishedKnowledgeSnapshot
) -> set[str]:
    """인용한 사실들이 요구하는 선행 사실 중 인용되지 않은 것.

    snapshot 검증이 선행 사실의 **적재**를 보장하고, 여기서 **인용**을 보장한다.
    둘은 다른 문제다.
    """
    need: set[str] = set()
    stack = list(cited)
    while stack:
        fact = snapshot.fact(stack.pop())
        if fact is None:
            continue
        for req in fact.requires:
            if req not in cited and req not in need:
                need.add(req)
                stack.append(req)
    return need
