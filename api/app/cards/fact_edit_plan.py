"""W3b — 카드 사실 편집 계획기. DB·모델·설정에 닿지 않는 순수 모듈.

저장 요청(FactEditRequest)과 지금 카드 상태(CardFactState)를 받아, DB 를 치기 전에
할 수 있는 검증을 전부 하고 무엇을 쓸지(EditPlan)를 돌려준다. 저장 쪽은 이 결과만
믿고 쓴다. 배치 규칙은 W3a 의 validate_proposals 를 그대로 부른다(다시 만들지 않는다).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from app.cards.fact_edit_schemas import (
    EditAdd,
    EditKeep,
    EditModify,
    FactEditRequest,
    FactFields,
)
from app.ingest.card_plan import (
    EntityGroup,
    PlanFact,
    PlanInvalid,
    ProposedBlock,
    ProposedCard,
    ValidatedBlock,
    ValidatedCard,
    check_group,
    fact_sort_key,
    validate_proposals,
)
from app.ingest.entity_names import SIZE_TOKENS
from app.ingest.fact_keys import parse_value

TEMP_ID_BASE = -1  # 임시 판 id 는 -1, -2, … (요청 순서)
_CATEGORY = "기타"  # 검증용 자리표시. 저장 쪽은 카드 분류를 건드리지 않는다
_SIZE_VALUES = frozenset(SIZE_TOKENS.values())


class EditError(Exception):
    """라우터가 ApiError(status, code, 한국어 메시지, details=details) 로 옮긴다."""

    def __init__(self, status: int, code: str, details: dict | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PinnedFact:
    fact: PlanFact  # 이 카드 판이 고정한 판
    block_id: str
    kind: str  # QUANTITIES | STEPS | NOTES (RAW 블록 사실은 없음)
    position: int


@dataclass(frozen=True)
class CardFactState:
    store_id: int
    card_id: int
    version_id: int
    title: str
    review_status: str
    published_version_id: int | None
    entity_id: int | None
    entity_name: str
    alias_norms: frozenset[str]  # 대상 이름·별칭의 normalize_alias 값
    entity_problem: str | None  # None | "MIXED_ENTITY" | "MERGED_ENTITY"
    blocks: tuple[tuple[str, str, int], ...]  # (block_id, kind, order) 순서대로
    pinned: tuple[PinnedFact, ...]  # 블록 순 → position 순


@dataclass(frozen=True)
class NormalizedFields:
    sentence: str
    polarity: str
    quantity: Decimal | None
    unit: str | None
    value_text: str | None
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    step_order: int | None
    temperature: str | None
    size: str | None
    predicate: str | None


@dataclass(frozen=True)
class PlannedModify:
    base: PlanFact
    fields: NormalizedFields
    temp_id: int
    step_changed: bool  # 단계 번호가 바뀜


@dataclass(frozen=True)
class PlannedAdd:
    client_ref: str
    fields: NormalizedFields
    temp_id: int


@dataclass(frozen=True)
class EditPlan:
    changed: bool
    card: ValidatedCard | None  # 임시 id 포함. changed=False 면 None
    facts: Mapping[int, PlanFact]  # 임시·실제 판 id → PlanFact (렌더링 입력)
    modifies: tuple[PlannedModify, ...]
    adds: tuple[PlannedAdd, ...]
    kept_ids: tuple[int, ...]  # KEEP + 같은 값이라 KEEP 이 된 MODIFY
    deleted_ids: tuple[int, ...]
    steps_reordered: int  # step_changed 인 수정 수
    display_reordered: bool  # 판 변화 없이 자리·블록만 달라짐

    def bind(
        self, id_map: Mapping[int, int], real: Mapping[int, PlanFact]
    ) -> tuple[ValidatedCard, dict[int, PlanFact]]:
        """임시 id 를 실제 판 id 로 바꾼 카드와 렌더링용 사실 사전.

        id_map 은 임시 id → 새로 만든 실제 판 id, real 은 저장 쪽이 DB 에서 다시 읽은 새 판이다.
        """
        if self.card is None:
            raise ValueError("바뀐 것이 없는 계획은 묶을 카드가 없다")

        def actual(rid: int) -> int:
            return id_map[rid] if rid < 0 else rid

        card = replace(
            self.card,
            blocks=tuple(
                ValidatedBlock(
                    block_id=b.block_id,
                    kind=b.kind,
                    order=b.order,
                    fact_revision_ids=tuple(actual(r) for r in b.fact_revision_ids),
                    variant=b.variant,
                )
                for b in self.card.blocks
            ),
        )
        facts: dict[int, PlanFact] = {}
        for rid, fact in self.facts.items():
            if rid < 0:
                facts[id_map[rid]] = real[id_map[rid]]
            else:
                facts[rid] = fact
        return card, facts


def normalize_fields(f: FactFields) -> NormalizedFields:
    """점주가 보낸 칸을 저장 모양으로 맞춘다. 수치와 서술값은 동시에 두지 않는다."""
    quantity: Decimal | None = None
    unit: str | None = None
    value_text: str | None = None
    if f.value is not None:
        quantity, unit, value_text = parse_value(f.value, f.unit)
        if quantity is not None and value_text is not None:
            raise EditError(422, "FACT_FIELD_INVALID", {"field": "value"})
    return NormalizedFields(
        sentence=f.sentence.strip(),
        polarity=f.polarity,
        quantity=quantity,
        unit=unit,
        value_text=value_text,
        conditions=tuple(f.conditions),
        exceptions=tuple(f.exceptions),
        step_order=f.step_order,
        temperature=f.variant.temperature,
        size=f.variant.size,
        predicate=f.predicate,
    )


def same_as_pinned(n: NormalizedFields, f: PlanFact) -> bool:
    """고치는 칸(문장·부정·값·단위·조건·예외·단계)이 모두 같은가. 규격·속성은 보지 않는다."""
    return (
        n.sentence == f.original_assertion.strip()
        and n.polarity == f.polarity
        and n.quantity == f.quantity_value
        and n.unit == f.quantity_unit
        and n.value_text == f.value_text
        and n.conditions == tuple(f.conditions)
        and n.exceptions == tuple(f.exceptions)
        and n.step_order == f.step_order
    )


def value_in_sentence(quantity: Decimal | None, sentence: str) -> bool:
    """수치 문자열이 문장에 있는가(쉼표 무시, 앞뒤에 다른 숫자(소수점 포함)가 붙으면 다른 수). 수치가 없으면 True."""
    if quantity is None:
        return True
    text = format(quantity.normalize(), "f")
    return re.search(rf"(?<![\d.]){re.escape(text)}(?!\.?\d)", sentence.replace(",", "")) is not None


def block_kind_for(n: NormalizedFields) -> str:
    """새 줄이 들어갈 블록 종류. 단계 번호 → STEPS, 긍정 수치 → QUANTITIES, 그 밖 → NOTES."""
    if n.step_order is not None:
        return "STEPS"
    if n.polarity == "AFFIRM" and n.quantity is not None:
        return "QUANTITIES"
    return "NOTES"


def _with_ref(e: EditError, ref: int | str) -> EditError:
    return EditError(e.status, e.code, {**e.details, "ref": ref})


def _modified_fact(base: PlanFact, n: NormalizedFields, temp_id: int) -> PlanFact:
    return replace(
        base,
        fact_revision_id=temp_id,
        quantity_value=n.quantity,
        quantity_unit=n.unit,
        value_text=n.value_text,
        polarity=n.polarity,
        step_order=n.step_order,
        conditions=n.conditions,
        exceptions=n.exceptions,
        original_assertion=n.sentence,
        assertion=n.sentence,
    )


def _added_fact(state: CardFactState, n: NormalizedFields, temp_id: int) -> PlanFact:
    return PlanFact(
        fact_revision_id=temp_id,
        fact_id=temp_id,
        entity_id=state.entity_id,  # type: ignore[arg-type]
        subject=state.entity_name,
        predicate=n.predicate,
        variant_temperature=n.temperature,
        variant_size=n.size,
        quantity_value=n.quantity,
        quantity_unit=n.unit,
        value_text=n.value_text,
        polarity=n.polarity,
        step_order=n.step_order,
        conditions=n.conditions,
        exceptions=n.exceptions,
        original_assertion=n.sentence,
        assertion=n.sentence,
        requires_fact_ids=(),
    )


def _layout(card_blocks) -> list[tuple[str, tuple, tuple[int, ...]]]:
    return [(b.kind, b.variant, tuple(b.fact_revision_ids)) for b in card_blocks]


def _current_layout(state: CardFactState) -> list[tuple[str, tuple, tuple[int, ...]]]:
    lines: list[tuple[str, tuple, tuple[int, ...]]] = []
    for block_id, _kind, _order in state.blocks:
        pins = [p for p in state.pinned if p.block_id == block_id]
        if pins:
            lines.append(
                (pins[0].kind, pins[0].fact.variant, tuple(p.fact.fact_revision_id for p in pins))
            )
    return lines


def build_plan(state: CardFactState, req: FactEditRequest) -> EditPlan:
    # 1) 대상 문제
    if state.entity_problem:
        raise EditError(409, "CARD_ENTITY_MOVED", {"entity_problem": state.entity_problem})

    pinned_by_id = {p.fact.fact_revision_id: p for p in state.pinned}

    # 2) 집합 대조 — 고정 판 = KEEP ∪ MODIFY ∪ 삭제
    keep_modify_ids = [
        item.fact_revision_id
        for block in req.blocks
        for item in block.items
        if isinstance(item, (EditKeep, EditModify))
    ]
    deleted = list(req.deleted_fact_revision_ids)
    counts = Counter(keep_modify_ids) + Counter(deleted)
    duplicated = sorted(i for i, c in counts.items() if c > 1)
    unexpected = sorted(set(counts) - set(pinned_by_id))
    missing = sorted(set(pinned_by_id) - set(counts))
    if duplicated or unexpected or missing:
        raise EditError(
            422,
            "FACT_SET_MISMATCH",
            {"missing": missing, "unexpected": unexpected, "duplicated": duplicated},
        )

    # 3) 빈 카드
    adds_requested = sum(
        1 for block in req.blocks for item in block.items if isinstance(item, EditAdd)
    )
    if not keep_modify_ids and not adds_requested:
        raise EditError(422, "CARD_WOULD_BE_EMPTY")

    # 4) 줄마다 정규화·같은 값 판정 (요청 순서)
    next_temp = TEMP_ID_BASE
    final_facts: dict[int, PlanFact] = {}  # 판 id(임시 포함) → 사실
    block_refs: list[tuple[str, list[int]]] = []
    ref_of: dict[int, int | str] = {}  # 판 id → 오류에 쓸 이름 (판 id 또는 client_ref)
    modifies: list[PlannedModify] = []
    adds: list[PlannedAdd] = []
    kept: list[int] = []
    for block in req.blocks:
        refs: list[int] = []
        for item in block.items:
            if isinstance(item, EditKeep):
                pin = pinned_by_id[item.fact_revision_id].fact
                final_facts[pin.fact_revision_id] = pin
                ref_of[pin.fact_revision_id] = pin.fact_revision_id
                kept.append(pin.fact_revision_id)
                refs.append(pin.fact_revision_id)
            elif isinstance(item, EditModify):
                base = pinned_by_id[item.fact_revision_id].fact
                try:
                    n = normalize_fields(item.fact)
                except EditError as e:
                    raise _with_ref(e, base.fact_revision_id) from None
                # 규격·속성은 고정 판 값을 쓴다
                n = replace(
                    n,
                    temperature=base.variant_temperature,
                    size=base.variant_size,
                    predicate=base.predicate,
                )
                if (n.step_order is None) != (base.step_order is None):
                    raise EditError(422, "STEP_KIND_CHANGE", {"ref": base.fact_revision_id})
                if same_as_pinned(n, base):
                    final_facts[base.fact_revision_id] = base
                    ref_of[base.fact_revision_id] = base.fact_revision_id
                    kept.append(base.fact_revision_id)
                    refs.append(base.fact_revision_id)
                    continue
                temp = next_temp
                next_temp -= 1
                modifies.append(
                    PlannedModify(base, n, temp, step_changed=n.step_order != base.step_order)
                )
                final_facts[temp] = _modified_fact(base, n, temp)
                ref_of[temp] = base.fact_revision_id
                refs.append(temp)
            else:
                try:
                    n = normalize_fields(item.fact)
                except EditError as e:
                    raise _with_ref(e, item.client_ref) from None
                if n.size is not None:
                    # 화면·분석기가 "m" 처럼 소문자로 보내도 사이즈 표 값("M")으로 맞춘다
                    n = replace(n, size=n.size.upper())
                    if n.size not in _SIZE_VALUES:
                        raise EditError(422, "VARIANT_UNRESOLVED", {"ref": item.client_ref})
                temp = next_temp
                next_temp -= 1
                adds.append(PlannedAdd(item.client_ref, n, temp))
                final_facts[temp] = _added_fact(state, n, temp)
                ref_of[temp] = item.client_ref
                refs.append(temp)
        block_refs.append((block.kind, refs))

    # 5) 값-문장 일치 (바뀐 줄만)
    for m in modifies:
        if not value_in_sentence(m.fields.quantity, m.fields.sentence):
            raise EditError(422, "FACT_VALUE_NOT_IN_SENTENCE", {"ref": m.base.fact_revision_id})
    for a in adds:
        if not value_in_sentence(a.fields.quantity, a.fields.sentence):
            raise EditError(422, "FACT_VALUE_NOT_IN_SENTENCE", {"ref": a.client_ref})

    # 6) 삭제 선행 — 남는 사실이 선행으로 쓰는 사실은 뺄 수 없다
    for rid in sorted(deleted):
        gone = pinned_by_id[rid].fact.fact_id
        required_by = sorted(
            ref_of[fid]
            for fid, f in final_facts.items()
            if gone in f.requires_fact_ids and isinstance(ref_of[fid], int)
        )
        if required_by:
            raise EditError(
                422, "FACT_REQUIRED_BY_OTHER", {"fact_revision_id": rid, "required_by": required_by}
            )

    # 7) 단계 선행 — 번호가 바뀐 단계가 같은 규격의 선행·후속 단계와 어긋나지 않는가
    by_fact_id = {f.fact_id: f for f in final_facts.values()}
    for m in modifies:
        if not m.step_changed:
            continue
        f = final_facts[m.temp_id]
        for r_id in f.requires_fact_ids:
            r = by_fact_id.get(r_id)
            if r and r.step_order is not None and r.variant == f.variant:
                if not r.step_order < f.step_order:  # type: ignore[operator]
                    raise EditError(
                        422,
                        "STEP_REQUIRES_ORDER",
                        {"ref": m.base.fact_revision_id, "requires_fact_id": r.fact_id},
                    )
        for g in final_facts.values():
            if f.fact_id in g.requires_fact_ids and g.step_order is not None and g.variant == f.variant:
                if not f.step_order < g.step_order:  # type: ignore[operator]
                    raise EditError(
                        422,
                        "STEP_REQUIRES_ORDER",
                        {"ref": ref_of[g.fact_revision_id], "requires_fact_id": f.fact_id},
                    )

    # 8) 배치 — W3a 검증을 그대로 부른다
    group = EntityGroup(
        entity_id=state.entity_id,  # type: ignore[arg-type]
        canonical_name=state.entity_name,
        facts=tuple(sorted(final_facts.values(), key=fact_sort_key)),
    )
    data_error = check_group(group)
    if data_error:
        raise EditError(422, "CARD_LAYOUT_INVALID", {"plan_code": data_error})
    try:
        cards = validate_proposals(
            group,
            [ProposedCard(_CATEGORY, tuple(ProposedBlock(kind, tuple(refs)) for kind, refs in block_refs))],
        )
    except PlanInvalid as e:
        raise EditError(422, "CARD_LAYOUT_INVALID", {"plan_code": e.code}) from e
    if len(cards) > 1:
        raise EditError(422, "CARD_TOO_LARGE")
    card = cards[0]

    # 9) 바뀜 판정
    facts_changed = bool(modifies or adds or deleted)
    display_reordered = False
    if not facts_changed:
        # 판이 그대로면 id 가 모두 실제 id 라 줄 목록을 바로 견줄 수 있다
        display_reordered = _layout(card.blocks) != _current_layout(state)
    changed = facts_changed or display_reordered
    return EditPlan(
        changed=changed,
        card=card if changed else None,
        facts=final_facts,
        modifies=tuple(modifies),
        adds=tuple(adds),
        kept_ids=tuple(kept),
        deleted_ids=tuple(sorted(deleted)),
        steps_reordered=sum(1 for m in modifies if m.step_changed),
        display_reordered=display_reordered,
    )
