"""계획 10 Task 4: 모델이 구역·줄을 쓰고 서버는 지어냄·빠뜨림만 막는다."""
from pathlib import Path

from app.ingest import card_plan
from app.ingest.card_plan import ProposedBlock, ProposedCard, ProposedLine
from tests.helpers_plan_fact import group, pf

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "assemble_card_plan.ko.txt"


def test_free_layout_is_accepted():
    # 표 칸에 order 가 붙어 있어도 모델이 쓴 구역·줄을 그대로 받는다
    g = group(1, "합성 딸기 음료", [pf(1, "구분=스무디", step=1), pf(2, "금액=3,900원", step=3, value="3900"),
                                  pf(3, "블랜더(액상,재료,얼음)", step=1), pf(4, "믹싱", step=2)])
    p = ProposedCard(category_name="음료제작", blocks=(
        ProposedBlock(kind="STEPS", heading="만들기", lines=(ProposedLine("블랜더에 액상, 재료, 얼음", (3,)), ProposedLine("믹싱", (4,)))),
        ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("가격 3,900원", (2,)), ProposedLine("스무디", (1,)))),))
    result = card_plan.plan_entity(g, [p])
    assert result.model_error is None
    assert [b.heading for b in result.cards[0].blocks] == ["만들기", None]
    assert result.cards[0].blocks[0].lines[0] == ("블랜더에 액상, 재료, 얼음", (3,))


def test_bad_line_falls_back_to_assertions():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2")])
    p = ProposedCard(category_name="음료제작", blocks=(ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("3샷", (1,)),)),))
    lines = card_plan.plan_entity(g, [p]).cards[0].blocks[0].lines
    assert lines == (("샷=2", (1,)),)


def test_missing_fact_appended():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2"), pf(2, "얼음=가득")])
    p = ProposedCard(category_name="음료제작", blocks=(ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("2샷", (1,)),)),))
    lines = card_plan.plan_entity(g, [p]).cards[0].blocks[0].lines
    assert lines[-1] == ("얼음=가득", (2,))


def test_cited_but_value_dropped_is_appended_to_its_block():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2"), pf(2, "금액=2,700원", value="2700")])
    p = ProposedCard(category_name="음료제작", blocks=(
        ProposedBlock(kind="STEPS", heading="만들기", lines=(ProposedLine("2샷", (1,)),)),
        ProposedBlock(kind="NOTES", heading="가격", lines=(ProposedLine("가격", (2,)),)),
        ProposedBlock(kind="NOTES", heading="보관", lines=(ProposedLine("2샷 보관", (1,)),))))
    blocks = card_plan.plan_entity(g, [p]).cards[0].blocks
    assert blocks[1].lines == (("가격", (2,)), ("금액=2,700원", (2,)))


def test_one_fact_on_two_lines_is_allowed():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2")])
    p = ProposedCard(category_name="음료제작", blocks=(
        ProposedBlock(kind="STEPS", heading="HOT", lines=(ProposedLine("2샷", (1,)),)),
        ProposedBlock(kind="STEPS", heading="ICE", lines=(ProposedLine("2샷", (1,)),))))
    result = card_plan.plan_entity(g, [p])
    assert result.model_error is None
    assert [b.fact_revision_ids for b in result.cards[0].blocks] == [(1,), (1,)]


def test_unknown_ref_falls_back():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2")])
    p = ProposedCard(category_name="음료제작", blocks=(ProposedBlock(kind="NOTES", heading=None, lines=(ProposedLine("2샷", ("F9",)),)),))
    result = card_plan.plan_entity(g, [p])
    assert result.model_error == "PLAN_UNKNOWN_REF"
    assert result.cards[0].needs_review_reason == "AUTO_LAYOUT"


def test_model_failure_uses_fallback_with_lines():
    g = group(1, "합성 알갱이", [pf(1, "물 1000ml를 끓인다", step=1, value="1000"), pf(2, "보관은 24시간")])
    card = card_plan.plan_entity(g, []).cards[0]
    assert card.needs_review_reason == "AUTO_LAYOUT"
    assert [l[0] for b in card.blocks for l in b.lines] == ["물 1000ml를 끓인다", "보관은 24시간"]


def test_fallback_heading_is_variant_name():
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2", variant=("HOT", None)), pf(2, "샷=3", value="3", variant=("ICE", None))])
    card = card_plan.plan_entity(g, []).cards[0]
    assert [b.heading for b in card.blocks] == ["HOT", "ICE"]


def test_prompt_rules_present():
    text = PROMPT.read_text(encoding="utf-8")
    for needle in ["heading", "lines", "2샷", "꿀 2래들 투입 (샷잔 1/4선)", "예시", "인용한 사실에 있는 것만", "모든 사실"]:
        assert needle in text, needle
    assert "새 문장·제목·값·숫자·단위·조건·예외를 쓰지 않는다" not in text  # 옛 규칙 제거


def test_append_keeps_existing_lines_and_adds_raw_line():
    # 공개 판에 새 사실만 붙일 때, 모델·사장님이 쓴 줄은 그대로 두고 새 사실은 원문 줄로 붙인다
    g = group(1, "합성 꿀 커피", [pf(1, "샷=2", value="2"), pf(2, "얼음=가득")])
    card = card_plan.append_facts(
        [("NOTES", (1,))], g, [2], category_name="음료제작",
        display=[("HOT", (("투샷으로", (1,)),))])
    assert card.blocks[0].heading == "HOT"
    assert card.blocks[0].lines == (("투샷으로", (1,)), ("얼음=가득", (2,)))
