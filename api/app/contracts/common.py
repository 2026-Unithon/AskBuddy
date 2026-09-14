"""C0-1 공통 계약 — W(쓰기)와 R(읽기)이 같은 타입을 쓴다.

여기 있는 것이 두 파이프라인의 유일한 접점이다. 한쪽만 고치면 계약이 깨지므로
변경은 양쪽 검토를 거친다 (TODO C0-5).

ID 규칙 — DB 는 bigint 인데 JSON 은 decimal string 이다.
  JavaScript 의 Number 는 2^53 을 넘으면 정밀도를 잃는다. bigint ID 를 숫자로 내보내면
  프론트에서 조용히 틀린 ID 가 된다. 그래서 경계에서 문자열로 넘긴다 (MVP 31-4).
"""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DIGITS = re.compile(r"^[0-9]+$")

# 서버가 발급한 DB ID. 문자열이지만 숫자만 담는다
EntityId = Annotated[str, Field(pattern=r"^[0-9]+$", max_length=20)]

SCHEMA_EXTRACTION = "extraction/v1"
SCHEMA_CARD_PLAN = "card_plan/v1"
SCHEMA_PUBLISHED = "published_knowledge/v1"
SCHEMA_ANSWER_PLAN = "answer_plan/v1"


class Contract(BaseModel):
    """계약 모델의 공통 설정.

    extra="forbid" 가 핵심이다. 모델이 스키마에 없는 필드를 만들어 보내면
    조용히 무시되는 대신 검증에서 걸린다 — 계약 위반을 런타임까지 끌고 가지 않는다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def as_id(value: int | str) -> str:
    """DB bigint 를 계약용 ID 문자열로 바꾼다."""
    text = str(value)
    if not _DIGITS.match(text):
        raise ValueError(f"ID 는 숫자만 담는다: {value!r}")
    return text


# ── 사실의 typed 속성 ──────────────────────────────────────────────────────
# 없는 속성은 null 이고 '미확정' 이라는 뜻이다. 생성해서 채우지 않는다 (MVP 31-2).

Polarity = Literal["AFFIRM", "NEGATE"]
"""AFFIRM 은 '한다', NEGATE 는 '하지 않는다'. 부정을 값으로 뭉개면 금지 사항이 사라진다."""


class Variant(Contract):
    """규격. 같은 이름이라도 값이 다른 축이다.

    `null` 은 **모든 규격에 통용된다는 뜻이 아니라 미확정이다** (MVP 31-2).
    여러 규격이 가능하면 보류하거나 되묻는다.

    카드는 규격을 한 장에 담되 값은 규격별로 나란히 둔다 (D19).
    사실은 여기서 갈라 저장한다 — 카드는 표시 단위이고 사실이 값의 단위다.
    """

    temperature: Literal["HOT", "ICE"] | None = None
    size: str | None = None

    def is_unspecified(self) -> bool:
        return self.temperature is None and self.size is None


class Quantity(Contract):
    """수치는 decimal string 과 unit 을 함께 보존한다 (MVP 31-2).

    float 로 담으면 275 가 274.99999 가 되고, 단위를 버리면 275ml 와 275g 이 같아진다.
    단위 변환은 명시된 규칙·원래 값·반올림 이력을 갖고 따로 한다.
    """

    value: str = Field(min_length=1, max_length=40)
    unit: str | None = Field(default=None, max_length=20)

    @field_validator("value")
    @classmethod
    def _numeric_like(cls, v: str) -> str:
        if not re.match(r"^-?[0-9]+(\.[0-9]+)?$", v):
            raise ValueError(f"수치는 숫자 문자열이어야 한다: {v!r}")
        return v
