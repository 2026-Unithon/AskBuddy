"""직원 레시피 한눈에 보기(계획 7 Task 12). 공개 판의 사실 묶음에서 화면이 쓰는 칸만 내보낸다.

화면(web compactRecipe)이 규격·순서·'이름=값' 문장으로 한눈에 보기를 만든다. 근거·출처는 내보내지 않는다.
"""
from __future__ import annotations

from typing import Any

from app.cards import fact_edit_repo as fact_repo
from app.cards.fact_edit_schemas import CardFactsView


def blocks_for_staff(view: CardFactsView) -> list[dict[str, Any]]:
    return [
        {"kind": block.kind,
         "variant": {"temperature": block.variant.temperature, "size": block.variant.size},
         "facts": [{"sentence": f.sentence, "step_order": f.step_order} for f in block.facts]}
        for block in view.blocks
    ]


async def published_fact_blocks(db, store_id: int, card_id: int, version_id: int) -> list[dict[str, Any]] | None:
    """사실 카드면 그 공개 판의 묶음, 아니면 None(화면은 본문 그대로 보인다)."""
    state = await fact_repo.load_card_fact_state(db, store_id, card_id, version_id)
    if state is None:
        return None
    rows = await fact_repo.load_fact_rows(db, store_id, state)
    from app.cards.router import build_facts_view  # 순환 import 를 피한다
    return blocks_for_staff(build_facts_view(state, rows, {}))
