"""카드 계획 검증·대체 계획·서버 렌더링 (W3a). DB·모델·설정에 닿지 않는 순수 모듈.

모델은 사실을 고르고 배치만 한다. 제목·문장·수량·단위·조건·부정·예외는 이 모듈이
사실 판에서 직접 렌더링한다. 모델 계획이 규칙을 어기면 문장을 지우지 않고 통째로
버린 뒤 결정적 대체 계획으로 간다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from decimal import Decimal

from app.contracts.card import CardBlock, CardPlan
from app.contracts.common import Variant

KIND_RANK = {"QUANTITIES": 1, "STEPS": 2, "NOTES": 3}
KIND_LABEL = {"QUANTITIES": "수치", "STEPS": "순서", "NOTES": "목록"}
NO_VARIANT_LABEL = "규격 표시 없음"
EVIDENCE_PREFIX = "근거: "
MAX_FACTS_PER_BLOCK = 50
MAX_BLOCKS_PER_CARD = 20
TITLE_MAX = 120
NAME_MAX = 100

# 계획 오류 — 모델 계획을 버리고 대체 계획을 쓴다
PLAN_EMPTY = "PLAN_EMPTY"
PLAN_UNKNOWN_REF = "PLAN_UNKNOWN_REF"
PLAN_OUTSIDE_GROUP = "PLAN_OUTSIDE_GROUP"
PLAN_DUPLICATE_IN_CARD = "PLAN_DUPLICATE_IN_CARD"
PLAN_KIND_MISMATCH = "PLAN_KIND_MISMATCH"
PLAN_VARIANT_MIXED = "PLAN_VARIANT_MIXED"
PLAN_STEP_ORDER = "PLAN_STEP_ORDER"
PLAN_STEPS_INCOMPLETE = "PLAN_STEPS_INCOMPLETE"
PLAN_REQUIRES_MISSING = "PLAN_REQUIRES_MISSING"
PLAN_UNPLACED = "PLAN_UNPLACED"

# 데이터 오류 — 대체 계획도 불가능하다. 카드 없이 검수 대기
DATA_REQUIRES_OUTSIDE_ENTITY = "DATA_REQUIRES_OUTSIDE_ENTITY"
DATA_REQUIRES_CYCLE = "DATA_REQUIRES_CYCLE"
DATA_TOO_LARGE = "DATA_TOO_LARGE"
DATA_NO_NAME = "DATA_NO_NAME"  # 대상 이름이 비어 제목을 만들 수 없다

VariantKey = tuple[str | None, str | None]  # (온도, 사이즈)
_NO_VARIANT: VariantKey = (None, None)


@dataclass(frozen=True)
class PlanFact:
    fact_revision_id: int
    fact_id: int
    entity_id: int
    subject: str | None
    predicate: str | None
    variant_temperature: str | None
    variant_size: str | None
    quantity_value: Decimal | None
    quantity_unit: str | None
    value_text: str | None
    polarity: str  # "AFFIRM" | "NEGATE"
    step_order: int | None
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    original_assertion: str
    assertion: str
    # 먼저 지켜야 하는 사실(fact_id). 같은 카드에 그 사실의 판이 있어야 한다
    requires_fact_ids: tuple[int, ...] = ()

    @property
    def variant(self) -> VariantKey:
        return (self.variant_temperature, self.variant_size)


@dataclass(frozen=True)
class EntityGroup:
    entity_id: int
    canonical_name: str
    facts: tuple[PlanFact, ...]  # fact_sort_key 순 (만드는 쪽 책임)


@dataclass(frozen=True)
class ProposedBlock:
    kind: str  # 모델이 준 그대로
    refs: tuple[int | str, ...]  # 판 id(int) 또는 풀지 못한 이름표(str)


@dataclass(frozen=True)
class ProposedCard:
    category_name: str
    blocks: tuple[ProposedBlock, ...]


@dataclass(frozen=True)
class ValidatedBlock:
    block_id: str  # f"b{order}"
    kind: str  # QUANTITIES | STEPS | NOTES
    order: int  # 카드 안 1부터
    fact_revision_ids: tuple[int, ...]  # 표시 순서
    variant: VariantKey


@dataclass(frozen=True)
class ValidatedCard:
    entity_id: int
    title: str
    category_name: str
    variant: VariantKey  # 모든 블록 규격이 같으면 그 값, 아니면 (None, None)
    blocks: tuple[ValidatedBlock, ...]

    def fact_revision_ids(self) -> tuple[int, ...]:
        """블록 순서대로, 중복 없이."""
        seen: dict[int, None] = {}
        for b in self.blocks:
            for rid in b.fact_revision_ids:
                seen.setdefault(rid, None)
        return tuple(seen)

    def to_card_plan(self) -> CardPlan:
        """계약 검증을 통과하는 CardPlan. 계약의 id 는 문자열이다."""
        return CardPlan(
            entity_id=str(self.entity_id),
            variant=Variant(temperature=self.variant[0], size=self.variant[1]),
            title=self.title,
            blocks=[
                CardBlock(
                    block_id=b.block_id,
                    kind=b.kind,
                    order=b.order,
                    fact_revision_ids=tuple(str(r) for r in b.fact_revision_ids),
                )
                for b in self.blocks
            ],
        )


@dataclass(frozen=True)
class EntityPlanResult:
    entity_id: int
    cards: tuple[ValidatedCard, ...]  # 비면 카드 없음
    model_error: str | None  # 모델 계획을 버린 이유(PLAN_*). 대체 계획을 썼을 때만
    pending_reason: str | None  # cards 가 비었을 때의 사유(DATA_*)


class PlanInvalid(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def fact_sort_key(f: PlanFact) -> tuple:
    return (
        f.variant_temperature is None,
        f.variant_temperature or "",
        f.variant_size is None,
        f.variant_size or "",
        f.step_order is None,
        f.step_order or 0,
        f.fact_revision_id,
    )


def variant_label(variant: VariantKey) -> str:
    return " · ".join(x for x in variant if x) or NO_VARIANT_LABEL


def card_title(canonical_name: str, index: int, total: int) -> str:
    """카드 제목 = 대상 이름(+ 나뉜 카드면 " i/n").

    규격 꼬리표(" (ICE)")를 붙이지 않는다. R 은 질문에 언급된 카드 제목으로 대상을
    찾으므로 제목이 대상 이름과 달라지면 사실 카드 질문이 모두 점주에게 넘어간다.
    규격은 블록 머리 줄과 공개 카드의 variant 칸이 싣고, 규격이 갈리는 질문은
    R 이 CLARIFY 로 규격을 확정한 뒤 그 값만 인용한다(D19).
    """
    base = canonical_name.strip()[:NAME_MAX]
    if total > 1:
        base += f" {index}/{total}"
    return base[:TITLE_MAX]


def check_group(group: EntityGroup) -> str | None:
    """대상 이름이 있고 선행 관계가 대상 안에서 닫혀 있으며 순환이 없는지 본다."""
    if not group.canonical_name.strip():
        return DATA_NO_NAME
    ids = {f.fact_id for f in group.facts}
    graph: dict[int, set[int]] = {i: set() for i in ids}
    for f in group.facts:
        for r in f.requires_fact_ids:
            if r not in ids:
                return DATA_REQUIRES_OUTSIDE_ENTITY
            graph[f.fact_id].add(r)
    # 반복형 DFS 로 순환(자기 참조 포함)을 찾는다
    state: dict[int, int] = {}  # 1=방문 중, 2=끝
    for start in graph:
        if state.get(start):
            continue
        stack = [(start, iter(sorted(graph[start])))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if state.get(nxt) == 1:
                    return DATA_REQUIRES_CYCLE
                if not state.get(nxt):
                    state[nxt] = 1
                    stack.append((nxt, iter(sorted(graph[nxt]))))
                    break
            else:
                state[node] = 2
                stack.pop()
    return None


def _chunks(items: Sequence, size: int) -> list[list]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def validate_proposals(
    group: EntityGroup, proposals: Sequence[ProposedCard]
) -> tuple[ValidatedCard, ...]:
    by_id = {f.fact_revision_id: f for f in group.facts}

    # 1) 빈 블록·빈 카드를 버린다
    cards: list[tuple[str, list[ProposedBlock]]] = []
    for p in proposals:
        blocks = [b for b in p.blocks if b.refs]
        if blocks:
            cards.append((p.category_name, blocks))

    # 2) 블록 규칙 — 판정 순서 고정
    for _, blocks in cards:
        for b in blocks:
            if b.kind not in KIND_RANK:
                raise PlanInvalid(PLAN_KIND_MISMATCH, f"kind={b.kind}")
            if any(type(r) is not int for r in b.refs):
                raise PlanInvalid(PLAN_UNKNOWN_REF)
            if any(r not in by_id for r in b.refs):
                raise PlanInvalid(PLAN_OUTSIDE_GROUP)
            facts = [by_id[r] for r in b.refs]  # type: ignore[index]
            if b.kind == "STEPS":
                if any(f.step_order is None for f in facts):
                    raise PlanInvalid(PLAN_KIND_MISMATCH, "STEPS 에 단계 없는 사실")
            elif any(f.step_order is not None for f in facts):
                raise PlanInvalid(PLAN_KIND_MISMATCH, "단계 사실이 STEPS 밖에 있다")
            if len({f.variant for f in facts}) > 1:
                raise PlanInvalid(PLAN_VARIANT_MIXED)
            if b.kind == "STEPS":
                orders = [f.step_order for f in facts]
                if any(later < earlier for earlier, later in zip(orders, orders[1:])):  # type: ignore[operator]
                    raise PlanInvalid(PLAN_STEP_ORDER)

    # 3) 한 카드 안 중복 (다른 카드끼리는 허용)
    for _, blocks in cards:
        seen: set[int] = set()
        for b in blocks:
            for r in b.refs:
                if r in seen:
                    raise PlanInvalid(PLAN_DUPLICATE_IN_CARD)
                seen.add(r)  # type: ignore[arg-type]

    # 4)
    if not cards:
        raise PlanInvalid(PLAN_EMPTY)

    # 5) 종류 순서로 정렬하고 블록·카드를 나눈다
    split: list[tuple[str, list[tuple[str, tuple[int, ...]]]]] = []
    for category, blocks in cards:
        ordered = sorted(enumerate(blocks), key=lambda ib: (KIND_RANK[ib[1].kind], ib[0]))
        pieces = [
            (b.kind, tuple(chunk))
            for _, b in ordered
            for chunk in _chunks(b.refs, MAX_FACTS_PER_BLOCK)
        ]
        for part in _chunks(pieces, MAX_BLOCKS_PER_CARD):
            split.append((category, part))

    # 6) 선행·단계 완전성
    for _, part in split:
        # 같은 규격의 단계는 여러 STEPS 블록에 걸쳐서도 순서가 줄지 않아야 한다
        last_step: dict[VariantKey, int] = {}
        for kind, refs in part:
            if kind != "STEPS":
                continue
            for r in refs:
                f = by_id[r]
                if f.step_order < last_step.get(f.variant, f.step_order):  # type: ignore[operator]
                    raise PlanInvalid(PLAN_STEP_ORDER, "블록 사이 단계 순서")
                last_step[f.variant] = f.step_order  # type: ignore[assignment]
        in_card = {r for _, refs in part for r in refs}
        fact_ids_in_card = {by_id[r].fact_id for r in in_card}
        for r in in_card:
            if any(req not in fact_ids_in_card for req in by_id[r].requires_fact_ids):
                raise PlanInvalid(PLAN_REQUIRES_MISSING)
        step_ids = {r for kind, refs in part if kind == "STEPS" for r in refs}
        step_variants = {by_id[r].variant for r in step_ids}
        for f in group.facts:
            if f.step_order is not None and f.variant in step_variants:
                if f.fact_revision_id not in step_ids:
                    raise PlanInvalid(PLAN_STEPS_INCOMPLETE)

    # 7) 어느 카드에도 없는 판
    placed = {r for _, part in split for _, refs in part for r in refs}
    if any(f.fact_revision_id not in placed for f in group.facts):
        raise PlanInvalid(PLAN_UNPLACED)

    # 8) 결과
    total = len(split)
    result: list[ValidatedCard] = []
    for i, (category, part) in enumerate(split, start=1):
        blocks: list[ValidatedBlock] = []
        for n, (kind, refs) in enumerate(part, start=1):
            blocks.append(
                ValidatedBlock(
                    block_id=f"b{n}",
                    kind=kind,
                    order=n,
                    fact_revision_ids=tuple(refs),
                    variant=by_id[refs[0]].variant,
                )
            )
        variants = {b.variant for b in blocks}
        variant = next(iter(variants)) if len(variants) == 1 else _NO_VARIANT
        result.append(
            ValidatedCard(
                entity_id=group.entity_id,
                title=card_title(group.canonical_name, i, total),
                category_name=category.strip() or "기타",
                variant=variant,
                blocks=tuple(blocks),
            )
        )
    return tuple(result)


def fallback_cards(group: EntityGroup, *, category_name: str) -> tuple[ValidatedCard, ...]:
    """규격별 결정적 배치. 모델 없이 모든 사실을 싣는다."""
    variants = sorted(
        {f.variant for f in group.facts},
        key=lambda v: (v[0] is None, v[0] or "", v[1] is None, v[1] or ""),
    )
    blocks: list[ProposedBlock] = []
    for v in variants:
        facts = [f for f in group.facts if f.variant == v]
        quantities = [
            f.fact_revision_id
            for f in facts
            if f.step_order is None and f.polarity == "AFFIRM" and f.quantity_value is not None
        ]
        steps = [
            f.fact_revision_id
            for f in sorted(
                (f for f in facts if f.step_order is not None),
                key=lambda f: (f.step_order, f.fact_revision_id),
            )
        ]
        quantity_set = set(quantities)
        notes = [
            f.fact_revision_id
            for f in facts
            if f.step_order is None and f.fact_revision_id not in quantity_set
        ]
        for kind, refs in (("QUANTITIES", quantities), ("STEPS", steps), ("NOTES", notes)):
            if refs:
                blocks.append(ProposedBlock(kind=kind, refs=tuple(refs)))
    try:
        return validate_proposals(group, [ProposedCard(category_name, tuple(blocks))])
    except PlanInvalid as e:
        raise PlanInvalid(DATA_TOO_LARGE, e.code) from e


def plan_entity(group: EntityGroup, proposals: Sequence[ProposedCard]) -> EntityPlanResult:
    data_error = check_group(group)
    if data_error:
        return EntityPlanResult(group.entity_id, (), None, data_error)
    if not group.facts:
        return EntityPlanResult(group.entity_id, (), None, None)
    try:
        return EntityPlanResult(group.entity_id, validate_proposals(group, proposals), None, None)
    except PlanInvalid as e:
        category = next((p.category_name for p in proposals if p.category_name), "기타")
        try:
            cards = fallback_cards(group, category_name=category)
        except PlanInvalid:
            return EntityPlanResult(group.entity_id, (), e.code, DATA_TOO_LARGE)
        return EntityPlanResult(group.entity_id, cards, e.code, None)


def _one_line(text: str) -> str:
    """줄바꿈을 공백으로 접어 사실 하나가 늘 한 줄이 되게 한다."""
    return re.sub(r"[\r\n]+", " ", text)


def _assertion(f: PlanFact) -> str:
    return _one_line(f.original_assertion.strip())


def render_card(
    card: ValidatedCard, facts: Mapping[int, PlanFact], *, evidence: Sequence[str] = ()
) -> str:
    """카드 본문을 사실 판에서 렌더링한다. 사실을 생략·요약하지 않는다."""
    in_card: dict[int, PlanFact] = {}
    for rid in card.fact_revision_ids():
        f = facts[rid]
        in_card.setdefault(f.fact_id, f)

    def prerequisite_label(fact_id: int) -> str | None:
        f = in_card.get(fact_id)
        if f is None:
            return None
        if f.step_order is not None:
            return f"{f.step_order}번"
        return f"「{_assertion(f)[:40]}」"

    sections: list[str] = []
    for b in card.blocks:
        head = f"[{KIND_LABEL[b.kind]}"
        if b.variant != _NO_VARIANT:
            head += f" · {variant_label(b.variant)}"
        lines = [head + "]"]
        for rid in b.fact_revision_ids:
            f = facts[rid]
            line = f"{f.step_order}. " if b.kind == "STEPS" else "- "
            line += _assertion(f)
            if f.conditions:
                line += f" (조건: {'; '.join(_one_line(c) for c in f.conditions)})"
            if f.exceptions:
                line += f" (예외: {'; '.join(_one_line(c) for c in f.exceptions)})"
            labels = [x for x in (prerequisite_label(r) for r in f.requires_fact_ids) if x]
            if labels:
                line += f" (먼저: {', '.join(labels)})"
            lines.append(line)
        sections.append("\n".join(lines))
    text = "\n\n".join(sections)
    if evidence:
        text += "\n\n" + EVIDENCE_PREFIX + ", ".join(evidence)
    return text


def render_missing(card: ValidatedCard, facts: Mapping[int, PlanFact], content: str) -> list[int]:
    """본문에 원문·조건·예외가 빠진 판 id (정렬·중복 제거)."""
    missing: set[int] = set()
    for rid in card.fact_revision_ids():
        f = facts[rid]
        needles = [_assertion(f), *map(_one_line, f.conditions), *map(_one_line, f.exceptions)]
        if any(n not in content for n in needles):
            missing.add(rid)
    return sorted(missing)
