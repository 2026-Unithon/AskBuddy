from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.cards.schemas import CardCategory, CardEvidence

LearningStatus = Literal["NOT_STARTED", "DONE", "RECONFIRM_REQUIRED"]


class RoadmapStore(BaseModel):
    store_id: int
    name: str


class RoadmapCounts(BaseModel):
    total: int
    done: int
    reconfirm_required: int


class RoadmapItem(BaseModel):
    item_id: int
    card_id: int
    published_version_id: int
    title: str
    status: LearningStatus


class RoadmapStage(BaseModel):
    category_id: int
    name: str
    order: int
    items: list[RoadmapItem]


class RoadmapResponse(BaseModel):
    store: RoadmapStore
    counts: RoadmapCounts
    continue_item_id: int | None = None
    stages: list[RoadmapStage]


class LearnItemDetail(BaseModel):
    item_id: int
    card_id: int
    published_version_id: int
    title: str
    content: str
    status: LearningStatus
    category: CardCategory
    evidence: list[CardEvidence]
    return_to: dict[str, str | int]


class CompletionRequest(BaseModel):
    published_version_id: int
    completed: bool


class CompletionResult(BaseModel):
    item_id: int
    card_id: int
    published_version_id: int
    status: LearningStatus
    counts: RoadmapCounts
