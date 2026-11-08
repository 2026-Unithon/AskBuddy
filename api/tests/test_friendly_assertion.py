"""사람이 읽기 좋은 사실 문장(2026-11-08 사용자: '원문 그대로' 규칙 제거).

원문은 근거로 남기고, 모델이 정리한 문장은 숫자가 원문과 맞을 때만 보이는 문장으로 쓴다(지어내기 막기).
"""
from app.ingest.friendly import friendly_assertion


def test_tidied_sentence_is_used():
    original = "너무 좀 많이 나간다 싶으면 나한테 말해 내가 추가로 시킬게"
    tidy = "우유가 많이 나가면 사장님께 말해 주세요. 사장님이 추가로 주문해요."
    assert friendly_assertion(tidy, original, value="", unit="") == tidy


def test_new_number_falls_back_to_original():
    original = "우유는 일주일에 두 번 월요일이랑 목요일"
    assert friendly_assertion("우유는 주 3회 발주해요.", original, value="", unit="") == original


def test_value_must_survive():
    original = "샷은 2번 넣어"
    assert friendly_assertion("샷을 넣어요.", original, value="2", unit="번") == original
    assert friendly_assertion("샷을 2번 넣어요.", original, value="2", unit="번") == "샷을 2번 넣어요."


def test_number_formats_compare_by_value():
    original = "금액=3,900원"
    assert friendly_assertion("가격은 3900원이에요.", original, value="3,900", unit="원") == "가격은 3900원이에요."


def test_empty_or_too_long_falls_back():
    original = "컵=20"
    assert friendly_assertion("", original, value="20", unit="") == original
    assert friendly_assertion("가" * 400, original, value="20", unit="") == original


from app.ingest.entity_names import parse_variant
from app.ingest.fact_keys import shape_from_ledger


def ledger_row(**kw):
    row = dict(subject="우유", attribute="발주 요일", value="월요일, 목요일", unit=None, polarity="AFFIRM",
               step_order=None, conditions="[]", exceptions="[]", variant=None,
               original_assertion="우유 같은 경우에는 일주일에 두 번 월요일이랑 목요일", assertion=None)
    row.update(kw)
    return row


def test_ledger_shape_uses_checked_friendly_sentence():
    shape, _ = shape_from_ledger(ledger_row(assertion="우유는 월요일과 목요일, 일주일에 두 번 발주해요."), parse_variant(None), None, None)
    assert shape.assertion == "우유는 월요일과 목요일, 일주일에 두 번 발주해요."
    assert shape.original_assertion.startswith("우유 같은 경우에는")


def test_ledger_shape_without_friendly_keeps_original():
    shape, _ = shape_from_ledger(ledger_row(), parse_variant(None), None, None)
    assert shape.assertion == shape.original_assertion
