"""똑같아 보이는 두 값을 고르라고 하지 않는다(2026-11-08 사용자 실화면: 같은 글 두 버튼이 세 번)."""
import asyncio
from decimal import Decimal

from app.cards.review_items import load_review_items
from app.ingest.fact_ledger import same_statement


def _r(text, q=None, unit=None, vt=None, pol="AFFIRM"):
    return {"original_assertion": text, "quantity_value": q, "quantity_unit": unit, "value_text": vt, "polarity": pol}


def test_same_sentence_different_parse_is_same():
    # 한 문장을 두 번 뽑으며 수치만 다르게 읽은 경우(250ml 와 50ml)
    a = _r("재료=코코넛베이스 250ml + 식힌 샷 50ml", Decimal("250"), "ml")
    b = _r("재료=코코넛베이스 250ml + 식힌 샷 50ml", Decimal("50"), "ml")
    assert same_statement(a, b)


def test_spacing_only_difference_is_same():
    assert same_statement(_r("토핑=치즈 큐브 6e a", vt="치즈 큐브 6e a"), _r("토핑=치즈큐브 6ea", vt="치즈큐브 6ea"))


def test_real_difference_is_not_same():
    assert not same_statement(_r("물=225ml", Decimal("225"), "ml"), _r("물=200ml", Decimal("200"), "ml"))


def test_same_value_different_wording_is_same():
    a = _r("물은 225ml", Decimal("225"), "ml")
    b = _r("물 225 ml 넣기", Decimal("225.0"), "ml")
    assert same_statement(a, b)


def test_opposite_polarity_is_not_same():
    assert not same_statement(_r("시럽=넣음", vt="넣음"), _r("시럽=넣음", vt="넣음", pol="NEGATE"))


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        assert "c.store_id = $1" in sql and args[0] == 7
        return self.rows


def _row(cid, low, lt, high, ht):
    return {"conflict_id": cid, "fact_id_low": low, "low_text": lt, "fact_id_high": high, "high_text": ht}


def test_load_hides_identical_and_merges_repeated_questions():
    rows = [
        _row(1, 10, "재료=요거트파우더 3래들", 11, "재료=요거 트파우더 3래들"),  # 띄어쓰기만 다름 → 숨김
        _row(2, 12, "토핑=휘핑 30g", 13, "토핑=휘핑 20g"),
        _row(3, 14, "토핑=휘핑 20g", 15, "토핑=휘핑  30g"),  # 위와 같은 질문 → 하나로
    ]
    items = asyncio.run(load_review_items(_Conn(rows), 7, [10, 11, 12, 13, 14, 15]))
    assert [i.conflict_id for i in items] == [2]


def test_invisible_characters_are_ignored():
    # PDF 에서 뽑힌 글에 섞이는 폭 0 공백·줄바꿈 금지 공백·BOM
    a = _r("재료=요거트파우더 3래들 + 가당딸기 150ml", Decimal("3"), "래들")
    b = _r("재료=요거​트파우더 3래들 +﻿ 가당딸기 150ml", Decimal("150"), "ml")
    assert same_statement(a, b)


def test_load_hides_pairs_differing_only_by_invisible_characters():
    rows = [_row(1, 10, "재료=요거트파우더 3래들", 11, "재료=요거​트파우더 3래들")]
    assert asyncio.run(load_review_items(_Conn(rows), 7, [10, 11])) == []
