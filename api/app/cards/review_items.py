"""검수 고르기 항목(계획 7 Task 6). 충돌한 두 사실을 '맞는 것을 골라 주세요!' 의 두 버튼으로 바꾼다."""
from __future__ import annotations

from app.ingest.text_norm import squash
from app.cards.fact_edit_schemas import CardFactsView, ReviewItem, ReviewOption


def _split(sentence: str) -> tuple[str | None, str]:
    """'이름=값' 이면 (이름, 값), 아니면 (None, 문장 그대로)."""
    name, sep, value = sentence.partition("=")
    if sep and name.strip() and value.strip():
        return name.strip(), value.strip()
    return None, sentence.strip()


def review_item_from_conflict(conflict_id: int, low_fact_id: int, low_text: str,
                              high_fact_id: int, high_text: str) -> ReviewItem:
    low_name, low_value = _split(low_text)
    high_name, high_value = _split(high_text)
    label = low_name if low_name and low_name == high_name else None
    if label is None:
        low_value, high_value = low_text.strip(), high_text.strip()
    return ReviewItem(item_id=f"conflict-{conflict_id}", conflict_id=conflict_id, label=label,
                      options=[ReviewOption(fact_id=low_fact_id, text=low_value),
                               ReviewOption(fact_id=high_fact_id, text=high_value)])


async def load_review_items(conn, store_id: int, fact_ids: list[int]) -> list[ReviewItem]:
    """이 카드 사실이 낀 OPEN 충돌. 두 사실의 지금 판 원문으로 버튼 글을 만든다."""
    if not fact_ids:
        return []
    rows = await conn.fetch(
        "select c.conflict_id, c.fact_id_low, c.fact_id_high, "
        "rl.original_assertion as low_text, rh.original_assertion as high_text "
        "from fact_conflicts c "
        "join knowledge_facts kl on kl.store_id = c.store_id and kl.fact_id = c.fact_id_low "
        "join fact_revisions rl on rl.store_id = kl.store_id and rl.fact_revision_id = kl.head_revision_id "
        "join knowledge_facts kh on kh.store_id = c.store_id and kh.fact_id = c.fact_id_high "
        "join fact_revisions rh on rh.store_id = kh.store_id and rh.fact_revision_id = kh.head_revision_id "
        "where c.store_id = $1 and c.status = 'OPEN' "
        "and (c.fact_id_low = any($2::bigint[]) or c.fact_id_high = any($2::bigint[])) "
        "order by c.conflict_id",
        store_id, fact_ids)
    items: list[ReviewItem] = []
    asked: set[tuple] = set()
    for r in rows:
        item = review_item_from_conflict(r["conflict_id"], r["fact_id_low"], r["low_text"],
                                         r["fact_id_high"], r["high_text"])
        texts = frozenset(squash(o.text) for o in item.options)
        # 띄어쓰기만 다른 두 값은 고를 게 없고, 같은 질문(같은 이름·같은 두 값)은 한 번만 묻는다
        if len(texts) < 2 or (item.label, texts) in asked:
            continue
        asked.add((item.label, texts))
        items.append(item)
    return items





WRITE_LABEL = "근거 자료를 확인할 수 없어요. 맞게 고쳐 적어 주세요."


def write_items(view: CardFactsView) -> list[ReviewItem]:
    """근거(출처)가 없는 사실마다 그 자리 글 입력칸. 사장님이 적으면 사장님 입력 자료가 근거가 된다."""
    return [
        ReviewItem(item_id=f"write-{f.fact_revision_id}", kind="WRITE", label=WRITE_LABEL,
                   fact_revision_id=f.fact_revision_id, text=f.assertion or f.sentence)
        for block in view.blocks for f in block.facts if not f.origins
    ]
