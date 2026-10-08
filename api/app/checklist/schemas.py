"""체크리스트 요청 본문. store_id 는 받지 않는다 (JWT 만)."""
from __future__ import annotations

from datetime import date, time
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

BIGINT_MAX = 9223372036854775807
# DB bigint 범위를 넘는 id 는 쿼리 전에 422 로 거른다
PositiveId = Annotated[int, Field(ge=1, le=BIGINT_MAX)]


def _naive(value: time | None) -> time | None:
    """시각은 매장 현지 시각이다. 시간대가 붙은 값은 받지 않는다."""
    if value is not None and value.tzinfo is not None:
        raise ValueError("시각에 시간대를 넣지 마세요")
    return value


def _check_times(starts_at: time | None, ends_at: time | None) -> None:
    if (starts_at is None) != (ends_at is None):
        raise ValueError("시작·끝 시각은 함께 적어 주세요")
    if starts_at is not None and starts_at == ends_at:
        raise ValueError("시작과 끝이 같을 수 없어요")


class ShiftCreate(BaseModel):
    name: str = Field(max_length=30)
    starts_at: time | None = None
    ends_at: time | None = None

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("근무조 이름을 적어 주세요")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _aware(cls, value: time | None) -> time | None:
        return _naive(value)

    @model_validator(mode="after")
    def _both_times(self):
        _check_times(self.starts_at, self.ends_at)
        return self


class ShiftUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    starts_at: time | None = None
    ends_at: time | None = None
    clear_time: bool = False   # 시간을 지우려면 true

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("근무조 이름을 적어 주세요")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _aware(cls, value: time | None) -> time | None:
        return _naive(value)

    @model_validator(mode="after")
    def _both_times(self):
        _check_times(self.starts_at, self.ends_at)
        if self.clear_time and self.starts_at is not None:
            raise ValueError("시간을 지우면서 시각을 함께 보낼 수 없어요")
        return self


class ShiftOrder(BaseModel):
    shift_ids: list[PositiveId] = Field(min_length=1, max_length=50)


class IdList(BaseModel):
    ids: list[PositiveId] = Field(default_factory=list, max_length=500)


class CardLinks(BaseModel):
    checklist: bool
    shift_ids: list[PositiveId] = Field(default_factory=list, max_length=50)   # [] = 공통


class Settings(BaseModel):
    business_day_starts_at: time | None = None
    staff_records_visible: bool | None = None

    @field_validator("business_day_starts_at")
    @classmethod
    def _aware(cls, value: time | None) -> time | None:
        return _naive(value)


class MySettings(BaseModel):
    personal_records_enabled: bool


class CheckItem(BaseModel):
    card_version_id: PositiveId
    line_no: int = Field(ge=1)
    checked: bool


class CheckRequest(CheckItem):
    business_date: date


class SubmissionRequest(BaseModel):
    business_date: date
    checks: list[CheckItem] = Field(default_factory=list, max_length=1000)
