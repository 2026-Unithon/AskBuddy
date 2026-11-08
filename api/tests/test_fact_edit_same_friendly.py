"""정리한 글(assertion)을 그대로 보낸 MODIFY 는 바뀐 게 아니다(2026-11-08 사용자 실화면: 안 고쳤는데 버릴지 물음)."""
from dataclasses import replace

from app.cards.fact_edit_plan import NormalizedFields, same_as_pinned
from tests.test_w3b_fact_edit_repo import _fact


def _n(fact, sentence):
    return NormalizedFields(
        sentence=sentence, polarity=fact.polarity, quantity=fact.quantity_value, unit=fact.quantity_unit,
        value_text=fact.value_text, conditions=tuple(fact.conditions), exceptions=tuple(fact.exceptions),
        step_order=fact.step_order, temperature=fact.variant_temperature, size=fact.variant_size,
        predicate=fact.predicate,
    )


def test_friendly_text_unchanged_is_same():
    f = replace(_fact(1), original_assertion="물=225ml", assertion="물은 225ml 넣어요")
    assert same_as_pinned(_n(f, "물은 225ml 넣어요"), f)


def test_original_text_still_same():
    f = replace(_fact(1), original_assertion="물=225ml", assertion="물은 225ml 넣어요")
    assert same_as_pinned(_n(f, "물=225ml"), f)


def test_other_text_is_change():
    f = replace(_fact(1), original_assertion="물=225ml", assertion="물은 225ml 넣어요")
    assert not same_as_pinned(_n(f, "물은 200ml 넣어요"), f)
