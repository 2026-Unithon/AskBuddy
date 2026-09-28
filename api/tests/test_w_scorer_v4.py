"""채점기 v4 — 공통/업종 규칙 분리와 속성 관계 교정의 합성 회귀.

실제 평가 자료는 읽지 않는다. 사람이 '다른 뜻'으로 판정한 유형(프로그램 번호 3 ≠ 3잔,
250g 투입 ≠ 250g 소분)은 계속 막고, 사람이 '맞다'고 한 유형만 새로 통과시킨다.
"""
import pytest

from app.team.extraction import _subject_scope, match_fact, requires_ice_label, variant_present
from app.team.scoring_rules import CAFE, COMMON, DEFAULT_RULES, ScoringRules, rules_for


def card(content, title="", id=1):
    return {"card_id": id, "title": title, "content": content}


def fact(subject, attribute, value, **extra):
    return {"subject": subject, "attribute": attribute, "value": value, **extra}


# --- 공통 + 업종 규칙 ---------------------------------------------------------

def test_common_rules_have_no_cafe_expressions():
    assert "HOT" not in COMMON.variant_synonyms and not COMMON.label_rules
    assert "우유량" not in COMMON.attribute_markers


def test_domain_rules_extend_common():
    cafe = rules_for("CAFE")
    assert set(COMMON.attribute_markers) <= set(cafe.attribute_markers)
    assert "우유량" in cafe.attribute_markers and cafe.variant_synonyms["ICE"]
    assert cafe.domain == "COMMON+CAFE" and DEFAULT_RULES == cafe
    assert rules_for(None) is COMMON


def test_unknown_domain_and_common_override_are_rejected():
    with pytest.raises(ValueError):
        rules_for("BAKERY")
    from app.team import scoring_rules
    bad = ScoringRules("BAD", attribute_markers={"보관위치": ("다른말",)})
    scoring_rules.DOMAIN_EXTRAS["BAD"] = bad
    try:
        with pytest.raises(ValueError):
            rules_for("BAD")
    finally:
        del scoring_rules.DOMAIN_EXTRAS["BAD"]


def test_ice_label_is_a_cafe_rule_only():
    f = fact("음료A", "우유량", "225ml", variant="ICE")
    assert requires_ice_label(f, rules_for("CAFE")) is True
    assert requires_ice_label(f, COMMON) is False
    assert variant_present("HOT", "따뜻한 음료A", CAFE) is True
    assert variant_present("HOT", "따뜻한 음료A", COMMON) is False


# --- 속성 관계 교정 ------------------------------------------------------------

def test_attribute_label_absent_but_value_bound_in_subject_sentence():
    f = fact("재료A", "안전보관일", "제조 후 24시간")
    assert match_fact(f, [card("재료A는 제조 후 24시간 동안 사용합니다.")]).verdict == "COVERED"


def test_counter_must_stay_bound_to_its_number():
    # 3잔을 한 번에 만든다 ≠ 블렌더 3번 프로그램
    f = fact("블렌더", "1회 제조 잔 수", "3잔을 한 번에 갈아 나눠 담는다")
    assert match_fact(f, [card("블렌더 3번으로 믹싱 후 컵에 부어 제공합니다.")]).verdict != "COVERED"


def test_attribute_with_fixed_expression_stays_strict():
    # 250g 소분 ≠ 250g 투입 — '소분' 표현이 정해진 속성은 값만으로 인정하지 않는다
    f = fact("재료B", "소분 단위", "250g")
    assert match_fact(f, [card("끓는 물에 재료B 250g을 넣고 삶습니다.")]).verdict != "COVERED"


def test_value_in_other_subject_sentence_is_not_borrowed():
    f = fact("재료A", "안전보관일", "3일")
    content = "재료A는 5일간 사용합니다. 재료B는 3일간 사용합니다."
    assert match_fact(f, [card(content)]).verdict != "COVERED"


def test_attribute_expression_ignores_spacing():
    f = fact("품목A 발주", "발주요일", "화요일")
    assert match_fact(f, [card("품목A 발주 요일은 화요일 오전입니다.")]).verdict == "COVERED"


def test_omitted_subject_in_next_sentence_without_numbers():
    f = fact("환불", "처리주체", "점주에게 전화 후 처리")
    content = "환불 요청 시 직원 혼자 처리해서는 안 됩니다. 반드시 점주 전화 확인 후 처리해야 합니다."
    assert match_fact(f, [card(content)]).verdict == "COVERED"


def test_next_sentence_with_numbers_is_not_in_subject_scope():
    clauses = ["재료A는 냉장 보관합니다", " 2번 선반에 둡니다", " 끝"]
    assert _subject_scope("재료A", clauses) == ["재료A는 냉장 보관합니다"]


def test_sequence_value_compares_order():
    f = fact("음료A", "제조순서", "얼음 → 물 → 샷 순으로 붓는다")
    right = card("음료A 제조 순서는 1단계 얼음 넣기, 2단계 물 넣기, 3단계 샷 넣기 순으로 진행합니다.")
    wrong = card("음료A 제조 순서는 샷을 먼저 넣고 물, 얼음 순으로 진행합니다.")
    assert match_fact(f, [right]).verdict == "COVERED"
    assert match_fact(f, [wrong]).verdict != "COVERED"


def test_negation_still_blocks_after_calibration():
    f = fact("음료A", "한도", "최대 3샷")
    content = "음료A 샷 추가는 최대 2샷까지 가능합니다. 3샷 이상은 접수하지 않습니다."
    assert match_fact(f, [card(content)]).verdict != "COVERED"


def test_stated_variant_defaults_to_specific():
    from app.team.extraction import applicability
    assert applicability({"variant": "HOT"}, True) == "SPECIFIC"
    assert applicability({}, True) == "UNKNOWN"
    assert applicability({"variant": "HOT", "applicability": "COMMON"}, True) == "COMMON"
    assert applicability({"variant": "HOT"}, False) == "NOT_APPLICABLE"


def test_specific_fact_needs_its_variant_on_the_card():
    from app.team.extraction import applicability
    f = fact("음료A", "샷 수", "2샷", variant="HOT")
    f = {**f, "applicability": applicability(f, True)}
    assert match_fact(f, [card("HOT 음료A는 2샷을 넣습니다.")]).verdict == "COVERED"
    assert match_fact(f, [card("음료A는 2샷을 넣습니다.")]).verdict == "PARTIAL"
    assert match_fact(f, [card("ICE 음료A는 2샷을 넣습니다.")]).verdict != "COVERED"
