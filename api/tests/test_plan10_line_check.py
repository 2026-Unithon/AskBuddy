"""계획 10 Task 3: 줄 검사(지어냄·빠뜨림). 문자열 검사이고 낱말 표가 없다."""
from app.ingest.line_check import check_line, numbers_in, uncovered_facts
from tests.helpers_plan_fact import pf


def test_numbers_in():
    assert numbers_in("가격 3,900원, 꿀 2래들 (샷잔 1/4선), 1.5P, 3~5분, ② 얼음") == {"3900", "2", "1/4", "1.5", "3", "5"}


def test_grounded_line_passes():
    facts = [pf(1, "샷=2", value="2"), pf(2, "재료=꿀 2래들 (샷잔 1/4선)", conditions=("샷잔 1/4선",))]
    assert check_line("2샷 내리고 꿀 2래들 투입 (샷잔 1/4선)", facts) is None


def test_invented_number_rejected():
    assert check_line("꿀 3래들 투입", [pf(2, "재료=꿀 2래들")]) == "LINE_INVENTED_NUMBER"


def test_invented_unit_rejected():
    assert check_line("물 1000g", [pf(3, "물 1000ml를 끓인다", value="1000", unit="ml")]) == "LINE_INVENTED_UNIT"


def test_unit_from_label_is_allowed():
    # '샷=2' 의 '샷' 은 사실 글에 있으니 '2샷' 을 쓸 수 있다(낱말로 분기하지 않는다).
    # 단, 숫자·단위만 있는 줄은 무엇인지 없어 실패(LINE_BARE_VALUE) — 하는 일과 함께 쓴다
    assert check_line("2샷 내리기", [pf(1, "샷=2", value="2")]) is None


def test_uncovered_values():
    facts = [pf(1, "샷=2", value="2"), pf(2, "금액=2,700원", value="2700"), pf(3, "얼음=가득")]
    lines = [("2샷", [1]), ("얼음 가득", [3]), ("가격", [2])]
    assert uncovered_facts(lines, facts) == [2]


def test_empty_line():
    assert check_line("  ", [pf(1, "샷=2", value="2")]) == "LINE_EMPTY"


def test_decimal_from_db_matches_plain_number():
    # DB numeric 은 1000.000 처럼 올 수 있다. 줄의 1000 과 같은 수다
    assert check_line("물 1000ml", [pf(3, "물 끓이기", value="1000.000", unit="ml")]) is None


def test_particle_after_unit_is_allowed():
    # 한글 단위 뒤 조사 한 글자는 단위가 아니다
    assert check_line("꿀 2래들을 넣는다", [pf(2, "꿀 2래들")]) is None


def test_condition_wording_is_not_checked():
    # D23 은 값(숫자)만 문자열로 본다. 조건·예외를 원문 말투로 바꿔 쓴 줄을 빠뜨림으로 보지 않는다
    # (2026-11-17 실측: 글자 그대로 요구하면 같은 뜻 원문 줄이 덧붙어 같은 말이 두 번 나왔다)
    facts = [pf(1, "오픈은 문 열고 들어오면 전원부터 켜", conditions=("오픈 시",)),
             pf(2, "시럽 없음", exceptions=("손님 요청 시",))]
    assert uncovered_facts([("문 열고 들어오면 전원부터 켜기", [1]), ("시럽은 넣지 않기", [2])], facts) == []


def test_row_number_in_source_is_not_a_value():
    # 표 한 행이 원문이면 맨 앞 행 번호(6)가 원문에 남는다. 값이 아니므로 줄에 없어도 빠뜨림이 아니다(2026-11-17 실측)
    from dataclasses import replace
    f = replace(pf(26, "6 합성 음료 HOT 잔 머그", value="머그"), assertion="HOT 합성 음료는 머그 잔을 써요.")
    assert uncovered_facts([("잔: 머그", [26])], [f]) == []


def test_value_number_still_required():
    from dataclasses import replace
    f = replace(pf(25, "5 합성 음료 HOT 온수량 180ml", value="180", unit="ml"), assertion="HOT 합성 음료의 온수량은 180ml예요.")
    assert uncovered_facts([("온수량 넉넉히", [25])], [f]) == [25]


def test_bare_value_line_rejected():
    # 숫자·단위만 남은 줄은 무엇의 값인지 알 수 없다(2026-11-17 사용자: '120ml 150g 2샷이 뭔지 알아?')
    facts = [pf(1, "합성 음료의 물량은 120ml", value="120", unit="ml"), pf(2, "가격=1,500원", value="1500")]
    assert check_line("120ml", facts) == "LINE_BARE_VALUE"
    assert check_line("1,500원", facts) == "LINE_BARE_VALUE"
    assert check_line("물 120ml", facts) is None
    assert check_line("가격 1,500원", facts) is None
