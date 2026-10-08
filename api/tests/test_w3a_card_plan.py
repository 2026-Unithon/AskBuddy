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
    return ProposedCard(category, tuple(ProposedBlock(k, tuple(r)) for k, r in blocks))


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


def test_validate_reorders_sections_and_numbers_blocks():
    g = _group([_fact(1, 1, q="1"), _fact(2, 2, step=1), _fact(3, 3)])
    (card,) = cp.validate_proposals(
        g, [_pc(("NOTES", [3]), ("STEPS", [2]), ("QUANTITIES", [1]))])
    assert [b.kind for b in card.blocks] == ["QUANTITIES", "STEPS", "NOTES"]
    assert [b.block_id for b in card.blocks] == ["b1", "b2", "b3"]
    assert [b.order for b in card.blocks] == [1, 2, 3]


def test_validate_unknown_ref():
    assert _code(_group([_fact(1, 1)]), [_pc(("NOTES", ["F99"]))]) == cp.PLAN_UNKNOWN_REF


def test_validate_outside_group():
    assert _code(_group([_fact(1, 1)]), [_pc(("NOTES", [500]))]) == cp.PLAN_OUTSIDE_GROUP


def test_validate_kind_mismatch():
    g = _group([_fact(1, 1, step=1), _fact(2, 2)])
    assert _code(g, [_pc(("QUANTITIES", [1]), ("NOTES", [2]))]) == cp.PLAN_KIND_MISMATCH
    assert _code(g, [_pc(("STEPS", [2]), ("STEPS", [1]))]) == cp.PLAN_KIND_MISMATCH
    assert _code(g, [_pc(("RAW", [1]), ("NOTES", [2]))]) == cp.PLAN_KIND_MISMATCH


def test_validate_hot_ice_swap_blocked():
    g = _group([_fact(1, 1, t="HOT", q="1"), _fact(2, 2, t="ICE", q="2")])
    assert _code(g, [_pc(("QUANTITIES", [1, 2]))]) == cp.PLAN_VARIANT_MIXED


def test_validate_null_variant_not_wildcard():
    g = _group([_fact(1, 1, q="1"), _fact(2, 2, t="ICE", q="2")])
    assert _code(g, [_pc(("QUANTITIES", [1, 2]))]) == cp.PLAN_VARIANT_MIXED


def test_validate_step_order():
    g = _group([_fact(1, 1, step=1), _fact(2, 2, step=2)])
    assert _code(g, [_pc(("STEPS", [2, 1]))]) == cp.PLAN_STEP_ORDER
    g2 = _group([_fact(1, 1, step=1), _fact(2, 2, step=2), _fact(3, 3, step=2)])
    (card,) = cp.validate_proposals(g2, [_pc(("STEPS", [1, 2, 3]))])
    assert card.blocks[0].fact_revision_ids == (1, 2, 3)


def test_validate_steps_incomplete():
    g = _group([_fact(1, 1, t="ICE", step=1), _fact(2, 2, t="ICE", step=2),
                _fact(3, 3, t="ICE", step=3)])
    props = [_pc(("STEPS", [1, 3])), _pc(("STEPS", [2]))]
    assert _code(g, props) == cp.PLAN_STEPS_INCOMPLETE


def test_validate_requires_missing():
    g = _group([_fact(1, 1, t="ICE", step=1), _fact(2, 2, step=2, t="ICE", req=(9,)),
                _fact(3, 9)])
    # 단계 2 의 선행 X(fact 9) 가 다른 카드에 있다
    assert _code(g, [_pc(("STEPS", [1, 2])), _pc(("NOTES", [3]))]) == cp.PLAN_REQUIRES_MISSING


def test_validate_duplicate_in_card_and_across_cards():
    g = _group([_fact(1, 1), _fact(2, 2)])
    assert _code(g, [_pc(("NOTES", [1, 2]), ("QUANTITIES", [1]))]) == cp.PLAN_DUPLICATE_IN_CARD
    cards = cp.validate_proposals(g, [_pc(("NOTES", [1, 2])), _pc(("NOTES", [1]))])
    assert [c.title for c in cards] == ["음료Z 1/2", "음료Z 2/2"]


def test_validate_unplaced_negation():
    g = _group([_fact(1, 1, q="1"), _fact(2, 2, neg=True)])
    assert _code(g, [_pc(("QUANTITIES", [1]))]) == cp.PLAN_UNPLACED


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
    facts[-1] = _fact(1001, 1001, req=(1,))
    g2 = _group(facts)
    assert _code(g2, [_pc(("NOTES", [f.fact_revision_id for f in g2.facts]))]) == cp.PLAN_REQUIRES_MISSING


def test_fallback_layout_example():
    (card,) = cp.fallback_cards(_example(), category_name="레시피")
    assert [(b.kind, b.variant, list(b.fact_revision_ids)) for b in card.blocks] == [
        ("QUANTITIES", ("HOT", None), [2]),
        ("QUANTITIES", ("ICE", None), [1]),
        ("STEPS", ("ICE", None), [3, 4]),
        ("NOTES", (None, None), [5]),
    ]
    assert card.variant == (None, None)
    assert card.title == "음료Z"


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
        for c in cards:
            assert cp.render_missing(c, facts, cp.render_card(c, facts)) == []
        assert {r for c in cards for r in c.fact_revision_ids()} == set(facts)


def test_plan_entity_valid_keeps_model_plan():
    g = _group([_fact(1, 1, q="1")])
    r = cp.plan_entity(g, [_pc(("QUANTITIES", [1]), category="재료")])
    assert r.model_error is None and r.pending_reason is None
    assert r.cards[0].category_name == "재료"


def test_plan_entity_invalid_uses_fallback():
    g = _group([_fact(1, 1, t="HOT", q="1"), _fact(2, 2, t="ICE", q="2")])
    r = cp.plan_entity(g, [_pc(("QUANTITIES", [1, 2]), category="레시피")])
    assert r.model_error == cp.PLAN_VARIANT_MIXED
    assert r.cards == cp.fallback_cards(g, category_name="레시피")
    assert cp.plan_entity(g, []).cards[0].category_name == "기타"


def test_plan_entity_data_error_no_cards():
    g = _group([_fact(1, 1, req=(99,))])
    r = cp.plan_entity(g, [_pc(("NOTES", [1]))])
    assert r.cards == () and r.pending_reason == cp.DATA_REQUIRES_OUTSIDE_ENTITY
    assert r.model_error is None


def test_plan_entity_fallback_too_large():
    facts = [_fact(i, i, s=f"S{i:02d}") for i in range(1, 22)]
    facts[-1] = _fact(21, 21, s="S21", req=(1,))
    g = _group(facts)
    r = cp.plan_entity(g, [])
    assert r.cards == () and r.pending_reason == cp.DATA_TOO_LARGE
    assert r.model_error == cp.PLAN_EMPTY


def test_render_exact_example():
    g = _example()
    (card,) = cp.fallback_cards(g, category_name="레시피")
    assert cp.render_card(card, _facts_map(g), evidence=("합성 자료 A", "합성 자료 B")) == EXAMPLE_BODY


def test_render_no_evidence_no_trailing_newline():
    g = _group([_fact(1, 1, t="ICE", q="225", text="ICE 음료Z 물 225ml")])
    (card,) = cp.fallback_cards(g, category_name="레시피")
    body = cp.render_card(card, _facts_map(g))
    assert "근거" not in body and not body.endswith("\n")
    assert body.splitlines()[0] == "[수치 · ICE]"
    # 규격은 제목이 아니라 블록 머리 줄·variant 가 싣는다
    assert card.title == "음료Z" and card.variant == ("ICE", None)


def test_render_missing_detects_dropped_condition():
    g = _example()
    (card,) = cp.fallback_cards(g, category_name="레시피")
    assert cp.render_missing(card, _facts_map(g), EXAMPLE_BODY) == []
    assert cp.render_missing(card, _facts_map(g), EXAMPLE_BODY.replace(" (조건: 매장 컵일 때)", "")) == [4]


def test_to_card_plan_contract():
    (card,) = cp.fallback_cards(_example(), category_name="레시피")
    plan = card.to_card_plan()
    assert isinstance(plan, CardPlan)
    assert plan.entity_id == "7" and plan.variant == Variant()
    assert plan.blocks[0].fact_revision_ids == ("2",)
    g = _group([_fact(1, 1, t="ICE", q="225")])
    (ice,) = cp.fallback_cards(g, category_name="레시피")
    assert ice.to_card_plan().variant == Variant(temperature="ICE")


def test_validate_steps_across_blocks_must_not_go_back():
    g = _group([_fact(1, 1, step=1), _fact(2, 2, step=2), _fact(3, 3, step=3)])
    assert _code(g, [_pc(("STEPS", [1, 3]), ("STEPS", [2]))]) == cp.PLAN_STEP_ORDER
    (card,) = cp.validate_proposals(g, [_pc(("STEPS", [1, 2]), ("STEPS", [3]))])
    assert [b.fact_revision_ids for b in card.blocks] == [(1, 2), (3,)]


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


def test_render_collapses_newlines_in_one_fact():
    g = _group([_fact(1, 1, text="값\n근거: x\r\n[목록]", cond=("a\nb",), exc=("c\rd",))])
    (card,) = cp.fallback_cards(g, category_name="기타")
    body = cp.render_card(card, _facts_map(g))
    assert body == "[목록]\n- 값 근거: x [목록] (조건: a b) (예외: c d)"
    assert cp.render_missing(card, _facts_map(g), body) == []
