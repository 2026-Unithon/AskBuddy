"""계획 10 테스트 도우미. 합성 사실을 짧게 만든다(평가 자료 이름을 쓰지 않는다)."""
from __future__ import annotations

from decimal import Decimal

from app.ingest.card_plan import EntityGroup, PlanFact


def pf(rid: int, assertion: str, *, value: str | None = None, unit: str | None = None,
       step: int | None = None, conditions: tuple[str, ...] = (), exceptions: tuple[str, ...] = (),
       variant: tuple[str | None, str | None] = (None, None), entity_id: int = 1) -> PlanFact:
    """단위가 있으면 수량(quantity_value·unit), 없으면 값 글(value_text)."""
    return PlanFact(
        fact_revision_id=rid, fact_id=rid * 10, entity_id=entity_id, subject=None, predicate=None,
        variant_temperature=variant[0], variant_size=variant[1],
        quantity_value=Decimal(value) if (value is not None and unit) else None,
        quantity_unit=unit, value_text=value if (value is not None and not unit) else None,
        polarity="AFFIRM", step_order=step, conditions=tuple(conditions), exceptions=tuple(exceptions),
        original_assertion=assertion, assertion=assertion)


def group(entity_id: int, name: str, facts: list[PlanFact]) -> EntityGroup:
    return EntityGroup(entity_id=entity_id, canonical_name=name, facts=tuple(facts))


_EA_COUNT = [0]


def ea(sentence: str, *, order: int = 0, value: str = "", subject: str = "합성 딸기 음료"):
    """추출 결과 한 건(합성). original_assertion·assertion 모두 sentence."""
    from app.ingest.schemas import ExtractedAssertion

    _EA_COUNT[0] += 1
    return ExtractedAssertion(local_ref=f"f{_EA_COUNT[0]}", original_assertion=sentence, assertion=sentence,
                              subject=subject, attribute="", value=value, order=order, confidence=0.9)
