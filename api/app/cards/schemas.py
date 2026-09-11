from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ReviewStatus = Literal["PENDING", "NEEDS_REVIEW", "APPROVED", "EXCLUDED"]


class CardCategory(BaseModel):
    category_id: int
    name: str


class CardSource(BaseModel):
    source_id: int
    title: str | None = None
    source_type: str | None = None
    read_url: str | None = None


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


class DraftUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    expected_version_id: int = Field(gt=0)

    @field_validator("title", "content")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("비워 둘 수 없습니다.")
        return value


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
