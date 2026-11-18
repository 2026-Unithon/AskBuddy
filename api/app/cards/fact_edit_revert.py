"""수정 되돌리기(계획 7 Task 7). 직전 판의 사실로 지금 카드에 대한 편집 요청을 만든다.

판(fact_revisions·card_versions)은 지우지 않는다. 옛 값으로 새 판을 만드는 보통 편집과 같은 경로라
검증·검수 상태·공개 포인터 규칙이 그대로 적용된다.
"""
from __future__ import annotations

from app.cards.fact_edit_schemas import (
    CardFactsView,
    EditAdd,
    EditBlock,
    EditLine,
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
        # 옛 판 id → 이 요청에서 그 사실을 가리키는 이름(지금 판 id 또는 ADD client_ref)
        now_id: dict[int, int] = {}
        add_ref: dict[int, str] = {}
        for i, row in enumerate(block.facts):
            present = now.get(row.fact_id)
            if present is None:
                # 수정에서 뺀 줄은 다시 넣는다
                ref = f"revert-{row.fact_id}-{i}"
                items.append(EditAdd(op="ADD", client_ref=ref, fact=_fields(row)))
                add_ref[row.fact_revision_id] = ref
                continue
            kept.add(row.fact_id)
            now_id[row.fact_revision_id] = present.fact_revision_id
            if _same(present, row):
                items.append(EditKeep(op="KEEP", fact_revision_id=present.fact_revision_id))
            else:
                items.append(EditModify(op="MODIFY", fact_revision_id=present.fact_revision_id, fact=_fields(row)))
        if items:
            # 옛 판의 구역 제목·줄로 돌아간다(D23)
            lines = [EditLine(text=line.text,
                              fact_revision_ids=[now_id[r] for r in line.fact_revision_ids if r in now_id],
                              client_refs=[add_ref[r] for r in line.fact_revision_ids if r in add_ref])
                     for line in block.lines
                     if any(r in now_id or r in add_ref for r in line.fact_revision_ids)]
            blocks.append(EditBlock(kind=block.kind, items=items, heading=block.heading, lines=lines))
    # 수정에서 새로 넣은 줄은 뺀다
    deleted = [row.fact_revision_id for fact_id, row in now.items() if fact_id not in kept]
    return FactEditRequest(expected_version_id=current.version_id, idempotency_key=idempotency_key,
                           blocks=blocks, deleted_fact_revision_ids=deleted)
