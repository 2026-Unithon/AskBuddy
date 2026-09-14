"""카드 계약 — 사실을 어떻게 보여줄 것인가 (MVP 31-3, D19).

**카드는 지식을 담는 그릇이 아니라 사실을 보여주는 방식이다.**
고정 필드를 두면 안 맞는 사실은 버려지고 빈 칸은 지어내진다. 그래서 필드가 아니라
**블록**을 고정한다 — 해당 사실이 없으면 그 블록이 통째로 빠진다.

업무 사실을 자유 생성하는 설명 필드를 두지 않는다. 블록은 **사실을 고를 뿐**
새 문장을 만들지 않는다 (MVP 31-3).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import (
    SCHEMA_CARD_PLAN,
    Contract,
    EntityId,
    FrozenContract,
    UtcDatetime,
    Variant,
)

BlockKind = Literal["QUANTITIES", "STEPS", "NOTES", "RAW"]
"""
QUANTITIES  대상·규격·속성·값·단위와 적용 조건을 한 단위로
STEPS       순서·선행조건·필수 주의를 함께. 번호를 임의로 바꾸면 의미가 바뀐다
NOTES       부정·예외·주의·서술형을 원문 또는 검수된 표현으로
RAW         typed 파싱이 불확실한 승인 원문 그대로. **답변 가능 판정은 아니다**
"""

# 추출 occurrence 의 카드 반영 처분. 공개 승인과는 별개 상태다 (MVP 31-3)
Disposition = Literal["LINKED", "REVIEW_PENDING", "EXCLUDED"]


class CardBlock(FrozenContract):
    """카드의 한 줄. 사실을 고를 뿐 새 사실을 만들지 않는다.

    승인 snapshot 에 그대로 실리므로 불변이다. 인용 목록을 파싱 뒤에 늘릴 수 있으면
    "승인된 것만 인용한다" 가 검증이 아니라 약속이 된다 (RV-07).
    """

    block_id: str = Field(min_length=1, max_length=40)
    kind: BlockKind
    # 카드 안의 자리. 리스트 순서에만 기대면 DB 왕복·재직렬화에서 뒤집힌다.
    # STEPS 에서 순서가 바뀌면 절차가 달라진다 (RV-06)
    order: int = Field(ge=1)
    # 이 블록이 보여줄 사실들. 비면 블록 자체를 만들지 않는다
    fact_revision_ids: tuple[EntityId, ...] = Field(default=(), max_length=50)
    # RAW 전용 — typed 로 쪼개지 않고 승인된 원문 구간 (RV-05).
    # 이것이 없으면 승인된 원문 카드를 표현하려고 사실을 억지로 만들어야 했다
    raw_span_id: EntityId | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> "CardBlock":
        if self.kind == "RAW":
            if not self.fact_revision_ids and not self.raw_span_id:
                raise ValueError("RAW 블록에는 사실이나 원문 구간 중 하나가 필요하다")
        else:
            if self.raw_span_id:
                raise ValueError(f"{self.kind} 블록은 원문 구간을 직접 인용하지 않는다")
            if not self.fact_revision_ids:
                raise ValueError(f"{self.kind} 블록에는 사실이 최소 하나 필요하다")
        if len(set(self.fact_revision_ids)) != len(self.fact_revision_ids):
            raise ValueError(f"블록 {self.block_id} 안에서 같은 사실을 두 번 인용했다")
        return self


class CardPlan(Contract):
    """조립 결과. 아직 공개된 것이 아니라 검수 대기 상태다."""

    schema_version: Literal["card_plan/v1"] = SCHEMA_CARD_PLAN
    entity_id: EntityId
    # 같은 메뉴의 다른 규격은 한 카드에 담되 값은 블록에서 규격별로 나뉜다 (D19)
    variant: Variant = Variant()
    title: str = Field(min_length=1, max_length=120)
    blocks: list[CardBlock] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _no_duplicate_blocks(self) -> "CardPlan":
        ids = [b.block_id for b in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block_id 가 중복됐다")
        orders = [b.order for b in self.blocks]
        if len(orders) != len(set(orders)):
            raise ValueError("블록 order 가 중복됐다. 자리가 둘이면 순서가 정해지지 않는다")
        return self

    def fact_ids(self) -> set[str]:
        """이 카드가 담은 사실 전부. 조립 커버리지 검사가 이걸 쓴다."""
        return {fid for b in self.blocks for fid in b.fact_revision_ids}


class OccurrenceDisposition(Contract):
    """추출 occurrence 하나가 카드에 어떻게 반영됐는가.

    **주체는 occurrence 다** (RV-08). 같은 사실이 자료 여러 곳에 나오면 판정도
    여러 건이다. 사실 단위로만 기록하면 "3번 나왔고 2번은 제외했다" 가 한 줄로
    뭉개져 무엇이 왜 빠졌는지 되짚을 수 없다.

    이유 없는 미처리를 남기지 않는다. 보류·제외를 늘려 지표를 부풀리지 않도록
    원본 truth 대비 공개 커버리지와 함께 보고한다 (MVP 31-3).
    """

    occurrence_id: EntityId
    fact_revision_id: EntityId | None = None
    disposition: Disposition
    # LINKED 면 어느 카드의 어느 블록에 실렸는가
    card_id: EntityId | None = None
    block_id: str | None = Field(default=None, max_length=40)
    # REVIEW_PENDING·EXCLUDED 는 사유가 필수다
    reason: str | None = Field(default=None, max_length=300)
    decided_by: EntityId | None = None
    decided_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _reason_required(self) -> "OccurrenceDisposition":
        if self.disposition == "LINKED":
            if not self.fact_revision_id:
                raise ValueError("LINKED 는 어느 사실 판에 실렸는지가 있어야 한다")
            if not self.card_id or not self.block_id:
                raise ValueError("LINKED 는 실린 카드·블록을 남긴다")
        else:
            if not self.reason:
                raise ValueError(f"{self.disposition} 에는 사유가 필요하다")
            if self.card_id or self.block_id:
                raise ValueError(f"{self.disposition} 는 카드에 실리지 않는다")
        return self
