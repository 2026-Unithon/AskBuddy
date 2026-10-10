"""W3b 편집 계획기 단위 시험 — DB·모델 없이 합성 상태로만."""
from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.cards import fact_edit_plan as fep
from app.cards.fact_edit_plan import (
    CardFactState,
    EditError,
    PinnedFact,
    block_kind_for,
    build_plan,
    normalize_fields,
    value_in_sentence,
)
from app.cards.fact_edit_schemas import FactEditRequest, FactFields
from app.ingest.card_plan import PlanFact, ValidatedBlock, ValidatedCard


def _fact(rid, fid, sentence, *, temp=None, size=None, qty=None, unit=None, step=None,
          polarity="AFFIRM", requires=(), text=None, predicate="양"):
    return PlanFact(
        fact_revision_id=rid, fact_id=fid, entity_id=7, subject="음료Z", predicate=predicate,
        variant_temperature=temp, variant_size=size,
        quantity_value=Decimal(qty) if qty is not None else None, quantity_unit=unit,
        value_text=text, polarity=polarity, step_order=step, conditions=(), exceptions=(),
        original_assertion=sentence, assertion=sentence, requires_fact_ids=tuple(requires),
    )


def _state(**over) -> CardFactState:
    f = {
        1: _fact(1, 101, "ICE 물 225ml", temp="ICE", qty="225", unit="ml"),
        2: _fact(2, 102, "ICE 시럽 20ml", temp="ICE", qty="20", unit="ml"),
        3: _fact(3, 103, "HOT 물 275ml", temp="HOT", qty="275", unit="ml"),
        4: _fact(4, 104, "ICE 컵에 얼음을 담는다", temp="ICE", step=1),
        5: _fact(5, 105, "ICE 시럽을 넣는다", temp="ICE", step=2),
        6: _fact(6, 106, "ICE 물을 붓는다", temp="ICE", step=3, requires=(105,)),
        7: _fact(7, 107, "컵을 데우지 않는다", polarity="NEGATE"),
    }
    layout = [("b1", "QUANTITIES", [3]), ("b2", "QUANTITIES", [1, 2]),
              ("b3", "STEPS", [4, 5, 6]), ("b4", "NOTES", [7])]
    pinned = tuple(
        PinnedFact(f[r], bid, kind, pos) for bid, kind, rs in layout for pos, r in enumerate(rs, 1)
    )
    base = dict(
        store_id=1, card_id=10, version_id=20, title="음료Z", review_status="PENDING",
        published_version_id=None, entity_id=7, entity_name="음료Z",
        alias_norms=frozenset({"음료z"}), entity_problem=None,
        blocks=tuple((bid, kind, i) for i, (bid, kind, _) in enumerate(layout, 1)),
        pinned=pinned,
    )
    base.update(over)
    return CardFactState(**base)


def _item(op, rid=None, fact=None, ref=None):
    d = {"op": op}
    if rid is not None:
        d["fact_revision_id"] = rid
    if fact is not None:
        d["fact"] = fact
    if ref is not None:
        d["client_ref"] = ref
    return d


def _keep(rid):
    return _item("KEEP", rid)


def _req(blocks=None, deleted=(), **over):
    if blocks is None:
        blocks = [("QUANTITIES", [3]), ("QUANTITIES", [1, 2]), ("STEPS", [4, 5, 6]), ("NOTES", [7])]
    body = {
        "expected_version_id": 20, "idempotency_key": "key-0001",
        "blocks": [
            {"kind": k, "items": [i if isinstance(i, dict) else _keep(i) for i in items]}
            for k, items in blocks
        ],
        "deleted_fact_revision_ids": list(deleted),
    }
    body.update(over)
    return FactEditRequest.model_validate(body)


def _err(state, req) -> EditError:
    with pytest.raises(EditError) as ei:
        build_plan(state, req)
    return ei.value


def _mod(rid, **fact):
    return _item("MODIFY", rid, fact)


def test_all_keep_same_order_is_unchanged():
    plan = build_plan(_state(), _req())
    assert plan.changed is False and plan.card is None
    assert plan.kept_ids == (3, 1, 2, 4, 5, 6, 7)
    assert plan.display_reordered is False


def test_modify_with_same_values_becomes_keep():
    item = _mod(2, sentence="  ICE 시럽 20ml ", value="20", unit="ml")
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert plan.changed is False and not plan.modifies and 2 in plan.kept_ids


def test_modify_value_creates_temp_revision():
    item = _mod(2, sentence="ICE 시럽 30ml", value="30", unit="ml")
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert plan.changed and len(plan.modifies) == 1
    m = plan.modifies[0]
    assert m.temp_id == -1 and m.base.fact_revision_id == 2 and m.step_changed is False
    assert -1 in plan.facts and plan.facts[-1].fact_id == 102
    assert plan.facts[-1].quantity_value == Decimal("30")
    assert plan.facts[-1].requires_fact_ids == ()
    assert -1 in plan.card.fact_revision_ids() and 2 not in plan.card.fact_revision_ids()


@pytest.mark.parametrize("sentence,value", [("ICE 시럽 20ml", "30"), ("ICE 시럽 300ml", "30"),
                                            ("ICE 시럽 1030ml", "30")])
def test_value_must_appear_in_sentence(sentence, value):
    item = _mod(2, sentence=sentence, value=value, unit="ml")
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert (e.status, e.code, e.details) == (422, "FACT_VALUE_NOT_IN_SENTENCE", {"ref": 2})


def test_range_value_is_not_checked():
    item = _mod(7, sentence="컵을 두세 번 헹군다", value="2~3")
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [item])]))
    assert plan.changed and plan.modifies[0].fields.value_text == "2~3"


def test_value_in_sentence_helper():
    assert value_in_sentence(None, "아무 말")
    assert value_in_sentence(Decimal("1500"), "1,500원")
    assert value_in_sentence(Decimal("2.5"), "2.5ml")
    assert not value_in_sentence(Decimal("5"), "2.5ml")
    assert not value_in_sentence(Decimal("25"), "250ml")
    assert not value_in_sentence(Decimal("30"), "시럽 30.5ml")
    assert value_in_sentence(Decimal("30"), "시럽 30ml.")
    assert value_in_sentence(Decimal("30.5"), "시럽 30.5ml")
    assert not value_in_sentence(Decimal("30"), "시럽 1.30ml")


def test_same_number_other_variant_is_untouched():
    both = [_fact(1, 101, "ICE 물 225ml", temp="ICE", qty="225", unit="ml"),
            _fact(3, 103, "HOT 물 225ml", temp="HOT", qty="225", unit="ml")]
    pinned = (PinnedFact(both[1], "b1", "QUANTITIES", 1), PinnedFact(both[0], "b2", "QUANTITIES", 1))
    state = _state(pinned=pinned, blocks=(("b1", "QUANTITIES", 1), ("b2", "QUANTITIES", 2)))
    item = _mod(1, sentence="ICE 물 250ml", value="250", unit="ml")
    plan = build_plan(state, _req([("QUANTITIES", [3]), ("QUANTITIES", [item])]))
    assert plan.kept_ids == (3,) and plan.facts[3].original_assertion == "HOT 물 225ml"
    assert plan.facts[-1].variant_temperature == "ICE" and plan.facts[-1].quantity_value == Decimal("250")


def test_condition_added_without_number_counts_as_change():
    item = _mod(5, sentence="ICE 시럽을 넣는다", step_order=2, conditions=["손님이 원하면"])
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                      ("STEPS", [4, item, 6]), ("NOTES", [7])]))
    assert plan.changed and plan.modifies[0].step_changed is False


def test_polarity_flip_counts_as_change():
    item = _mod(7, sentence="컵을 데운다", polarity="AFFIRM")
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [item])]))
    assert plan.changed and plan.facts[-1].polarity == "AFFIRM"


def test_set_mismatch_missing():
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [])][:3]))
    assert e.code == "FACT_SET_MISMATCH" and e.details == {"missing": [7], "unexpected": [], "duplicated": []}


def test_set_mismatch_unexpected_and_duplicated():
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2, 999]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert e.details["unexpected"] == [999]
    e = _err(_state(), _req(deleted=[3]))
    assert e.details == {"missing": [], "unexpected": [], "duplicated": [3]}


def test_delete_everything_is_empty_card():
    e = _err(_state(), _req([], deleted=[1, 2, 3, 4, 5, 6, 7]))
    assert (e.status, e.code) == (422, "CARD_WOULD_BE_EMPTY")


def test_delete_required_step_is_blocked():
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 6]), ("NOTES", [7])], deleted=[5]))
    assert e.code == "FACT_REQUIRED_BY_OTHER"
    assert e.details == {"fact_revision_id": 5, "required_by": [6]}


def _steps_swap(a, b, sa, sb):
    fa = _mod(a, sentence=_sent(a), step_order=sb)
    fb = _mod(b, sentence=_sent(b), step_order=sa)
    return fa, fb


def _sent(rid):
    return {4: "ICE 컵에 얼음을 담는다", 5: "ICE 시럽을 넣는다", 6: "ICE 물을 붓는다"}[rid]


def test_swap_dependent_steps_is_rejected():
    five, six = _steps_swap(5, 6, 2, 3)
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, six, five]), ("NOTES", [7])]))
    assert e.code == "STEP_REQUIRES_ORDER"
    assert e.details == {"ref": 6, "requires_fact_id": 105}


def test_swap_independent_steps_counts_two():
    four, five = _steps_swap(4, 5, 1, 2)
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                      ("STEPS", [five, four, 6]), ("NOTES", [7])]))
    assert len(plan.modifies) == 2 and plan.steps_reordered == 2 and plan.changed


def test_step_to_non_step_kind_change():
    item = _mod(5, sentence="ICE 시럽을 넣는다")  # 단계 번호 지움
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, item, 6]), ("NOTES", [7])]))
    assert (e.code, e.details) == ("STEP_KIND_CHANGE", {"ref": 5})
    item = _mod(7, sentence="컵을 데우지 않는다", polarity="NEGATE", step_order=4)
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [item])]))
    assert e.code == "STEP_KIND_CHANGE"


def test_display_only_reorder():
    state = _state()
    # NOTES 에 줄이 둘 있는 카드를 만든다
    extra = _fact(8, 108, "일회용 컵은 쓰지 않는다", polarity="NEGATE")
    pinned = state.pinned + (PinnedFact(extra, "b4", "NOTES", 2),)
    state = _state(pinned=pinned)
    plan = build_plan(state, _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                   ("STEPS", [4, 5, 6]), ("NOTES", [8, 7])]))
    assert plan.changed and plan.display_reordered and not plan.modifies
    assert plan.card.blocks[-1].fact_revision_ids == (8, 7)


def _add(ref, **fact):
    fact.setdefault("sentence", "샷은 2샷이다")
    return _item("ADD", fact=fact, ref=ref)


def test_add_quantity_goes_to_quantities():
    f = FactFields(sentence="ICE 얼음 100g", value="100", unit="g")
    assert block_kind_for(normalize_fields(f)) == "QUANTITIES"
    assert block_kind_for(normalize_fields(FactFields(sentence="x", step_order=1))) == "STEPS"
    assert block_kind_for(normalize_fields(FactFields(sentence="x", polarity="NEGATE", value="1"))) == "NOTES"
    add = _add("n1", sentence="ICE 얼음 100g", value="100", unit="g", variant={"temperature": "ICE"})
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2, add]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert plan.changed and plan.adds[0].temp_id == -1 and plan.adds[0].client_ref == "n1"
    assert plan.facts[-1].fact_id == -1 and plan.facts[-1].requires_fact_ids == ()
    assert plan.facts[-1].subject == "음료Z" and plan.facts[-1].entity_id == 7


def _step_add(step):
    return _add("n1", sentence="ICE 컵을 흔든다", step_order=step, variant={"temperature": "ICE"})


def test_add_step_numbered_mid_but_placed_last_is_step_order_error():
    # 분석이 2번이라 읽은 단계를 블록 끝에 두면 번호가 준다(1, 2, 3, 2)
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 5, 6, _step_add(2)]), ("NOTES", [7])]))
    assert (e.code, e.details) == ("CARD_LAYOUT_INVALID", {"plan_code": "PLAN_STEP_ORDER"})


def test_add_step_mid_procedure_with_renumber_is_accepted():
    # 화면이 보내는 모양: 새 단계 2번 + 뒤 단계 번호만 바꾼 MODIFY(3·4번). 선행(105 → 106)도 유지
    five = _mod(5, sentence=_sent(5), step_order=3)
    six = _mod(6, sentence=_sent(6), step_order=4)
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                      ("STEPS", [4, _step_add(2), five, six]), ("NOTES", [7])]))
    assert plan.changed and len(plan.adds) == 1 and len(plan.modifies) == 2
    assert plan.steps_reordered == 2
    steps = next(b for b in plan.card.blocks if b.kind == "STEPS")
    orders = [plan.facts[r].step_order for r in steps.fact_revision_ids]
    assert orders == [1, 2, 3, 4]


def test_add_in_steps_block_without_step_is_layout_error():
    add = _add("n1", variant={"temperature": "ICE"})
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 5, 6, add]), ("NOTES", [7])]))
    assert (e.code, e.details) == ("CARD_LAYOUT_INVALID", {"plan_code": "PLAN_KIND_MISMATCH"})


def test_add_unknown_size_is_unresolved():
    add = _add("n1", variant={"size": "XL"})
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [7, add])]))
    assert (e.code, e.details) == ("VARIANT_UNRESOLVED", {"ref": "n1"})


def test_add_variant_differs_from_block():
    add = _add("n1", sentence="ICE 얼음 100g", value="100", unit="g", variant={"temperature": "HOT"})
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2, add]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert (e.code, e.details) == ("CARD_LAYOUT_INVALID", {"plan_code": "PLAN_VARIANT_MIXED"})


def test_add_value_not_in_sentence_uses_client_ref():
    add = _add("n1", sentence="ICE 얼음 많이", value="100", unit="g", variant={"temperature": "ICE"})
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2, add]),
                             ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert e.code == "FACT_VALUE_NOT_IN_SENTENCE" and e.details == {"ref": "n1"}


def test_too_large_when_validation_splits_card():
    card = ValidatedCard(7, "음료Z 1/2", "기타", (None, None), (ValidatedBlock("b1", "NOTES", 1, (7,), (None, None)),))
    with patch.object(fep, "validate_proposals", return_value=(card, card)):
        e = _err(_state(), _req())
    assert (e.status, e.code) == (422, "CARD_TOO_LARGE")


def test_entity_problem_comes_first():
    e = _err(_state(entity_problem="MERGED_ENTITY"), _req([("NOTES", [999])]))
    assert (e.status, e.code, e.details) == (409, "CARD_ENTITY_MOVED", {"entity_problem": "MERGED_ENTITY"})


def test_modify_ignores_variant_and_predicate_from_request():
    item = _mod(2, sentence="ICE 시럽 30ml", value="30", unit="ml",
                variant={"temperature": "HOT", "size": "L"}, predicate="다른속성")
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    f = plan.facts[-1]
    assert (f.variant_temperature, f.variant_size, f.predicate) == ("ICE", None, "양")


def test_bind_swaps_temp_ids_and_keeps_layout():
    item = _mod(2, sentence="ICE 시럽 30ml", value="30", unit="ml")
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    new = _fact(900, 102, "ICE 시럽 30ml", temp="ICE", qty="30", unit="ml")
    card, facts = plan.bind({-1: 900}, {900: new})
    assert [b.block_id for b in card.blocks] == [b.block_id for b in plan.card.blocks]
    assert card.blocks[1].fact_revision_ids == (1, 900)
    assert facts[900] is new and all(k > 0 for k in facts) and set(facts) == {1, 3, 4, 5, 6, 7, 900}


def test_deterministic():
    item = _mod(2, sentence="ICE 시럽 30ml", value="30", unit="ml")
    a = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                                   ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    b = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, item]),
                                   ("STEPS", [4, 5, 6]), ("NOTES", [7])]))
    assert a == b


def test_module_is_pure():
    code = ("import sys, app.cards.fact_edit_plan; "
            "bad=[m for m in sys.modules if m in ('app.config','app.db','psycopg','openai','asyncpg')]; "
            "sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_add_lowercase_size_is_normalized():
    add = _add("n2", sentence="m 얼음 100g", value="100", unit="g", variant={"size": "m"})
    plan = build_plan(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                                      ("STEPS", [4, 5, 6]), ("NOTES", [7]), ("QUANTITIES", [add])]))
    assert plan.facts[-1].variant_size == "M"


def test_check_order_set_mismatch_before_empty():
    e = _err(_state(), _req([], deleted=[1, 2]))
    assert e.code == "FACT_SET_MISMATCH"


def test_check_order_step_kind_before_value_in_sentence():
    bad_value = _mod(2, sentence="ICE 시럽 20ml", value="30", unit="ml")
    kind = _mod(5, sentence="ICE 시럽을 넣는다")
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, bad_value]),
                             ("STEPS", [4, kind, 6]), ("NOTES", [7])]))
    assert e.code == "STEP_KIND_CHANGE"


def test_check_order_delete_precedence_before_layout():
    e = _err(_state(), _req([("QUANTITIES", [3]), ("QUANTITIES", [1, 2]),
                             ("STEPS", [4, 6]), ("NOTES", [7])], deleted=[5]))
    assert e.code == "FACT_REQUIRED_BY_OTHER"  # 배치(PLAN_*)보다 먼저
