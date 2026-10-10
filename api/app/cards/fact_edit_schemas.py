"""W3b — 점주 사실 카드 편집의 요청·응답·읽기 모델.

사실 카드는 문장 한 덩어리가 아니라 사실(판) 단위로 고친다. 이 파일은 모양만 정한다.
검증 규칙(값-문장 일치, 단계 순서 등)은 fact_edit_plan.py 가 맡는다.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.cards.schemas import CardMutationResult, ReviewStatus

FactPolarity = Literal["AFFIRM", "NEGATE"]
EditBlockKind = Literal["QUANTITIES", "STEPS", "NOTES"]

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ITEM_MAX = 200


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clean_list(values: list[str]) -> list[str]:
    cleaned = [v.strip() for v in values]
    cleaned = [v for v in cleaned if v]
    if any(len(v) > _ITEM_MAX for v in cleaned):
        raise ValueError(f"항목은 {_ITEM_MAX}자 이하여야 합니다.")
    return cleaned


class FactVariant(BaseModel):
    """입·출력 공용 규격."""

    temperature: Literal["HOT", "ICE"] | None = None
    size: str | None = Field(default=None, max_length=20)

    @field_validator("size", mode="before")
    @classmethod
    def _size(cls, value: str | None) -> str | None:
        return _strip_or_none(value) if isinstance(value, str) or value is None else value


class FactFields(BaseModel):
    """입·출력 공용. 점주가 확인하는 사실 한 줄."""

    sentence: str = Field(min_length=1, max_length=2000)
    polarity: FactPolarity = "AFFIRM"
    value: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=10)
    exceptions: list[str] = Field(default_factory=list, max_length=10)
    step_order: int | None = Field(default=None, ge=1, le=999)
    # ADD 만 쓴다. MODIFY 는 서버가 무시한다(고정 판 값 유지)
    variant: FactVariant = Field(default_factory=FactVariant)
    predicate: str | None = Field(default=None, max_length=100)

    @field_validator("sentence", mode="before")
    @classmethod
    def _sentence(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("비워 둘 수 없습니다.")
        return value

    @field_validator("value", "unit", "predicate", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> Any:
        return _strip_or_none(value) if isinstance(value, str) else value

    @field_validator("conditions", "exceptions", mode="before")
    @classmethod
    def _items(cls, value: Any) -> Any:
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return _clean_list(value)
        return value


class EditKeep(BaseModel):
    op: Literal["KEEP"]
    fact_revision_id: int = Field(gt=0)


class EditModify(BaseModel):
    op: Literal["MODIFY"]
    fact_revision_id: int = Field(gt=0)
    fact: FactFields


class EditAdd(BaseModel):
    op: Literal["ADD"]
    client_ref: str = Field(min_length=1, max_length=40)
    fact: FactFields

    @field_validator("client_ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError("영문·숫자·_·- 만 쓸 수 있습니다.")
        return value


EditItem = Annotated[EditKeep | EditModify | EditAdd, Field(discriminator="op")]


class EditBlock(BaseModel):
    kind: EditBlockKind
    items: list[EditItem] = Field(min_length=1, max_length=50)


class FactEditRequest(BaseModel):
    expected_version_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=80)
    # 비면 서버가 CARD_WOULD_BE_EMPTY 로 거절한다
    blocks: list[EditBlock] = Field(default_factory=list, max_length=20)
    deleted_fact_revision_ids: list[int] = Field(default_factory=list, max_length=1000)

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError("영문·숫자·_·- 만 쓸 수 있습니다.")
        return value


class FactParseRequest(BaseModel):
    # 상한은 서버가 설정으로 다시 본다
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["ADD", "MODIFY"] = "ADD"
    base_fact_revision_id: int | None = Field(default=None, gt=0)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("비워 둘 수 없습니다.")
        return value

    @model_validator(mode="after")
    def _mode_base(self) -> "FactParseRequest":
        if self.mode == "MODIFY" and self.base_fact_revision_id is None:
            raise ValueError("MODIFY 에는 base_fact_revision_id 가 필요합니다.")
        if self.mode == "ADD" and self.base_fact_revision_id is not None:
            raise ValueError("ADD 에는 base_fact_revision_id 를 쓸 수 없습니다.")
        return self


class ParsedFactProposal(BaseModel):
    client_ref: str
    fact: FactFields
    block_kind: EditBlockKind
    warnings: list[str] = Field(default_factory=list)


class FactParseResponse(BaseModel):
    mode: Literal["ADD", "MODIFY"]
    proposals: list[ParsedFactProposal]
    warnings: list[str] = Field(default_factory=list)


class FactRevisionResult(BaseModel):
    op: Literal["MODIFY", "ADD"]
    client_ref: str | None = None
    base_fact_revision_id: int | None = None
    fact_revision_id: int


class FactEditResult(CardMutationResult):
    changed: bool
    edit_id: int
    revisions: list[FactRevisionResult] = Field(default_factory=list)


# ── 읽기 모델 (Task 3 이 채운다) ────────────────────────────────────────────


class FactOrigin(BaseModel):
    # OWNER_TEXT = source_type 이 OWNER_TEXT 인 자료(점주 직접 입력)
    kind: Literal["SOURCE", "OWNER_ANSWER", "OWNER_TEXT"]
    source_id: int | None = None
    source_title: str | None = None
    source_type: str | None = None
    source_availability: Literal["AVAILABLE", "DELETED", "UNAVAILABLE"] | None = None
    locator_type: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    owner_answer_id: int | None = None
    created_at: datetime | None = None


class FactRequirement(BaseModel):
    fact_id: int
    label: str


class FactRow(BaseModel):
    fact_revision_id: int
    fact_id: int
    position: int
    sentence: str
    assertion: str
    subject: str | None = None
    predicate: str | None = None
    variant: FactVariant = Field(default_factory=FactVariant)
    value: str | None = None
    unit: str | None = None
    polarity: FactPolarity
    step_order: int | None = None
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    requires: list[FactRequirement] = Field(default_factory=list)
    change_kind: str | None = None
    previous_sentence: str | None = None
    origins: list[FactOrigin] = Field(default_factory=list)
    edit_block: Literal["CHANGED_ELSEWHERE", "MOVED_ENTITY"] | None = None


class FactBlockView(BaseModel):
    block_id: str
    kind: Literal["QUANTITIES", "STEPS", "NOTES", "RAW"]
    order: int
    variant: FactVariant = Field(default_factory=FactVariant)
    facts: list[FactRow]


class CardFactsView(BaseModel):
    card_id: int
    version_id: int
    title: str
    entity_id: int | None = None
    entity_name: str | None = None
    review_status: ReviewStatus
    published_version_id: int | None = None
    editable: bool
    entity_problem: Literal["MIXED_ENTITY", "MERGED_ENTITY"] | None = None
    blocks: list[FactBlockView]
