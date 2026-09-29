"""W2-2 사실 열쇠 — 값 파싱·slot/identity 열쇠 (순수 함수, DB 없음)."""
from dataclasses import replace
from decimal import Decimal

from app.ingest.fact_keys import FactShape, canonical_unit, identity_key, parse_value, slot_key


def _shape(**kw) -> FactShape:
    base = dict(subject="음료Z", predicate="물", variant_temperature=None, variant_size=None,
                variant_other=None, quantity_value=Decimal("275"), quantity_unit="ml",
                value_text=None, polarity="AFFIRM", step_order=None, conditions=(),
                exceptions=(), original_assertion="음료Z 물 275ml", assertion="음료Z 물 275ml")
    base.update(kw)
    return FactShape(**base)


def test_parse_value_number_with_unit():
    assert parse_value("275", "ml") == (Decimal("275"), "ml", None)


def test_parse_value_decimal_and_unit_alias_is_same_identity():
    q1, u1, t1 = parse_value("275", "ml")
    q2, u2, t2 = parse_value("275.0", "㎖")
    assert u2 == "ml" and t2 is None
    a = _shape(quantity_value=q1, quantity_unit=u1, value_text=t1)
    b = _shape(quantity_value=q2, quantity_unit=u2, value_text=t2)
    assert identity_key(1, a) == identity_key(1, b)


def test_parse_value_unit_glued_to_number():
    assert parse_value("20ml", "") == (Decimal("20"), "ml", None)


def test_parse_value_glued_unit_matches_unit_argument():
    # 값에 붙은 단위와 단위 칸이 같으면 수치로 본다 ("20ml ml" 서술값이 아니다)
    assert parse_value("20ml", "ml") == (Decimal("20"), "ml", None)
    assert parse_value("20㎖", "밀리리터") == (Decimal("20"), "ml", None)
    assert parse_value("3 샷", "샷") == (Decimal("3"), "샷", None)


def test_parse_value_glued_unit_same_identity_as_split():
    q1, u1, t1 = parse_value("20ml", "ml")
    q2, u2, t2 = parse_value("20", "ml")
    a = _shape(quantity_value=q1, quantity_unit=u1, value_text=t1)
    b = _shape(quantity_value=q2, quantity_unit=u2, value_text=t2)
    assert identity_key(1, a) == identity_key(1, b)


def test_parse_value_glued_unit_differs_from_unit_argument_stays_text():
    # 붙은 단위와 단위 칸이 다르면 어느 쪽이 맞는지 모른다 — 서술값으로 남긴다
    assert parse_value("20ml", "g") == (None, None, "20ml g")


def test_parse_value_european_decimal_is_known_limit():
    # 쉼표는 천 단위 구분으로만 본다. "1,5" 는 15 가 된다 — 알려진 한계
    assert parse_value("1,5", "l") == (Decimal("15"), "l", None)


def test_parse_value_thousands_separator():
    q, u, t = parse_value("1,000", "g")
    assert q == Decimal("1000") and u == "g" and t is None


def test_parse_value_range_is_text():
    assert parse_value("2~3", "개") == (None, None, "2~3 개")


def test_parse_value_word_is_text():
    assert parse_value("반", "컵") == (None, None, "반 컵")


def test_canonical_unit_table_and_fallback():
    assert canonical_unit("밀리리터") == "ml"
    assert canonical_unit("℃") == "°c"
    assert canonical_unit(" 샷 ") == "샷"
    assert canonical_unit("") is None and canonical_unit(None) is None


def test_hot_vs_ice_same_value_are_different_slots():
    hot, ice = _shape(variant_temperature="HOT"), _shape(variant_temperature="ICE")
    assert slot_key(1, hot) != slot_key(1, ice)
    assert identity_key(1, hot) != identity_key(1, ice)


def test_null_variant_and_ice_are_different_slots():
    assert slot_key(1, _shape()) != slot_key(1, _shape(variant_temperature="ICE"))


def test_value_only_differs_same_slot_different_identity():
    a, b = _shape(), _shape(quantity_value=Decimal("225"))
    assert slot_key(1, a) == slot_key(1, b)
    assert identity_key(1, a) != identity_key(1, b)


def test_polarity_only_differs_same_slot_different_identity():
    a, b = _shape(), _shape(polarity="NEGATE")
    assert slot_key(1, a) == slot_key(1, b)
    assert identity_key(1, a) != identity_key(1, b)


def test_condition_order_does_not_matter():
    a = _shape(conditions=("포장 주문일 때", "여름"))
    b = _shape(conditions=("여름", "포장 주문일 때"))
    assert identity_key(1, a) == identity_key(1, b)


def test_step_order_differs_different_slot():
    assert slot_key(1, _shape(step_order=1)) != slot_key(1, _shape(step_order=2))


def test_unit_differs_different_identity():
    assert identity_key(1, _shape()) != identity_key(1, _shape(quantity_unit="g"))


def test_variant_other_present_vs_absent_different_slot():
    assert slot_key(1, _shape()) != slot_key(1, _shape(variant_other="디카페인"))


def test_entity_is_part_of_the_slot():
    assert slot_key(1, _shape()) != slot_key(2, _shape())


def test_predicate_whitespace_and_case_do_not_matter():
    a, b = _shape(predicate="Water Amount"), _shape(predicate="water  amount")
    assert slot_key(1, a) == slot_key(1, b)


def test_text_value_spacing_does_not_matter():
    a = _shape(quantity_value=None, quantity_unit=None, value_text="반  컵")
    b = replace(a, value_text="반 컵")
    assert identity_key(1, a) == identity_key(1, b)
