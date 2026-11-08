"""수정 되돌리기(계획 7 Task 7). 직전 판의 사실로 지금 카드에 대한 편집 요청을 만든다.

판(fact_revisions·card_versions)은 지우지 않는다. 옛 값으로 새 판을 만드는 보통 편집과 같은 경로라
검증·검수 상태·공개 포인터 규칙이 그대로 적용된다.
"""
from __future__ import annotations

from app.cards.fact_edit_schemas import (
    CardFactsView,
    EditAdd,
    EditBlock,
    EditKeep,
    EditModify,
    FactEditRequest,
    FactFields,
    FactRow,
)


def _fields(row: FactRow) -> FactFields:
    return FactFields(sentence=row.sentence, polarity=row.polarity, value=row.value, unit=row.unit,
                      conditions=row.conditions, exceptions=row.exceptions, step_order=row.step_order,
                      variant=row.variant, predicate=row.predicate)


def _same(a: FactRow, b: FactRow) -> bool:
    return a.fact_revision_id == b.fact_revision_id


def plan_revert(old: CardFactsView, current: CardFactsView, *, idempotency_key: str) -> FactEditRequest:
    """old(수정 전 판)의 줄 순서·값으로 돌아가는 편집 요청. current 는 지금 카드 판."""
    now = {row.fact_id: row for block in current.blocks for row in block.facts}
    kept: set[int] = set()
    blocks: list[EditBlock] = []
    for block in old.blocks:
        if block.kind == "RAW":
            continue
        items = []
        for i, row in enumerate(block.facts):
            present = now.get(row.fact_id)
            if present is None:
                # 수정에서 뺀 줄은 다시 넣는다
                items.append(EditAdd(op="ADD", client_ref=f"revert-{row.fact_id}-{i}", fact=_fields(row)))
                continue
            kept.add(row.fact_id)
            if _same(present, row):
                items.append(EditKeep(op="KEEP", fact_revision_id=present.fact_revision_id))
            else:
                items.append(EditModify(op="MODIFY", fact_revision_id=present.fact_revision_id, fact=_fields(row)))
        if items:
            blocks.append(EditBlock(kind=block.kind, items=items))
    # 수정에서 새로 넣은 줄은 뺀다
    deleted = [row.fact_revision_id for fact_id, row in now.items() if fact_id not in kept]
    return FactEditRequest(expected_version_id=current.version_id, idempotency_key=idempotency_key,
                           blocks=blocks, deleted_fact_revision_ids=deleted)
