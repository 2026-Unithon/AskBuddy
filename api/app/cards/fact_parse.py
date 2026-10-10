"""W3b — 점주가 쓴 문장을 사실 후보로 나누는 분석(저장 없음).

모델 호출 동안 DB 연결을 쥐지 않는다. 기록 sink 는 풀에서 짧게 빌려 쓴다.
제안은 점주가 확인하는 초안일 뿐이다. 저장(Task 5)이 모든 칸을 처음부터 다시 검증한다.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from app.cards.fact_edit_plan import (
    CardFactState,
    EditError,
    block_kind_for,
    normalize_fields,
    value_in_sentence,
)
from app.cards.fact_edit_schemas import (
    FactFields,
    FactParseRequest,
    FactParseResponse,
    FactVariant,
    ParsedFactProposal,
)
from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.ingest.card_plan import PlanFact
from app.ingest.entity_names import normalize_alias, parse_variant
from app.ingest.extract import parse_owner_facts
from app.ingest.raw_responses import DbRawResponseSink
from app.ingest.schemas import ExtractedAssertion, FactExtractionResult
from app.usage.recorder import DbUsageSink

logger = logging.getLogger(__name__)


def _clip_list(items: list[str], item_max: int = 200, count_max: int = 10) -> list[str]:
    clipped = [i.strip()[:item_max] for i in items if i and i.strip()]
    return clipped[:count_max]


def _fields(a: ExtractedAssertion, sentence: str, *, mode: str, base: PlanFact | None):
    """제안 칸과 (모르는 규격이 있었는지) 를 돌려준다. MODIFY 는 규격·속성을 기준 판에서 가져온다."""
    value = a.value.strip()[:500] or None
    unit = (a.unit.strip()[:20] or None) if value else None
    step_order = a.as_order()
    variant_other = False
    if mode == "MODIFY" and base is not None:
        variant = FactVariant(temperature=base.variant_temperature, size=base.variant_size)  # type: ignore[arg-type]
        predicate = base.predicate
        step_order = base.step_order
    else:
        parts = parse_variant(a.variant)
        variant_other = bool(parts.other) or parts.multi_temperature
        variant = (
            FactVariant()
            if variant_other
            else FactVariant(temperature=parts.temperature, size=(parts.size or "").upper() or None)  # type: ignore[arg-type]
        )
        predicate = (a.attribute.strip()[:100] or None)
    fields = FactFields(
        sentence=sentence[:2000],
        polarity=a.polarity,
        value=value,
        unit=unit,
        conditions=_clip_list(a.conditions),
        exceptions=_clip_list(a.exceptions),
        step_order=step_order,
        variant=variant,
        predicate=predicate,
    )
    return fields, variant_other


def proposals_from_result(
    result: FactExtractionResult,
    *,
    state: CardFactState,
    mode: str,
    base: PlanFact | None,
    max_facts: int,
) -> FactParseResponse:
    """모델 결과 → 제안 목록. 합치거나 고르지 않고, 의심스러운 곳에 경고만 붙인다."""
    kept = [a for a in result.assertions if a.original_assertion.strip()]
    warnings: list[str] = []
    if not kept:
        warnings.append("NO_FACT")
    if len(kept) >= 2:
        warnings.append("MULTIPLE_FACTS")
    if len(kept) > max_facts:
        warnings.append("TOO_MANY_FACTS")
        kept = kept[:max_facts]
    if mode == "MODIFY" and len(kept) >= 2:
        warnings.append("MODIFY_SPLIT")
    card_variants = {
        (p.fact.variant_temperature, p.fact.variant_size) for p in state.pinned
    }
    base_is_step = base is not None and base.step_order is not None
    proposals: list[ParsedFactProposal] = []
    for index, a in enumerate(kept, 1):
        fields, variant_other = _fields(
            a, a.original_assertion.strip(), mode=mode, base=base
        )
        normalized = normalize_fields(fields)
        flags: list[str] = []
        subject = a.subject.strip()
        if subject and normalize_alias(subject) not in state.alias_norms:
            flags.append("SUBJECT_MISMATCH")
        if variant_other:
            flags.append("VARIANT_UNRESOLVED")
        elif mode == "ADD" and (normalized.temperature, normalized.size) not in card_variants:
            flags.append("NEW_VARIANT")
        if not value_in_sentence(normalized.quantity, normalized.sentence):
            flags.append("VALUE_NOT_IN_SENTENCE")
        if mode == "MODIFY" and base is not None and (a.as_order() is not None) != base_is_step:
            flags.append("STEP_CHANGED")
        proposals.append(
            ParsedFactProposal(
                client_ref=f"p{index}",
                fact=fields,
                block_kind=block_kind_for(normalized),  # type: ignore[arg-type]
                warnings=flags,
            )
        )
    return FactParseResponse(mode=mode, proposals=proposals, warnings=warnings)  # type: ignore[arg-type]


def _card_variant_labels(state: CardFactState) -> list[str]:
    labels: list[str] = []
    for p in state.pinned:
        label = " ".join(x for x in (p.fact.variant_temperature, p.fact.variant_size) if x)
        if label and label not in labels:
            labels.append(label)
    return labels


async def parse_card_text(
    pool,
    *,
    store_id: int,
    card_id: int,
    state: CardFactState,
    req: FactParseRequest,
) -> FactParseResponse:
    """문장을 분석해 제안만 돌려준다. 연결을 쥐지 않고 모델을 부른다(sink 는 짧게 빌린다)."""
    from app.config import get_settings

    base: PlanFact | None = None
    if req.mode == "MODIFY":
        base = next(
            (p.fact for p in state.pinned if p.fact.fact_revision_id == req.base_fact_revision_id),
            None,
        )
        if base is None:
            raise ApiError(422, "PARSE_BASE_INVALID", "고칠 사실이 이 카드에 없어요.")
    payload = {
        "entity_name": state.entity_name,
        "card_variants": _card_variant_labels(state),
        "mode": req.mode,
        "base_sentence": base.original_assertion if base is not None else None,
        "text": req.text,
    }
    context = UsageContext(
        store_id=str(store_id),
        cost_phase="OPERATING",
        cost_purpose="PRODUCT",
        stage="EXTRACT",
        logical_call_id=f"card-parse:{card_id}:{uuid4().hex[:16]}",
        operation_id=f"card-parse:{card_id}",
    )
    started = time.perf_counter()
    try:
        result = await parse_owner_facts(
            payload=payload,
            usage_sink=DbUsageSink(pool),
            usage_context=context,
            raw_sink=DbRawResponseSink(pool),
        )
    except Exception:
        logger.exception("카드 사실 분석 실패 store=%s card=%s", store_id, card_id)
        raise ApiError(
            502, "FACT_PARSE_FAILED", "분석하지 못했어요. 다시 시도해 주세요.", retryable=True
        ) from None
    max_facts = int(getattr(get_settings(), "card_fact_parse_max_facts", 10))
    try:
        response = proposals_from_result(
            result, state=state, mode=req.mode, base=base, max_facts=max_facts
        )
    except (EditError, ValueError):
        logger.exception("카드 사실 분석 결과 변환 실패 store=%s card=%s", store_id, card_id)
        raise ApiError(
            502, "FACT_PARSE_FAILED", "분석하지 못했어요. 다시 시도해 주세요.", retryable=True
        ) from None
    logger.info(
        "card_parse store=%s card=%s mode=%s %.1fs 제안 %d건 경고=%s",
        store_id, card_id, req.mode, time.perf_counter() - started,
        len(response.proposals), response.warnings,
    )
    return response
