from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CategoryItem(BaseModel):
    category_id: int
    name: str
    is_system: bool
    sort_order: int


class ReclassificationSummary(BaseModel):
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "STALE"]
    job_id: int


class CategoryList(BaseModel):
    version: int
    items: list[CategoryItem]
    reclassification: ReclassificationSummary | None = None


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(default=0, ge=0, le=9998)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("카테고리 이름을 입력해 주세요.")
        return normalized


class CategoryMutationResult(BaseModel):
    category: CategoryItem
    version: int
    reclass_job_id: int | None = None


class DeleteCategoryResult(BaseModel):
    category_id: int
    version: int
    reclass_job_id: int | None = None


class ReclassificationJob(BaseModel):
    job_id: int
    target_category_version: int
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "STALE"]
    total_count: int
    applied_count: int
    skipped_count: int
    failed_count: int
    error: dict[str, str] | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ClassificationChoice(BaseModel):
    card_id: int
    category_name: str


class ClassificationBatch(BaseModel):
    items: list[ClassificationChoice]
