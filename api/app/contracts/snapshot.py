"""W → R 계약 — 승인 카드 버전에 고정된 불변 묶음 (MVP 31-4).

**snapshot 은 최신 사실을 붙이는 view 가 아니다.** card_version 이 검수한 revision
집합과 블록을 그 시점 그대로 얼려둔 것이다. 최신을 따라가면 승인 전 정정이
공개 답변에 섞이고 과거 인용이 말없이 바뀐다.

CP-01 에서 존재 검사만으로 부족한 것들을 채웠다 (RV-01/02/06/07/09):
  - 존재만 보면 같은 ID 의 서로 다른 사실, 중복 카드·블록이 다 통과한다
  - 선행 관계는 존재뿐 아니라 **순환이 없어야** 절차를 펼칠 수 있다
  - 어느 블록도 가리키지 않는 사실은 R 이 인용할 수 없다. 실어 보낼 이유가 없다
  - 승인된 묶음은 파싱한 뒤에도 바뀌지 않아야 한다
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.card import CardBlock
from app.contracts.common import (
    SCHEMA_PUBLISHED,
    EntityId,
    FrozenContract,
    HashRef,
    Polarity,
    Quantity,
    RawText,
    RevisionId,
    UtcDatetime,
    Variant,
)
from app.contracts.extraction import EvidenceLocator, _first_cycle


class FactProvenance(FrozenContract):
    """이 사실이 어느 자료의 어디에서 나왔는가 (RV-06).

    공개된 사실은 전부 출처를 갖는다. 출처 없는 사실이 실리면 "승인된 매장 지식만
    근거로 답한다" 를 검사할 수 없고, 자료를 지운 뒤 인용 끊김 표시도 못 한다 (D20).
    """

    occurrence_id: EntityId
    source_id: EntityId
    # 자료 내용의 지문. 자료를 지워도 남아 어느 판본에서 나온 말인지 대조한다 (D9·D20)
    source_content_hash: HashRef | None = None
    locator: EvidenceLocator = EvidenceLocator()

    # 자료가 지금 열람 가능한지는 **여기 담지 않는다**. 가변 상태를 불변 묶음에
    # 넣으면 내용이 같은 두 발행의 hash 가 달라진다. 현재 상태는 조회 시 덧입힌다


class FactRevision(FrozenContract):
    """승인된 사실 한 판. 불변이다 — 수정은 새 revision 이다 (MVP 31-2)."""

    fact_revision_id: EntityId
    # revision 이 바뀌어도 따라다니는 사실의 정체. 정정 이력을 이어 붙인다
    fact_id: EntityId
    # 어느 대상에 대한 사실인가. 카드와 같은 축이어야 재분류가 가능하다 (RV-06)
    entity_id: EntityId
    # 원문이 권위 기준이다. 공백까지 그대로 둔다 (RV-07)
    original_assertion: RawText = Field(min_length=1, max_length=2000)
    # 검수된 표현. 원문과 다르면 검수를 거친 것이다
    assertion: str = Field(min_length=1, max_length=2000)
    subject: str | None = Field(default=None, max_length=200)
    predicate: str | None = Field(default=None, max_length=100)
    variant: Variant = Variant()
    quantity: Quantity | None = None
    value_text: str | None = Field(default=None, max_length=500)
    polarity: Polarity = "AFFIRM"
    # 절차 안의 자리. 순서가 바뀌면 의미가 바뀌는 사실이 있다
    order: int | None = Field(default=None, ge=1)
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    requires: tuple[EntityId, ...] = ()
    provenance: tuple[FactProvenance, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _shape(self) -> "FactRevision":
        if self.quantity and self.value_text:
            raise ValueError("수치와 서술값을 동시에 두지 않는다")
        if self.fact_revision_id in self.requires:
            raise ValueError(f"사실 {self.fact_revision_id} 가 자기 자신을 선행 조건으로 둔다")
        if len(set(self.requires)) != len(self.requires):
            raise ValueError(f"사실 {self.fact_revision_id} 의 requires 가 중복됐다")
        return self


class RawSpan(FrozenContract):
    """typed 로 쪼개지 않고 승인된 원문 구간 (RV-05, §3.4).

    RAW 블록이 가리키는 대상이다. snapshot 이 이것을 싣지 않으면 `raw_span_id` 는
    아무 데도 닿지 못하는 참조가 된다 — 블록이 사실을 가리킬 때와 같은 문제다.
    """

    raw_span_id: EntityId
    source_id: EntityId
    text: RawText = Field(min_length=1, max_length=4000)
    locator: EvidenceLocator = EvidenceLocator()


class PublishedCard(FrozenContract):
    card_id: EntityId
    card_version_id: EntityId
    entity_id: EntityId
    variant: Variant = Variant()
    title: str = Field(min_length=1, max_length=120)
    blocks: tuple[CardBlock, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _blocks_distinct(self) -> "PublishedCard":
        ids = [b.block_id for b in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"카드 {self.card_id} 안에 block_id 가 중복됐다")
        orders = [b.order for b in self.blocks]
        if len(orders) != len(set(orders)):
            raise ValueError(f"카드 {self.card_id} 안에 블록 order 가 중복됐다")
        return self


class PublishedKnowledgeSnapshot(FrozenContract):
    """R 이 소비하는 전부. 이 밖의 것은 답변 근거가 될 수 없다."""

    schema_version: Literal["published_knowledge/v1"] = SCHEMA_PUBLISHED
    store_id: EntityId
    # 매장 범위에서 단조 증가한다. 캐시 키와 재현에 쓴다
    knowledge_revision: RevisionId
    snapshot_id: EntityId
    snapshot_hash: HashRef
    created_at: UtcDatetime
    glossary_version: str = Field(max_length=40)
    renderer_version: str = Field(max_length=40)
    cards: tuple[PublishedCard, ...] = ()
    fact_revisions: tuple[FactRevision, ...] = ()
    raw_spans: tuple[RawSpan, ...] = ()

    @model_validator(mode="after")
    def _ids_unique(self) -> "PublishedKnowledgeSnapshot":
        """같은 ID 가 두 번 실리면 존재 검사가 무의미해진다 (RV-01).

        set 으로 존재만 보던 검사는 같은 fact_revision_id 를 가진 서로 다른 사실을
        둘 다 받아들였다. 어느 쪽이 인용되는지는 목록 순서에 달리게 된다.
        """
        for label, values in (
            ("fact_revision_id", [f.fact_revision_id for f in self.fact_revisions]),
            ("card_id", [c.card_id for c in self.cards]),
            ("card_version_id", [c.card_version_id for c in self.cards]),
            ("raw_span_id", [r.raw_span_id for r in self.raw_spans]),
        ):
            dupes = {v for v in values if values.count(v) > 1}
            if dupes:
                raise ValueError(f"snapshot 안에 {label} 가 중복됐다: {sorted(dupes)}")
        return self

    @model_validator(mode="after")
    def _blocks_reference_known_facts(self) -> "PublishedKnowledgeSnapshot":
        """블록이 가리키는 사실이 snapshot 안에 있어야 한다.

        없으면 R 이 인용할 수 없는 카드를 받는다 — 그 상태로 답하면 불변식 3 위반이다.
        """
        known = {f.fact_revision_id for f in self.fact_revisions}
        spans = {r.raw_span_id for r in self.raw_spans}
        for card in self.cards:
            for block in card.blocks:
                missing = [fid for fid in block.fact_revision_ids if fid not in known]
                if missing:
                    raise ValueError(
                        f"카드 {card.card_id} 블록 {block.block_id} 가 "
                        f"snapshot 에 없는 사실을 가리킨다: {missing}")
                if (block.raw_span_id
                        and block.raw_span_id not in spans):
                    raise ValueError(
                        f"카드 {card.card_id} 블록 {block.block_id} 가 "
                        f"snapshot 에 없는 원문 구간을 가리킨다: {block.raw_span_id}")
        return self

    @model_validator(mode="after")
    def _requires_closure(self) -> "PublishedKnowledgeSnapshot":
        """선행 사실도 같이 실려야 하고, 순환하면 안 된다.

        "약품을 넣는다" 가 "먼저 전원을 끈다" 를 요구하는데 그게 빠지면
        위험한 절반만 전달된다. 서로가 서로를 요구하면 무엇을 먼저 보여줄지
        정할 수 없어 렌더러가 돌지 못한다 (RV-02).
        """
        known = {f.fact_revision_id for f in self.fact_revisions}
        for fact in self.fact_revisions:
            missing = [r for r in fact.requires if r not in known]
            if missing:
                raise ValueError(
                    f"사실 {fact.fact_revision_id} 의 선행 사실이 빠졌다: {missing}")
        cycle = _first_cycle(
            {f.fact_revision_id: list(f.requires) for f in self.fact_revisions})
        if cycle:
            raise ValueError(f"선행 사실이 순환한다: {' → '.join(cycle)}")
        return self

    @model_validator(mode="after")
    def _no_orphan_facts(self) -> "PublishedKnowledgeSnapshot":
        """어느 블록도 닿지 못하는 사실은 싣지 않는다 (RV-01).

        R 은 블록을 골라 인용한다. 블록이 가리키지도, 선행 조건으로 끌려오지도 않는
        사실은 인용될 길이 없으면서 snapshot 에만 남는다 — 검수를 거치지 않은 내용이
        공개 묶음에 섞여 나가는 통로가 된다.
        """
        by_id = {f.fact_revision_id: f for f in self.fact_revisions}
        reachable: set[str] = set()
        stack = [fid for c in self.cards for b in c.blocks for fid in b.fact_revision_ids]
        while stack:
            fid = stack.pop()
            if fid in reachable:
                continue
            reachable.add(fid)
            stack.extend(by_id[fid].requires)
        orphans = sorted(set(by_id) - reachable)
        if orphans:
            raise ValueError(f"어느 카드도 인용하지 않는 사실이 실렸다: {orphans}")

        cited_spans = {b.raw_span_id for c in self.cards for b in c.blocks
                       if b.raw_span_id}
        span_orphans = sorted({r.raw_span_id for r in self.raw_spans} - cited_spans)
        if span_orphans:
            raise ValueError(f"어느 카드도 인용하지 않는 원문 구간이 실렸다: {span_orphans}")
        return self

    def fact(self, fact_revision_id: str) -> FactRevision | None:
        return next((f for f in self.fact_revisions
                     if f.fact_revision_id == fact_revision_id), None)

    def card(self, card_id: str) -> PublishedCard | None:
        return next((c for c in self.cards if c.card_id == card_id), None)
