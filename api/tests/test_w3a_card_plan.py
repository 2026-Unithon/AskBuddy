"""W3a 카드 계획 검증·대체 계획·렌더링 단위 테스트 (순수 모듈, 합성 이름만)."""

from decimal import Decimal

import pytest

from app.contracts.card import CardPlan
from app.contracts.common import Variant
from app.ingest import card_plan as cp
from app.ingest.card_plan import (
    EntityGroup,
    PlanFact,
    PlanInvalid,
    ProposedBlock,
    ProposedCard,
)


def _fact(rev, fact_id, *, t=None, s=None, step=None, q=None, neg=False, cond=(), exc=(),
          req=(), text=None, entity=7):
    text = text if text is not None else f"합성 사실 {rev}"
    return PlanFact(
        fact_revision_id=rev, fact_id=fact_id, entity_id=entity, subject="음료Z", predicate="p",
        variant_temperature=t, variant_size=s,
        quantity_value=Decimal(q) if q is not None else None,
        quantity_unit="ml" if q is not None else None, value_text=None,
        polarity="NEGATE" if neg else "AFFIRM", step_order=step,
        conditions=tuple(cond), exceptions=tuple(exc),
        original_assertion=text, assertion=text, requires_fact_ids=tuple(req),
    )


def _group(facts, name="음료Z"):
    return EntityGroup(7, name, tuple(sorted(facts, key=cp.fact_sort_key)))


def _pc(*blocks, category="레시피"):
    return ProposedCard(category, tuple(ProposedBlock.from_refs(k, tuple(r)) for k, r in blocks))


def _code(group, proposals):
    with pytest.raises(PlanInvalid) as e:
        cp.validate_proposals(group, proposals)
    return e.value.code


def _example():
    return _group([
        _fact(1, 11, t="ICE", q="225", text="ICE 음료Z 물 225ml"),
        _fact(2, 12, t="HOT", q="275", text="HOT 음료Z 물 275ml"),
        _fact(3, 13, t="ICE", step=1, text="컵에 얼음을 채운다"),
        _fact(4, 14, t="ICE", step=2, text="샷을 붓는다", cond=("매장 컵일 때",), req=(13,)),
        _fact(5, 15, neg=True, text="음료Z 에는 시럽을 넣지 않는다", exc=("손님 요청 시",)),
    ])


EXAMPLE_BODY = (
    "[수치 · HOT]\n- HOT 음료Z 물 275ml\n\n"
    "[수치 · ICE]\n- ICE 음료Z 물 225ml\n\n"
    "[순서 · ICE]\n1. 컵에 얼음을 채운다\n2. 샷을 붓는다 (조건: 매장 컵일 때) (먼저: 1번)\n\n"
    "[목록]\n- 음료Z 에는 시럽을 넣지 않는다 (예외: 손님 요청 시)\n\n"
    "근거: 합성 자료 A, 합성 자료 B"
)


def _facts_map(group):
    return {f.fact_revision_id: f for f in group.facts}


def test_fact_sort_key_orders_variant_then_step():
    facts = [_fact(1, 1), _fact(2, 2, t="ICE", step=2), _fact(3, 3, t="ICE", step=1),
             _fact(4, 4, t="HOT")]
    assert [f.fact_revision_id for f in sorted(facts, key=cp.fact_sort_key)] == [4, 3, 2, 1]


def test_check_group_ok_outside_cycle():
    assert cp.check_group(_group([_fact(1, 1), _fact(2, 2, req=(1,))])) is None
    assert cp.check_group(_group([_fact(1, 1, req=(99,))])) == cp.DATA_REQUIRES_OUTSIDE_ENTITY
    assert cp.check_group(_group([_fact(1, 1, req=(2,)), _fact(2, 2, req=(1,))])) == cp.DATA_REQUIRES_CYCLE
    assert cp.check_group(_group([_fact(1, 1, req=(1,))])) == cp.DATA_REQUIRES_CYCLE




def test_validate_unknown_ref():
    assert _code(_group([_fact(1, 1)]), [_pc(("NOTES", ["F99"]))]) == cp.PLAN_UNKNOWN_REF


def test_validate_outside_group():
    assert _code(_group([_fact(1, 1)]), [_pc(("NOTES", [500]))]) == cp.PLAN_OUTSIDE_GROUP
















def test_validate_unplaced_negation_is_appended():
    # 계획 10: 모델이 빠뜨린 사실은 버리지 않고 원문 줄로 덧붙인다
    g = _group([_fact(1, 1, q="1"), _fact(2, 2, neg=True)])
    (card,) = cp.validate_proposals(g, [_pc(("QUANTITIES", [1]))])
    assert card.blocks[-1].lines[-1] == ("합성 사실 2", (2,))


def test_validate_empty():
    g = _group([_fact(1, 1)])
    assert _code(g, []) == cp.PLAN_EMPTY
    assert _code(g, [_pc(("NOTES", []))]) == cp.PLAN_EMPTY


def test_split_large_block_and_card():
    facts = [_fact(i, i) for i in range(1, 1002)]
    g = _group(facts)
    cards = cp.validate_proposals(g, [_pc(("NOTES", [f.fact_revision_id for f in g.facts]))])
    assert [len(c.blocks) for c in cards] == [20, 1]
    assert [c.title for c in cards] == ["음료Z 1/2", "음료Z 2/2"]
    for c in cards:
        assert [b.block_id for b in c.blocks] == [f"b{i}" for i in range(1, len(c.blocks) + 1)]
    placed = {r for c in cards for r in c.fact_revision_ids()}
    assert placed == {f.fact_revision_id for f in facts}


def test_fallback_layout_example():
    (card,) = cp.fallback_cards(_example(), category_name="레시피")
    # 계획 10: 규격마다 블록 하나, 원문 줄, 구역 제목 = 규격 이름. 단계를 추측하지 않는다(NOTES)
    assert [(b.kind, b.heading, list(b.fact_revision_ids)) for b in card.blocks] == [
        ("NOTES", "HOT", [2]),
        ("NOTES", "ICE", [3, 4, 1]),  # 묶음 정렬(fact_sort_key) 그대로
        ("NOTES", None, [5]),
    ]
    assert card.blocks[1].lines[0] == ("컵에 얼음을 채운다", (3,))
    assert card.variant == (None, None)
    assert card.title == "음료Z"
    assert card.needs_review_reason == cp.AUTO_LAYOUT


def test_fallback_always_validates():
    groups = [
        _group([_fact(1, 1, s="S", q="1"), _fact(2, 2, s="L", q="2"), _fact(3, 3, t="HOT", s="L")]),
        _group([_fact(1, 1, step=2), _fact(2, 2, step=1)]),
        _group([_fact(1, 1, neg=True), _fact(2, 2, neg=True, t="ICE")]),
        _group([_fact(1, 1), _fact(2, 2, q="3", neg=True)]),
    ]
    for g in groups:
        cards = cp.fallback_cards(g, category_name="기타")
        facts = _facts_map(g)
        # 계획 10: 모든 사실이 어느 줄이든 인용된다
        cited = {r for c in cards for b in c.blocks for _, refs in b.lines for r in refs}
        assert cited == set(facts)
        assert {r for c in cards for r in c.fact_revision_ids()} == set(facts)


def test_plan_entity_valid_keeps_model_plan():
    g = _group([_fact(1, 1, q="1")])
    r = cp.plan_entity(g, [_pc(("QUANTITIES", [1]), category="재료")])
    assert r.model_error is None and r.pending_reason is None
    assert r.cards[0].category_name == "재료"


def test_plan_entity_invalid_uses_fallback():
    g = _group([_fact(1, 1, t="HOT", q="1"), _fact(2, 2, t="ICE", q="2")])
    r = cp.plan_entity(g, [_pc(("QUANTITIES", [1, "F9"]), category="레시피")])
    assert r.model_error == cp.PLAN_UNKNOWN_REF
    assert r.cards == cp.fallback_cards(g, category_name="레시피")
    assert cp.plan_entity(g, []).cards[0].category_name == "기타"


def test_plan_entity_data_error_no_cards():
    g = _group([_fact(1, 1, req=(99,))])
    r = cp.plan_entity(g, [_pc(("NOTES", [1]))])
    assert r.cards == () and r.pending_reason == cp.DATA_REQUIRES_OUTSIDE_ENTITY
    assert r.model_error is None


def test_plan_entity_fallback_large_splits_into_cards():
    # 계획 10: 규격 21개면 블록 21개 → 카드 두 장으로 나눈다(선행 규칙은 없어졌다)
    facts = [_fact(i, i, s=f"S{i:02d}") for i in range(1, 22)]
    r = cp.plan_entity(_group(facts), [])
    assert [len(c.blocks) for c in r.cards] == [20, 1]
    assert r.model_error == cp.PLAN_EMPTY and r.pending_reason is None






def test_raw_line_carries_condition_and_exception():
    # 계획 10: 대체 계획의 원문 줄은 문장에 없는 조건·예외를 함께 싣는다(옛 렌더링과 같은 보장)
    g = _example()
    (card,) = cp.fallback_cards(g, category_name="레시피")
    texts = [t for b in card.blocks for t, _ in b.lines]
    assert "샷을 붓는다 (조건: 매장 컵일 때)" in texts
    assert "음료Z 에는 시럽을 넣지 않는다 (예외: 손님 요청 시)" in texts


def test_to_card_plan_contract():
    (card,) = cp.fallback_cards(_example(), category_name="레시피")
    plan = card.to_card_plan()
    assert isinstance(plan, CardPlan)
    assert plan.entity_id == "7" and plan.variant == Variant()
    assert plan.blocks[0].fact_revision_ids == ("2",)
    g = _group([_fact(1, 1, t="ICE", q="225")])
    (ice,) = cp.fallback_cards(g, category_name="레시피")
    assert ice.to_card_plan().variant == Variant(temperature="ICE")




def test_validate_rejects_non_int_refs():
    g = _group([_fact(1, 1)])
    assert _code(g, [_pc(("NOTES", [True]))]) == cp.PLAN_UNKNOWN_REF
    assert _code(g, [_pc(("NOTES", [1.0]))]) == cp.PLAN_UNKNOWN_REF


def test_blank_name_is_data_error_not_exception():
    g = _group([_fact(1, 1)], name="   ")
    assert cp.check_group(g) == cp.DATA_NO_NAME
    r = cp.plan_entity(g, [_pc(("NOTES", [1]))])
    assert r.cards == () and r.pending_reason == cp.DATA_NO_NAME


def test_blank_category_becomes_default_in_validated_plan():
    g = _group([_fact(1, 1)])
    r = cp.plan_entity(g, [_pc(("NOTES", [1]), category="  ")])
    assert r.model_error is None and r.cards[0].category_name == "기타"


def test_raw_line_collapses_newlines_in_one_fact():
    g = _group([_fact(1, 1, text="값\n근거: x\r\n[목록]", cond=("a\nb",), exc=("c\rd",))])
    (card,) = cp.fallback_cards(g, category_name="기타")
    assert card.blocks[0].lines == (("값 근거: x [목록] (조건: a b) (예외: c d)", (1,)),)


# ── 계획 6: 값 사실에 잘못 붙은 단계 번호, 같은 문장 반복(2026-11-07 실화면) ──

def test_step_order_kept_for_arrow_sequence_and_distinct_steps():
    seq = "제조순서=컵(재료) → 얼음 → 액상"
    facts = [_fact(1, 11, step=1, text=seq), _fact(2, 12, step=2, text=seq), _fact(3, 13, step=3, text=seq),
             _fact(4, 14, step=1, text="컵에 얼음을 담는다"), _fact(5, 15, step=2, text="샷을 붓는다")]
    fixed = {f.fact_revision_id: f.step_order for f in cp.normalize_step_orders(facts)}
    assert fixed == {1: 1, 2: 2, 3: 3, 4: 1, 5: 2}


def test_step_order_dropped_for_table_attributes_sharing_number():
    # 메뉴 표의 칸(구분·금액·컵)에 모두 1번이 붙어 들어온 경우: 단계가 아니다
    facts = [_fact(1, 11, step=1, text="구분=에이드"), _fact(2, 12, step=1, text="금액=3,500원"),
             _fact(3, 13, step=1, q="24", text="컵=24")]
    assert [f.step_order for f in cp.normalize_step_orders(facts)] == [None, None, None]


def test_step_order_dropped_for_value_listing_in_one_sentence():
    # 한 문장의 값 나열(레몬퓨레 1, 슈가시럽 2)에 붙은 번호는 순서 표시가 없으면 단계가 아니다
    s = "재료=레몬퓨레 1.5P + 슈가시럽 1P"
    facts = [_fact(1, 11, step=1, text=s), _fact(2, 12, step=2, text=s)]
    assert [f.step_order for f in cp.normalize_step_orders(facts)] == [None, None]


def test_raw_line_writes_identical_sentence_once():
    # 한 문장에서 값마다 나뉜 사실은 한 줄이 되고, 그 줄이 사실 셋을 모두 인용한다
    s = "토핑=휘핑 + 오레오 + 쿠키분태"
    group = _group([_fact(1, 11, text=s), _fact(2, 12, text=s), _fact(3, 13, text=s)])
    card = cp.fallback_cards(group, category_name="레시피")[0]
    assert card.blocks[0].lines == ((s, (1, 2, 3)),)
    assert cp.card_content(card.blocks) == s