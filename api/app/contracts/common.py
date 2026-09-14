"""C0-1 공통 계약 — W(쓰기)와 R(읽기)이 같은 타입을 쓴다.

여기 있는 것이 두 파이프라인의 유일한 접점이다. 한쪽만 고치면 계약이 깨지므로
변경은 양쪽 검토를 거친다 (TODO C0-5).

ID 규칙 — DB 는 bigint 인데 JSON 은 decimal string 이다.
  JavaScript 의 Number 는 2^53 을 넘으면 정밀도를 잃는다. bigint ID 를 숫자로 내보내면
  프론트에서 조용히 틀린 ID 가 된다. 그래서 경계에서 문자열로 넘긴다 (MVP 31-4).

  문자열이므로 **정규형을 강제한다** (CP-01/RV-09). `"012"` 와 `"12"` 를 둘 다 받으면
  같은 행을 가리키는 두 문자열이 생기고, 계약 전체가 쓰는 set 기반 존재·중복 검사가
  조용히 뚫린다. 앞자리 0 을 거절하고 bigint 범위를 넘는 값도 거절한다.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

_DIGITS = re.compile(r"^[0-9]+$")

# PostgreSQL bigint 상한. 넘는 값은 DB 에 저장된 적이 없는 ID 다
MAX_BIGINT = 2**63 - 1


def _canonical_id(value: str) -> str:
    if len(value) > 1 and value[0] == "0":
        raise ValueError(f"ID 는 앞자리 0 을 두지 않는다 (같은 행의 두 표기가 생긴다): {value!r}")
    if int(value) > MAX_BIGINT:
        raise ValueError(f"ID 가 bigint 범위를 넘는다: {value!r}")
    return value


# 서버가 발급한 DB ID. 문자열이지만 숫자만 담고, 표기는 하나뿐이다
EntityId = Annotated[
    str,
    Field(pattern=r"^[0-9]+$", max_length=19),
    AfterValidator(_canonical_id),
]

# 매장 범위에서 단조 증가하는 판 번호. ID 와 같은 이유로 문자열이다 (RV-09)
RevisionId = EntityId

# 원문. **공백을 손대지 않는다** (RV-07).
# 계약 전체는 str_strip_whitespace 로 앞뒤 공백을 떼지만, 원문에 그걸 적용하면
# 들여쓰기·줄바꿈이 사라져 "원문이 권위 기준" 이라는 전제가 깨진다.
RawText = Annotated[str, StringConstraints(strip_whitespace=False)]

SCHEMA_EXTRACTION = "extraction/v1"
SCHEMA_CARD_PLAN = "card_plan/v1"
SCHEMA_PUBLISHED = "published_knowledge/v1"
SCHEMA_ANSWER_PLAN = "answer_plan/v1"

# SHA-256 16진 표기. 길이만 보면 임의 문자열이 통과한다 (RV-09)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _sha256_hex(value: str) -> str:
    if not _SHA256_HEX.match(value):
        raise ValueError("hash 는 소문자 16진 SHA-256 64자여야 한다")
    return value


Sha256Hex = Annotated[str, AfterValidator(_sha256_hex)]

# 표시용 hash. 알고리즘을 값에 담아 나중에 바꿀 때 옛 값과 섞이지 않게 한다 (§3.4)
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


def _hash_ref(value: str) -> str:
    if not _HASH_REF.match(value):
        raise ValueError("hash 는 `sha256:<64 소문자 16진>` 형식이어야 한다")
    return value


HashRef = Annotated[str, AfterValidator(_hash_ref)]


def _utc_aware(value: datetime) -> datetime:
    """naive datetime 을 거절한다.

    시각대 없는 시각은 서버·DB·프론트에서 각각 다르게 읽힌다. 승인 시점이
    9시간 밀리면 어느 판이 먼저인지 뒤집힌다.
    """
    if value.tzinfo is None:
        raise ValueError("시각은 시각대를 포함해야 한다 (TIMESTAMPTZ)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_utc_aware)]


class Contract(BaseModel):
    """계약 모델의 공통 설정.

    extra="forbid" 가 핵심이다. 모델이 스키마에 없는 필드를 만들어 보내면
    조용히 무시되는 대신 검증에서 걸린다 — 계약 위반을 런타임까지 끌고 가지 않는다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FrozenContract(Contract):
    """승인된 뒤에는 바꿀 수 없는 계약 (RV-07).

    `frozen=True` 는 필드 재대입을 막을 뿐이다. 리스트를 담으면 `.append()` 로
    내용이 바뀐다 — 승인 snapshot 을 파싱한 뒤 인용 목록을 늘릴 수 있다는 뜻이다.
    그래서 이 계약을 쓰는 모델은 컬렉션을 `tuple` 로 선언한다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


def as_id(value: int | str) -> str:
    """DB bigint 를 계약용 ID 문자열로 바꾼다."""
    text = str(value)
    if not _DIGITS.match(text):
        raise ValueError(f"ID 는 숫자만 담는다: {value!r}")
    return _canonical_id(text)


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

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    temperature: Literal["HOT", "ICE"] | None = None
    size: str | None = None

    def is_unspecified(self) -> bool:
        return self.temperature is None and self.size is None


class Quantity(Contract):
    """수치는 decimal string 과 unit 을 함께 보존한다 (MVP 31-2).

    float 로 담으면 275 가 274.99999 가 되고, 단위를 버리면 275ml 와 275g 이 같아진다.
    단위 변환은 명시된 규칙·원래 값·반올림 이력을 갖고 따로 한다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    value: str = Field(min_length=1, max_length=40)
    unit: str | None = Field(default=None, max_length=20)

    @field_validator("value")
    @classmethod
    def _numeric_like(cls, v: str) -> str:
        if not re.match(r"^-?[0-9]+(\.[0-9]+)?$", v):
            raise ValueError(f"수치는 숫자 문자열이어야 한다: {v!r}")
        return v
