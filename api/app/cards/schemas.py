from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ReviewStatus = Literal["PENDING", "NEEDS_REVIEW", "APPROVED", "EXCLUDED"]


class CardCategory(BaseModel):
    category_id: int
    name: str
    # 카테고리 종류(계획 7 Task 2). 비어 있으면 이름 규칙
    kind: str | None = None


class CardSource(BaseModel):
    source_id: int
    title: str | None = None
    source_type: str | None = None
    read_url: str | None = None
    # D20: 자료가 삭제(DELETED)되면 원본을 열 수 없다. 화면은 '인용 끊김' 으로 표시한다
    source_availability: Literal["AVAILABLE", "DELETED", "UNAVAILABLE"] = "AVAILABLE"


class CardListItem(BaseModel):
    card_id: int
    review_status: ReviewStatus
    title: str
    content: str
    category: CardCategory | None = None
    assignment_type: Literal["AUTOMATIC", "MANUAL"]
    source: CardSource | None = None
    job_id: int | None = None
    has_evidence: bool
    needs_review_reason: str | None = None
    updated_at: datetime


class CardList(BaseModel):
    items: list[CardListItem]
    next_cursor: int | None = None
    total: int


class CardVersion(BaseModel):
    version_id: int
    version_no: int
    title: str
    content: str
    change_source: str
    created_at: datetime


class CardEvidence(BaseModel):
    evidence_id: int
    locator_type: str
    locator: dict[str, Any]
    excerpt: str | None = None
    source: CardSource


class CardReviewEvent(BaseModel):
    event_id: int
    action: str
    from_status: str | None = None
    to_status: str | None = None
    from_category_id: int | None = None
    to_category_id: int | None = None
    metadata: dict[str, Any]
    created_at: datetime


class CardDetail(BaseModel):
    card_id: int
    review_status: ReviewStatus
    assignment_type: Literal["AUTOMATIC", "MANUAL"]
    category: CardCategory | None = None
    source: CardSource | None = None
    job_id: int | None = None
    needs_review_reason: str | None = None
    draft: CardVersion | None = None
    published: CardVersion | None = None
    evidence: list[CardEvidence] = Field(default_factory=list)
    events: list[CardReviewEvent] = Field(default_factory=list)
    updated_at: datetime
    # W3b — 사실 카드(블록 사실이 고정된 초안)인지
    fact_card: bool = False


class CategoryUpdateRequest(BaseModel):
    category_id: int = Field(gt=0)
    expected_updated_at: datetime

    @field_validator("expected_updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expected_updated_at에는 시간대가 필요합니다.")
        return value


class CardMutationResult(BaseModel):
    card_id: int
    review_status: ReviewStatus
    draft_version_id: int | None = None
    published_version_id: int | None = None
    updated_at: datetime
    undo_until: datetime | None = None


class BulkRequest(BaseModel):
    """카드 일괄 처리(계획 7 Task 4). 이동은 category_id 가 있어야 한다."""

    action: Literal["approve", "unpublish", "exclude", "restore", "move"]
    card_ids: list[int] = Field(min_length=1, max_length=200)
    category_id: int | None = None

    @model_validator(mode="after")
    def _move_has_category(self) -> "BulkRequest":
        if self.action == "move" and self.category_id is None:
            raise ValueError("옮길 카테고리를 골라 주세요.")
        if any(card_id <= 0 for card_id in self.card_ids):
            raise ValueError("카드 번호가 올바르지 않습니다.")
        return self


class BulkItem(BaseModel):
    card_id: int
    ok: bool
    review_status: str | None = None
    error: dict[str, str] | None = None


class BulkResult(BaseModel):
    results: list[BulkItem]
