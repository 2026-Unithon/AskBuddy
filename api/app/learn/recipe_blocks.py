"""직원 레시피 한눈에 보기(계획 7 Task 12). 공개 판의 사실 묶음에서 화면이 쓰는 칸만 내보낸다.

화면은 사장님 카드 상세와 같은 보기(구역 제목·줄)를 그린다(계획 10). 근거·출처는 내보내지 않는다.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.cards import fact_edit_repo as fact_repo
from app.cards.fact_edit_schemas import CardFactsView, FactRow

# 금액 사실은 칸 이름(금액·판매 가격…)이 제각각이라 단위 칸으로 고른다. web/lib/card-price.ts 와 같은 규칙
_CURRENCY = "원"


def _fact_price(fact: FactRow) -> str | None:
    if fact.unit != _CURRENCY or fact.value is None:
        return None
    try:
        return f"{Decimal(fact.value):,}{_CURRENCY}"
    except InvalidOperation:
        return None


def _line_price(refs: list[int], prices: dict[int, str | None]) -> str | None:
    """줄이 인용한 사실이 모두 금액이면 그 금액(여럿이면 쉼표로), 아니면 None."""
    found = [prices.get(rid) for rid in refs]
    if not found or any(p is None for p in found):
        return None
    return ", ".join(dict.fromkeys(p for p in found if p))


def blocks_for_staff(view: CardFactsView) -> list[dict[str, Any]]:
    """계획 10(D23): 사장님 상세와 같은 보기 — 구역 제목·줄. 근거 판 id 는 내보내지 않는다.
    금액 줄에는 금액 글을 붙인다 — 화면이 사장님처럼 제목 옆으로 옮긴다(2026-11-18 사용자)."""
    out: list[dict[str, Any]] = []
    for block in view.blocks:
        prices = {f.fact_revision_id: _fact_price(f) for f in block.facts}
        out.append({"kind": block.kind,
                    "variant": {"temperature": block.variant.temperature, "size": block.variant.size},
                    "heading": block.heading,
                    "lines": [{"line_no": line.line_no, "text": line.text, "price": _line_price(line.fact_revision_ids, prices)}
                              for line in block.lines]})
    return out


async def published_fact_blocks(db, store_id: int, card_id: int, version_id: int) -> list[dict[str, Any]] | None:
    """사실 카드면 그 공개 판의 묶음, 아니면 None(화면은 본문 그대로 보인다)."""
    state = await fact_repo.load_card_fact_state(db, store_id, card_id, version_id)
    if state is None:
        return None
    rows = await fact_repo.load_fact_rows(db, store_id, state)
    from app.cards.router import build_facts_view  # 순환 import 를 피한다
    return blocks_for_staff(build_facts_view(state, rows, {}))
