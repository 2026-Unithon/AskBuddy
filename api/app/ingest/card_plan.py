"""카드 계획 검증·대체 계획·서버 렌더링 (W3a, D23). DB·모델·설정에 닿지 않는 순수 모듈.

모델은 구역(heading)·순서·줄 글을 쓰고 줄마다 근거 사실을 단다(D23). 서버는 줄이 근거 사실에
없는 숫자·단위를 지어냈는지, 사실 값을 빠뜨렸는지만 문자열로 검사한다(`line_check`).
검사에 실패한 줄만 사실 원문으로 바꾸고, 빠진 사실은 원문 줄로 덧붙인다. 이름표가 틀리거나
줄이 하나도 없으면 계획을 버리고 결정적 대체 계획(규격마다 원문 줄)으로 간다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace, dataclass
import re
from decimal import Decimal

from app.contracts.card import CardBlock, CardPlan, DisplayLine
from app.contracts.common import Variant
from app.ingest.line_check import check_line, uncovered_facts

KIND_RANK = {"QUANTITIES": 1, "STEPS": 2, "NOTES": 3}
NO_VARIANT_LABEL = "규격 표시 없음"
MAX_FACTS_PER_BLOCK = 50
MAX_LINES_PER_BLOCK = 60
MAX_BLOCKS_PER_CARD = 20
HEADING_MAX = 40
LINE_MAX = 300
# 모델이 실패해 대체 계획을 쓴 카드의 검수 표시(카드 단위)
AUTO_LAYOUT = "AUTO_LAYOUT"
TITLE_MAX = 120
NAME_MAX = 100

# 계획 오류 — 모델 계획을 버리고 대체 계획을 쓴다
PLAN_EMPTY = "PLAN_EMPTY"
PLAN_UNKNOWN_REF = "PLAN_UNKNOWN_REF"
PLAN_OUTSIDE_GROUP = "PLAN_OUTSIDE_GROUP"
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
class ProposedLine:
    # 모델(또는 사장님)이 쓴 줄 글. None 이면 인용한 사실마다 원문 줄을 서버가 쓴다
    text: str | None
    refs: tuple[int | str, ...]  # 판 id(int) 또는 풀지 못한 이름표(str)


@dataclass(frozen=True)
class ProposedBlock:
    kind: str  # 모델이 준 그대로
    heading: str | None = None
    lines: tuple[ProposedLine, ...] = ()

    @classmethod
    def from_refs(cls, kind: str, refs: Sequence[int | str], heading: str | None = None) -> "ProposedBlock":
        """글 없이 사실만 고른 블록 — 사실마다 원문 줄."""
        return cls(kind=kind, heading=heading, lines=tuple(ProposedLine(None, (r,)) for r in refs))

    @property
    def refs(self) -> tuple[int | str, ...]:
        """줄 순서대로, 중복 없이."""
        seen: dict[int | str, None] = {}
        for line in self.lines:
            for r in line.refs:
                seen.setdefault(r, None)
        return tuple(seen)


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
    variant: VariantKey  # 블록 사실 규격이 모두 같으면 그 값, 아니면 (None, None)
    heading: str | None = None
    # (줄 글, 근거 판 id 들). 검사를 거친 표시 줄(D23)
    lines: tuple[tuple[str, tuple[int, ...]], ...] = ()


@dataclass(frozen=True)
class ValidatedCard:
    entity_id: int
    title: str
    category_name: str
    variant: VariantKey  # 모든 블록 규격이 같으면 그 값, 아니면 (None, None)
    blocks: tuple[ValidatedBlock, ...]
    # 모델 계획을 버리고 대체 계획을 썼으면 AUTO_LAYOUT
    needs_review_reason: str | None = None

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
                    heading=b.heading,
                    lines=tuple(DisplayLine(text=t, fact_revision_ids=tuple(str(r) for r in refs))
                                for t, refs in b.lines),
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

    규격 꼬리표(" (ICE)")를 붙이지 않는다. R 은 공개 사실의 subject와 entity_id로
    대상을 찾으므로 분할 번호는 대상 이름으로 취급하지 않는다.
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


def _one_heading(text: str | None) -> str | None:
    text = _one_line((text or "").strip())[:HEADING_MAX].strip()
    return text or None


def raw_line_text(f: PlanFact) -> str:
    """사실 원문 줄: 보이는 문장 + 문장에 없는 조건·예외. 한 줄로 접는다."""
    text = _assertion(f)
    extra_cond = [_one_line(c) for c in f.conditions if _one_line(c) not in text]
    extra_exc = [_one_line(c) for c in f.exceptions if _one_line(c) not in text]
    if extra_cond:
        text += f" (조건: {'; '.join(extra_cond)})"
    if extra_exc:
        text += f" (예외: {'; '.join(extra_exc)})"
    return text[:LINE_MAX]


def _raw_lines(refs: Sequence[int], by_id: Mapping[int, PlanFact]) -> list[tuple[str, tuple[int, ...]]]:
    """사실마다 원문 줄. 한 문장에서 값마다 나뉜 사실은 같은 글이라 한 줄로 합친다."""
    merged: dict[str, list[int]] = {}
    for r in refs:
        merged.setdefault(raw_line_text(by_id[r]), []).append(r)
    return [(text, tuple(ids)) for text, ids in merged.items()]


def _block_variant(refs: Sequence[int], by_id: Mapping[int, PlanFact]) -> VariantKey:
    variants = {by_id[r].variant for r in refs}
    return next(iter(variants)) if len(variants) == 1 else _NO_VARIANT


def _chunk_lines(lines: Sequence[tuple[str, tuple[int, ...]]]) -> list[list[tuple[str, tuple[int, ...]]]]:
    """블록 한 개가 사실 50개·줄 60개를 넘지 않게 줄 경계에서 자른다."""
    out: list[list[tuple[str, tuple[int, ...]]]] = []
    current: list[tuple[str, tuple[int, ...]]] = []
    facts: set[int] = set()
    for line in lines:
        grown = facts | set(line[1])
        if current and (len(grown) > MAX_FACTS_PER_BLOCK or len(current) >= MAX_LINES_PER_BLOCK):
            out.append(current)
            current, facts = [], set()
            grown = set(line[1])
        current.append(line)
        facts = grown
    if current:
        out.append(current)
    return out


def validate_proposals(
    group: EntityGroup, proposals: Sequence[ProposedCard], *, check_lines: bool = True
) -> tuple[ValidatedCard, ...]:
    """모델(또는 사장님) 계획 → 검사한 카드들.

    버리는 것(PlanInvalid): 줄이 하나도 없음, 모르는 이름표, 다른 대상의 사실, 어디에도 없는 사실.
    구역·순서·종류·규격 섞기·한 사실 여러 줄은 막지 않는다(D23 — 모양은 모델이 정한다).
    `check_lines` 이면 줄마다 지어냄을 검사해 실패한 줄을 원문으로 바꾸고, 빠진 사실을 덧붙인다.
    사장님 줄은 검사하지 않는다(사장님이 원천이다).
    """
    by_id = {f.fact_revision_id: f for f in group.facts}

    # 1) 근거 없는 줄·빈 블록·빈 카드를 버린다
    cards: list[tuple[str, list[ProposedBlock]]] = []
    for p in proposals:
        blocks = []
        for b in p.blocks:
            lines = tuple(line for line in b.lines if line.refs)
            if lines:
                blocks.append(replace(b, lines=lines))
        if blocks:
            cards.append((p.category_name, blocks))
    if not cards:
        raise PlanInvalid(PLAN_EMPTY)

    # 2) 이름표
    for _, blocks in cards:
        for b in blocks:
            for line in b.lines:
                if any(type(r) is not int for r in line.refs):
                    raise PlanInvalid(PLAN_UNKNOWN_REF)
                if any(r not in by_id for r in line.refs):
                    raise PlanInvalid(PLAN_OUTSIDE_GROUP)

    # 3) 줄 검사 — 지어낸 줄은 그 줄이 인용한 사실마다 원문 줄로
    checked: list[tuple[str, list[tuple[str, str | None, list[tuple[str, tuple[int, ...]]]]]]] = []
    for category, blocks in cards:
        out_blocks = []
        for b in blocks:
            kind = b.kind if b.kind in KIND_RANK else "NOTES"
            lines: list[tuple[str, tuple[int, ...]]] = []
            for line in b.lines:
                refs = tuple(dict.fromkeys(int(r) for r in line.refs))
                text = _one_line((line.text or "").strip())
                if line.text is None or not text or len(text) > LINE_MAX or (
                        check_lines and check_line(text, [by_id[r] for r in refs]) is not None):
                    lines.extend(_raw_lines(refs, by_id))
                else:
                    lines.append((text, refs))
            out_blocks.append((kind, _one_heading(b.heading), lines))
        checked.append((category, out_blocks))

    # 4) 빠뜨림 — 인용했지만 값이 빠진 사실은 그 블록 끝에, 어디에도 없는 사실은 마지막 블록 끝에
    if check_lines:
        for _, blocks in checked:
            card_lines = [line for _, _, lines in blocks for line in lines]
            cited = list(dict.fromkeys(r for _, refs in card_lines for r in refs))
            for rid in uncovered_facts(card_lines, [by_id[r] for r in cited]):
                target = next(lines for _, _, lines in blocks if any(rid in refs for _, refs in lines))
                target.extend(_raw_lines([rid], by_id))
        everywhere = {r for _, blocks in checked for _, _, lines in blocks for _, refs in lines for r in refs}
        missing = [f.fact_revision_id for f in group.facts if f.fact_revision_id not in everywhere]
        if missing:
            checked[-1][1][-1][2].extend(_raw_lines(missing, by_id))

    # 붙어 있는 같은 글 줄은 한 줄로(한 문장에서 값마다 나뉜 사실). 근거는 합친다
    for _, blocks in checked:
        for i, (kind, heading, lines) in enumerate(blocks):
            merged: list[tuple[str, tuple[int, ...]]] = []
            for text, refs in lines:
                if merged and merged[-1][0] == text:
                    merged[-1] = (text, tuple(dict.fromkeys((*merged[-1][1], *refs))))
                else:
                    merged.append((text, refs))
            blocks[i] = (kind, heading, merged)

    # 5) 블록·카드를 한도에 맞게 나눈다
    split: list[tuple[str, list[tuple[str, str | None, list[tuple[str, tuple[int, ...]]]]]]] = []
    for category, blocks in checked:
        pieces = [(kind, heading, chunk) for kind, heading, lines in blocks for chunk in _chunk_lines(lines)]
        for part in _chunks(pieces, MAX_BLOCKS_PER_CARD):
            split.append((category, part))

    # 6) 어느 카드에도 없는 판
    placed = {r for _, part in split for _, _, lines in part for _, refs in lines for r in refs}
    if any(f.fact_revision_id not in placed for f in group.facts):
        raise PlanInvalid(PLAN_UNPLACED)

    # 7) 결과
    total = len(split)
    result: list[ValidatedCard] = []
    for i, (category, part) in enumerate(split, start=1):
        blocks_out: list[ValidatedBlock] = []
        for n, (kind, heading, lines) in enumerate(part, start=1):
            refs = tuple(dict.fromkeys(r for _, line_refs in lines for r in line_refs))
            blocks_out.append(ValidatedBlock(
                block_id=f"b{n}", kind=kind, order=n, fact_revision_ids=refs,
                variant=_block_variant(refs, by_id), heading=heading, lines=tuple(lines)))
        variants = {b.variant for b in blocks_out}
        variant = next(iter(variants)) if len(variants) == 1 else _NO_VARIANT
        result.append(ValidatedCard(
            entity_id=group.entity_id,
            title=card_title(group.canonical_name, i, total),
            category_name=category.strip() or "기타",
            variant=variant,
            blocks=tuple(blocks_out)))
    return tuple(result)


def fallback_cards(group: EntityGroup, *, category_name: str) -> tuple[ValidatedCard, ...]:
    """모델이 실패했을 때만. 규격마다 블록 하나, 줄 = 사실 원문, 구역 제목 = 규격 이름(없으면 없음).

    종류는 NOTES(목록)다 — 사실 모양으로 단계를 추측하지 않는다(D23).
    """
    variants = sorted(
        {f.variant for f in group.facts},
        key=lambda v: (v[0] is None, v[0] or "", v[1] is None, v[1] or ""),
    )
    blocks = [
        ProposedBlock.from_refs(
            "NOTES", [f.fact_revision_id for f in group.facts if f.variant == v],
            heading=(variant_label(v) if v != _NO_VARIANT else None))
        for v in variants
    ]
    try:
        cards = validate_proposals(group, [ProposedCard(category_name, tuple(blocks))])
    except PlanInvalid as e:
        raise PlanInvalid(DATA_TOO_LARGE, e.code) from e
    return tuple(replace(c, needs_review_reason=AUTO_LAYOUT) for c in cards)


_SEQUENCE_MARK = re.compile(r"→|->|⇒|➔")


def normalize_step_orders(facts: Sequence[PlanFact]) -> list[PlanFact]:
    """추출이 단계가 아닌 사실에 붙인 번호를 뗀다(계획 6, 결정적 규칙·모델 호출 없음).

    단계로 인정하는 것: 문장에 순서 표시(→)가 있거나, 같은 규격에서 그 번호를 그 사실 하나만 쓸 때.
    버리는 것: 같은 규격에서 다른 문장의 사실과 같은 번호를 나눠 쓸 때(메뉴 표의 칸마다 1번),
    순서 표시 없는 한 문장에서 번호가 여러 개일 때(값 나열 순번).
    저장된 판은 바꾸지 않고, 조립·렌더에 쓰는 사본만 고친다.
    """
    out: list[PlanFact] = []
    for f in facts:
        if f.step_order is None or _SEQUENCE_MARK.search(f.original_assertion or ""):
            out.append(f)
            continue
        same_number_other_sentence = any(
            g is not f and g.variant == f.variant and g.step_order == f.step_order
            and g.original_assertion.strip() != f.original_assertion.strip()
            and not _SEQUENCE_MARK.search(g.original_assertion or "")
            for g in facts
        )
        listed_in_one_sentence = any(
            g is not f and g.step_order is not None and g.step_order != f.step_order
            and g.original_assertion.strip() == f.original_assertion.strip()
            for g in facts
        )
        out.append(replace(f, step_order=None) if same_number_other_sentence or listed_in_one_sentence else f)
    return out


def _kind_of(f: PlanFact) -> str:
    """fallback_cards 와 같은 종류 규칙."""
    if f.step_order is not None:
        return "STEPS"
    if f.polarity == "AFFIRM" and f.quantity_value is not None:
        return "QUANTITIES"
    return "NOTES"


def append_facts(layout: Sequence[tuple[str, tuple[int, ...]]], group: EntityGroup,
                 new_ids: Sequence[int], *, category_name: str,
                 display: Sequence[tuple[str | None, Sequence[tuple[str, tuple[int, ...]]]]] | None = None
                 ) -> ValidatedCard:
    """공개 판 배치를 그대로 두고 새 사실만 붙인다. 모델을 부르지 않는다(A-D4).

    layout 은 공개 판의 (종류, 판 id 들) 블록 순서다. display 는 같은 순서의 (구역 제목, 표시 줄)이다 —
    있으면 그 줄을 그대로 두고(모델·사장님이 쓴 글), 새 사실은 원문 줄로 붙인다. 줄이 없는 옛 판은
    사실마다 원문 줄이다. 새 사실은 같은 종류·같은 규격의 첫 블록 끝에, 맞는 블록이 없으면 그 종류의
    새 블록을 끝에 둔다. 이미 검사한 줄을 다시 검사하지 않는다. 카드가 한 장이 아니면 거절한다.
    """
    by_id = {f.fact_revision_id: f for f in group.facts}
    blocks: list[tuple[str, list[int], str | None, list[ProposedLine]]] = []
    for i, (kind, ids) in enumerate(layout):
        if any(r not in by_id for r in ids):
            raise PlanInvalid(PLAN_OUTSIDE_GROUP, "layout")
        heading, shown = (display[i] if display is not None and i < len(display) else (None, ()))
        lines = [ProposedLine(text, tuple(refs)) for text, refs in shown]
        cited = {r for line in lines for r in line.refs}
        # 줄이 인용하지 않은 블록 사실(옛 판)은 원문 줄로
        lines.extend(ProposedLine(None, (r,)) for r in ids if r not in cited)
        blocks.append((kind, list(ids), heading, lines))
    for rid in new_ids:
        f = by_id.get(rid)
        if f is None:
            raise PlanInvalid(PLAN_OUTSIDE_GROUP, f"new={rid}")
        kind = _kind_of(f)
        target = next((b for b in blocks
                       if b[0] == kind and b[1] and by_id[b[1][0]].variant == f.variant), None)
        if target is None:
            blocks.append((kind, [rid], None, [ProposedLine(None, (rid,))]))
            continue
        target[1].append(rid)
        target[3].append(ProposedLine(None, (rid,)))
    proposal = ProposedCard(category_name, tuple(
        ProposedBlock(kind=k, heading=h, lines=tuple(lines)) for k, _, h, lines in blocks))
    cards = validate_proposals(group, [proposal], check_lines=False)
    if len(cards) != 1:
        raise PlanInvalid(DATA_TOO_LARGE, "append")
    return cards[0]


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
    # 카드에는 보이는 문장(정리한 글, 검사를 못 넘으면 원문)을 쓴다(2026-11-08 '원문 그대로' 제거)
    return _one_line((f.assertion or f.original_assertion).strip())


def card_content(blocks: Sequence[ValidatedBlock]) -> str:
    """판 본문(검색·임베딩이 쓰는 글) = 블록 순서대로 구역 제목(있으면) + 줄 글, 줄바꿈으로 잇는다 (D23)."""
    out: list[str] = []
    for b in sorted(blocks, key=lambda b: b.order):
        if b.heading:
            out.append(b.heading)
        out.extend(text for text, _ in b.lines)
    return "\n".join(out)
