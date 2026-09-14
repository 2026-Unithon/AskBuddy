"""추출 계약 — 모델이 자료에서 뽑아 보내는 것 (MVP 31-2).

원칙 셋:
  1. **카드 요약이 아니라 `original_assertion` 을 보존한다.** 요약하면 조건·예외가 날아간다.
  2. **없는 속성은 만들어 채우지 않는다.** null 은 '미확정' 이다.
  3. **모델은 ID 를 발급하지 못한다.** `local_ref` 는 출력 안의 참조일 뿐이고,
     schema 검증을 통과한 뒤 서버가 DB ID 를 준다 (MVP 31-2).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import (
    SCHEMA_EXTRACTION,
    Contract,
    Polarity,
    Quantity,
    Variant,
)

LocatorType = Literal["PAGE", "TIMESTAMP", "LINE", "BBOX", "WHOLE_SOURCE"]


class EvidenceLocator(Contract):
    """이 사실이 자료의 어디에서 나왔는가.

    자료 유형에 맞는 값을 요구한다 — 영상·음성은 시각, 문서는 페이지.
    위치가 없으면 나중에 "정말 그래요?" 에 답할 수 없고 영상 구간도 못 띄운다.
    """

    type: LocatorType = "WHOLE_SOURCE"
    page: int | None = Field(default=None, ge=1)
    timestamp_sec: int | None = Field(default=None, ge=0)
    line: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)

    @model_validator(mode="after")
    def _require_matching_field(self) -> "EvidenceLocator":
        need = {"PAGE": self.page, "TIMESTAMP": self.timestamp_sec,
                "LINE": self.line, "BBOX": self.bbox}
        if self.type in need and need[self.type] is None:
            raise ValueError(f"{self.type} locator 에는 그에 맞는 값이 필요하다")
        return self


class Assertion(Contract):
    """사실 하나. 원문이 권위 기준이고 typed 속성은 그 위의 해석이다.

    typed projection 이 원문과 다르면 검수 전에 공개하지 않는다 (MVP 31-3).
    """

    # 모델 출력 안에서만 유효한 참조. DB ID 가 아니다
    local_ref: str = Field(min_length=1, max_length=40)
    original_assertion: str = Field(min_length=1, max_length=2000)
    evidence: EvidenceLocator = EvidenceLocator()

    # ── 아래는 전부 선택이다. 모르면 null 이고, 지어내지 않는다 ──
    subject: str | None = Field(default=None, max_length=200)
    predicate: str | None = Field(default=None, max_length=100)
    variant: Variant | None = None
    quantity: Quantity | None = None
    value_text: str | None = Field(default=None, max_length=500)
    polarity: Polarity = "AFFIRM"
    conditions: list[str] = Field(default_factory=list, max_length=10)
    exceptions: list[str] = Field(default_factory=list, max_length=10)
    order: int | None = Field(default=None, ge=1)
    # 이 사실을 지키려면 먼저 지켜야 하는 다른 사실들의 local_ref
    requires: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _value_shape(self) -> "Assertion":
        if self.quantity and self.value_text:
            raise ValueError("수치와 서술값을 동시에 두지 않는다. 하나만 쓴다")
        return self


class ExtractionEnvelope(Contract):
    """구간 하나의 추출 결과.

    부분 성공·유효한 빈 결과·실패를 구분한다 (MVP 31-2).
    빈 JSON 을 성공으로 만들지 않는다 — `assertions` 가 비었어도 `unresolved` 에
    왜 비었는지 남아야 한다.
    """

    schema_version: Literal["extraction/v1"] = SCHEMA_EXTRACTION
    source_id: str
    segment_id: str | None = None
    attempt_id: str | None = None
    assertions: list[Assertion] = Field(default_factory=list)
    # 사실로 만들지 못한 것. 확인이 필요한 것은 여기 남긴다
    unresolved: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _unique_local_refs(self) -> "ExtractionEnvelope":
        refs = [a.local_ref for a in self.assertions]
        if len(refs) != len(set(refs)):
            raise ValueError("local_ref 가 중복됐다. 구간 안에서 유일해야 한다")
        known = set(refs)
        for a in self.assertions:
            missing = [r for r in a.requires if r not in known]
            if missing:
                raise ValueError(
                    f"{a.local_ref} 의 requires 가 이 구간에 없는 것을 가리킨다: {missing}")
        return self
