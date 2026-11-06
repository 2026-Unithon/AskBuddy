"""오늘만 할 일 요청 본문. store_id 는 받지 않는다 (JWT 만)."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.checklist.schemas import PositiveId

MAX_TEXT = 300
MAX_TARGETS = 30


def _clean(value: str) -> str:
    # 줄바꿈은 살리고 줄 안의 겹친 공백만 줄인다
    lines = [" ".join(line.split()) for line in value.strip().splitlines()]
    value = "\n".join(line for line in lines if line)
    if not value:
        raise ValueError("할 일을 적어 주세요")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{MAX_TEXT}자 안으로 적어 주세요")
    return value


class TodayTaskCreate(BaseModel):
    # 사장이 처음 적은 글. 다듬은 문장을 보내도 원문은 남긴다
    text: str
    # 사장이 확인한 보낼 문장. 없으면 원문을 그대로 보낸다
    body: str | None = None
    member_ids: list[PositiveId] = Field(min_length=1, max_length=MAX_TARGETS)

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)

    @model_validator(mode="after")
    def _unique_targets(self) -> "TodayTaskCreate":
        self.member_ids = list(dict.fromkeys(self.member_ids))
        return self


class PolishRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _clean(value)


class DoneRequest(BaseModel):
    done: bool


class SeenRequest(BaseModel):
    task_ids: list[PositiveId] = Field(min_length=1, max_length=50)
