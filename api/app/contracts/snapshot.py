"""W → R 계약 — 승인 카드 버전에 고정된 불변 묶음 (MVP 31-4).

**snapshot 은 최신 사실을 붙이는 view 가 아니다.** card_version 이 검수한 revision
집합과 블록을 그 시점 그대로 얼려둔 것이다. 최신을 따라가면 승인 전 정정이
공개 답변에 섞이고 과거 인용이 말없이 바뀐다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.card import CardBlock
from app.contracts.common import (
    SCHEMA_PUBLISHED,
    Contract,
    EntityId,
    Polarity,
    Quantity,
    Variant,
)


class FactRevision(Contract):
    """승인된 사실 한 판. 불변이다 — 수정은 새 revision 이다 (MVP 31-2)."""

    fact_revision_id: EntityId
    assertion: str = Field(min_length=1, max_length=2000)
    subject: str | None = Field(default=None, max_length=200)
    predicate: str | None = Field(default=None, max_length=100)
    variant: Variant = Variant()
    quantity: Quantity | None = None
    value_text: str | None = Field(default=None, max_length=500)
    polarity: Polarity = "AFFIRM"
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    requires: list[EntityId] = Field(default_factory=list)
    evidence_occurrence_ids: list[EntityId] = Field(default_factory=list)


class PublishedCard(Contract):
    card_id: EntityId
    card_version_id: EntityId
    entity_id: EntityId
    variant: Variant = Variant()
    title: str = Field(min_length=1, max_length=120)
    blocks: list[CardBlock] = Field(min_length=1, max_length=20)


class PublishedKnowledgeSnapshot(Contract):
    """R 이 소비하는 전부. 이 밖의 것은 답변 근거가 될 수 없다."""

    schema_version: Literal["published_knowledge/v1"] = SCHEMA_PUBLISHED
    store_id: EntityId
    # 매장 범위에서 단조 증가한다. 캐시 키와 재현에 쓴다
    knowledge_revision: int = Field(ge=0)
    snapshot_id: EntityId
    snapshot_hash: str = Field(min_length=8, max_length=128)
    created_at: datetime
    glossary_version: str = Field(max_length=40)
    renderer_version: str = Field(max_length=40)
    cards: list[PublishedCard] = Field(default_factory=list)
    fact_revisions: list[FactRevision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _blocks_reference_known_facts(self) -> "PublishedKnowledgeSnapshot":
        """블록이 가리키는 사실이 snapshot 안에 있어야 한다.

        없으면 R 이 인용할 수 없는 카드를 받는다 — 그 상태로 답하면 불변식 3 위반이다.
        """
        known = {f.fact_revision_id for f in self.fact_revisions}
        for card in self.cards:
            for block in card.blocks:
                missing = [fid for fid in block.fact_revision_ids if fid not in known]
                if missing:
                    raise ValueError(
                        f"카드 {card.card_id} 블록 {block.block_id} 가 "
                        f"snapshot 에 없는 사실을 가리킨다: {missing}")
        return self

    @model_validator(mode="after")
    def _requires_closure(self) -> "PublishedKnowledgeSnapshot":
        """선행 사실도 같이 실려야 한다.

        "약품을 넣는다" 가 "먼저 전원을 끈다" 를 요구하는데 그게 빠지면
        위험한 절반만 전달된다.
        """
        known = {f.fact_revision_id for f in self.fact_revisions}
        for fact in self.fact_revisions:
            missing = [r for r in fact.requires if r not in known]
            if missing:
                raise ValueError(
                    f"사실 {fact.fact_revision_id} 의 선행 사실이 빠졌다: {missing}")
        return self
