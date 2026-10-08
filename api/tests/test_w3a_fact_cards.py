"""W3a 사실 카드 쓰기 — 순수 규칙·전제 검사 단위 테스트 (합성 이름만, DB 없음)."""

import asyncio
from decimal import Decimal

import pytest

from app.ingest import card_plan as cp
from app.ingest import fact_cards as fc
from app.ingest.card_plan import EntityGroup, EntityPlanResult, PlanFact


def test_card_review_reason_precedence():
    assert fc.card_review_reason(missing_provenance=True, model_error="PLAN_EMPTY",
                                 open_conflict=True) == "NO_PROVENANCE"
    assert fc.card_review_reason(missing_provenance=False, model_error="PLAN_VARIANT_MIXED",
                                 open_conflict=True) == "FALLBACK:PLAN_VARIANT_MIXED"
    assert fc.card_review_reason(missing_provenance=False, model_error=None,
                                 open_conflict=True) == "FACT_CONFLICT_OPEN"
    assert fc.card_review_reason(missing_provenance=False, model_error=None,
                                 open_conflict=False) is None
    long = fc.card_review_reason(missing_provenance=False, model_error="X" * 80,
                                 open_conflict=False)
    assert long == ("FALLBACK:" + "X" * 80)[:50] and len(long) == 50


def _occ(i):
    return fc.Origin(occurrence_id=i, owner_answer_id=None, source_id=1,
                     locator_type="WHOLE_SOURCE", locator={})


def _owner(i):
    return fc.Origin(occurrence_id=None, owner_answer_id=i, source_id=None,
                     locator_type=None, locator=None)


def test_cap_origins_owner_first_then_lowest_occurrences():
    origins = [_occ(i) for i in range(160, 100, -1)] + [_owner(9), _owner(3)]
    capped = fc.cap_origins(origins)
    assert len(capped) == fc.MAX_PROVENANCE == 50
    assert [o.owner_answer_id for o in capped[:2]] == [3, 9]
    assert [o.occurrence_id for o in capped[2:]] == list(range(101, 149))


class _NoDb:
    """어떤 호출이든 실패로 기록하는 연결 대역."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"DB 호출 {name}")
        return call


def _group():
    fact = PlanFact(
        fact_revision_id=11, fact_id=21, entity_id=7, subject="음료Z", predicate="물",
        variant_temperature="ICE", variant_size=None, quantity_value=Decimal("225"),
        quantity_unit="ml", value_text=None, polarity="AFFIRM", step_order=None,
        conditions=(), exceptions=(), original_assertion="음료Z 물 225ml",
        assertion="음료Z 물 225ml")
    return EntityGroup(7, "음료Z", (fact,))


@pytest.mark.parametrize("case", ["empty", "defer", "mismatch"])
def test_write_entity_cards_requires_cards(case):
    group = _group()
    planned = cp.plan_entity(group, [])  # 제안 없음 → 대체 계획 카드 하나
    assert planned.cards
    state = fc.EntityCardState(7, "NEW", (), None)
    result = planned
    if case == "empty":
        result = EntityPlanResult(7, (), None, "DATA_TOO_LARGE")
    elif case == "defer":
        state = fc.EntityCardState(7, "DEFER", (5,), fc.REASON_EXISTING_CARD)
    else:
        state = fc.EntityCardState(8, "NEW", (), None)
    conn = _NoDb()
    with pytest.raises(ValueError):
        asyncio.run(fc.write_entity_cards(
            conn, 1, source_id=2, job_id=None, category_version=1,
            categories={"기타": 1}, state=state, group=group, result=result))
    assert conn.calls == []


def _at(kind, locator):
    return fc.Origin(occurrence_id=1, owner_answer_id=None, source_id=1,
                     locator_type=kind, locator=locator)


def test_evidence_locator_maps_to_card_evidence_kinds():
    assert fc._evidence_locator(_at("LINE", {"line": 7})) == ("MESSAGE", {"line": 7})
    assert fc._evidence_locator(_at("BBOX", {"page": 2})) == ("PAGE", {"page": 2})
    assert fc._evidence_locator(_at("PAGE", {"page": 3})) == ("PAGE", {"page": 3})
    assert fc._evidence_locator(_at("TIMESTAMP", {"timestamp_sec": 5})) == (
        "TIMESTAMP", {"timestamp_sec": 5})
    assert fc._evidence_locator(_at("WHOLE_SOURCE", {})) == ("WHOLE_SOURCE", {})
    assert fc._evidence_locator(_at("UNKNOWN", {"x": 1})) == ("WHOLE_SOURCE", {})
    assert fc._evidence_locator(_at(None, None)) == ("WHOLE_SOURCE", {})
