"""사용자 확정 원칙의 합성 회귀. 실제 dev 표본/원본은 테스트에서 읽지 않는다."""
import copy
import pytest
from app.team.extraction import (ExtractionReport, aggregate, match_fact, score_expected_fact,
                                requires_ice_label, apply_evaluation_policy)
from app.team.repeat_metrics import compare_repeats


def card(id, title, content):
    return {"card_id": id, "title": title, "content": content}


def fact(**changes):
    return dict({"fact_id": "synthetic", "subject": "음료Z", "attribute": "우유량",
                 "value": "180ml", "variant": "HOT", "applicability": "NOT_APPLICABLE",
                 "must_have": False}, **changes)


def test_explicit_opposite_variant_cannot_win_when_axis_is_absent():
    cards = [card(1, "음료Z ICE", "우유량 180ml"), card(2, "음료Z HOT", "우유량 180ml")]
    assert match_fact(fact(), cards, require_variant=False).card_id == 2
    assert match_fact(fact(), cards[:1], require_variant=False).verdict != "COVERED"


@pytest.mark.parametrize("title,verdict", [("음료Z", "PARTIAL"), ("음료Z 아이스", "PARTIAL"),
                                         ("음료Z ICE", "COVERED")])
def test_ice_label_is_required_even_without_variant_axis(title, verdict):
    assert match_fact(fact(variant="ICE"), [card(1, title, "우유량 180ml")], require_variant=False).verdict == verdict


@pytest.mark.parametrize("assertion,expected", [("얼음을 넣는다", True), ("얼음과 함께 갈아 만든다", True),
                                               ("얼음을 넣지 않는다", False), ("얼음이 없으면 물을 넣는다", False)])
def test_affirmative_recipe_ice_evidence(assertion, expected):
    f = fact(variant=None, category_hint="음료제작", original_assertion=assertion)
    assert requires_ice_label(f) is expected
    assert requires_ice_label({**f, "category_hint": "청소"}) is False


def test_unrelated_subject_number_cannot_displace_location_card():
    f = fact(subject="재료Z", attribute="보관위치", value="4번 냉장고", variant=None)
    cards = [card(1, "음료Q 레시피", "샷 수 4샷"), card(2, "재료Z 보관 위치", "4번 냉장고에 보관합니다")]
    assert match_fact(f, cards).card_id == 2


def test_subject_value_binding_between_clauses():
    f = fact(subject="재료Z", attribute="보관위치", value="4번 냉장고", variant=None)
    c = card(1, "재료 보관", "재료Z의 보관위치는 2번 냉장고이며 재료Q의 보관위치는 4번 냉장고입니다")
    assert match_fact(f, [c]).verdict != "COVERED"


def test_closing_value_not_borrowed_from_last_order():
    f = fact(subject="영업", attribute="종료시각", value="20:00", variant=None)
    c = card(1, "매장 영업", "영업 종료 시각은 20:30입니다. 라스트오더는 20:00입니다")
    assert match_fact(f, [c]).verdict != "COVERED"


def test_clause_filter_does_not_hide_following_correction():
    c = card(1, "음료Z HOT", "우유량 180ml입니다. 이 수치는 잘못된 값입니다. 200ml를 사용합니다")
    assert match_fact(fact(), [c]).verdict != "COVERED"


def test_reference_to_closing_does_not_relabel_last_order_time():
    f = fact(subject="영업", attribute="종료시각", value="20:00", variant=None)
    wrong = card(1, "영업 종료 및 주문", "영업 종료 시각은 20:30입니다. 20:00부터 영업 종료 전까지 라스트오더 안내 후 주문을 받습니다")
    right = card(2, "매장 마감", "매장 마감 시간은 20:00입니다. 이후에는 주문을 받지 않습니다")
    assert match_fact(f, [wrong]).verdict != "COVERED"
    assert match_fact(f, [wrong, right]).card_id == 2


def test_attribute_candidate_wins_over_unrelated_number_even_when_value_is_missing():
    f = fact(subject="재료Z", attribute="보관위치", value="4번 냉장고", variant=None)
    cards = [card(1, "재료Z 우유 투입", "샷 4개"), card(2, "재료Z 보관 위치", "2번 냉장고에 보관합니다")]
    assert match_fact(f, cards).card_id == 2


@pytest.mark.parametrize("attribute,value,content", [("소분 단위", "180g", "재료Z 180g을 넣어 삶습니다"),
                                                   ("침지시간", "18분", "재료Z에 물을 18초간 흘립니다")])
def test_quantity_role_and_unit_are_not_interchangeable(attribute, value, content):
    assert match_fact(fact(subject="재료Z", attribute=attribute, value=value, variant=None),
                      [card(1, "재료Z 처리", content)]).verdict != "COVERED"


def correction():
    latest = fact(fact_id="new", subject="재료Z", attribute="보관위치", value="4번 냉장고", variant=None)
    previous = {**latest, "fact_id": "old", "value": "2번 냉장고", "attribute": "보관위치(이전)",
                "expectation": "ABSENT", "superseded_by": "new"}
    return previous, latest


def test_corrected_only_card_passes_exclusion_without_recall_credit():
    old, latest = correction()
    cards = [card(1, "재료Z 보관 위치", "4번 냉장고에 보관합니다")]
    m = score_expected_fact(old, cards, [old, latest])
    assert m.verdict == "COVERED"
    report = ExtractionReport()
    report.add(old, m, "KAKAO")
    report.add(latest, match_fact(latest, cards), "KAKAO")
    metrics = aggregate(report.rows)
    assert metrics["fact_count"] == 1 and metrics["covered"] == 1
    assert metrics["expected_exclusions"] == 1 and metrics["expected_exclusions_failed_ids"] == []


def test_retained_previous_or_missing_latest_cannot_pass():
    old, latest = correction()
    old_card = card(1, "재료Z 보관 위치", "2번 냉장고에 보관합니다")
    new_card = card(2, "재료Z 보관 위치", "4번 냉장고에 보관합니다")
    assert score_expected_fact(old, [old_card, new_card], [old, latest]).verdict != "COVERED"
    assert score_expected_fact(old, [], [old, latest]).verdict != "COVERED"
    assert score_expected_fact(old, [new_card], [old]).verdict == "UNDETERMINED"


def test_exclusion_is_separate_from_performance_and_blocks_repeat_safety():
    old, latest = correction()
    base = [{"old": "COVERED", "new": "COVERED"}] * 3
    candidate = [*base[:2], {"old": "PARTIAL", "new": "COVERED"}]
    result = compare_repeats(base, candidate, [old, latest])
    assert result["denominator"] == 1 and result["median_delta"] == 0
    assert result["safety_passed"] is False and result["expected_exclusions_failed_ids"] == ["old"]


def test_policy_preserves_snapshot_and_cannot_rewrite_values():
    old, latest = correction()
    truth = [old, latest]
    before = copy.deepcopy(truth)
    apply_evaluation_policy(truth, {"old": {"expectation": "ABSENT", "superseded_by": "new"}})
    assert truth == before
    with pytest.raises(ValueError):
        apply_evaluation_policy(truth, {"old": {"value": "99번 냉장고"}})
