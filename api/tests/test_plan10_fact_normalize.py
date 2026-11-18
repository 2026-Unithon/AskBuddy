"""계획 10 Task 6: 추출 직후 서버 보정 — 표 칸의 order 지우기, 반복된 화살표 통문장 나누기."""
from app.ingest.fact_normalize import normalize_extracted
from tests.helpers_plan_fact import ea


def test_table_cell_loses_order():
    # ExtractedAssertion.order 는 int 이고 '순서 없음' 은 0 이다(응답 스키마 불변)
    out = normalize_extracted([ea("구분=스무디", order=1), ea("금액=3,900원", order=3)])
    assert [f.order for f in out] == [0, 0]


def test_repeated_arrow_sentence_is_split():
    s = "제조순서=블랜더 → 믹싱 → 토핑"
    out = normalize_extracted([ea(s, order=1, value="블랜더"), ea(s, order=2, value="믹싱"), ea(s, order=5, value="토핑")])
    assert [(f.assertion, f.order) for f in out] == [("블랜더", 1), ("믹싱", 2), ("토핑", 3)]
    assert all(f.original_assertion == s for f in out)  # 원문은 남는다


def test_arrow_step_keeps_order():
    out = normalize_extracted([ea("블랜더(재료,얼음)", order=1)])
    assert out[0].order == 1


def test_arrow_sentence_with_unmatched_value_is_left_alone():
    # 값이 조각과 맞지 않으면 손대지 않는다(추측하지 않는다)
    s = "제조순서=블랜더 → 믹싱"
    out = normalize_extracted([ea(s, order=1, value="블랜더"), ea(s, order=2, value="다른 값")])
    assert [(f.assertion, f.order) for f in out] == [(s, 1), (s, 2)]
