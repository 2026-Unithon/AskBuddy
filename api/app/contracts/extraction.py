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
    FrozenContract,
    EntityId,
    Polarity,
    Quantity,
    RawText,
    Variant,
)

LocatorType = Literal["PAGE", "TIMESTAMP", "LINE", "BBOX", "WHOLE_SOURCE"]

ExtractionStatus = Literal["OK", "NO_RESULT", "PARTIAL", "FAILED"]
"""
OK         뽑을 것을 다 뽑았다
NO_RESULT  볼 것은 다 봤는데 사실이 없었다 — **왜 없었는지가 있어야 한다**
PARTIAL    일부만 뽑았다. 잘림·미해소가 남아 있다
FAILED     못 읽었다. 사실이 없고 오류가 있다

이 넷을 구분하지 않으면 `assertions: []` 하나가 "자료에 내용이 없다" 와
"호출이 깨졌다" 를 같은 모양으로 만든다. 추출 손실(E-O0)을 재면 전자는 분모에서
정당하게 빠지고 후자는 우리 잘못인데, 섞이면 실패가 성능으로 집계된다.
"""


class EvidenceLocator(FrozenContract):
    """이 사실이 자료의 어디에서 나왔는가. 값 객체이므로 불변이다.

    자료 유형에 맞는 값을 요구한다 — 영상·음성은 시각, 문서는 페이지.
    위치가 없으면 나중에 "정말 그래요?" 에 답할 수 없고 영상 구간도 못 띄운다.
    """

    type: LocatorType = "WHOLE_SOURCE"
    page: int | None = Field(default=None, ge=1)
    timestamp_sec: int | None = Field(default=None, ge=0)
    line: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None

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
    # 원문은 공백까지 그대로 둔다 (RV-07). 들여쓰기가 순서를 나타내는 자료가 있다
    original_assertion: RawText = Field(min_length=1, max_length=2000)
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
        if self.local_ref in self.requires:
            raise ValueError(f"{self.local_ref} 가 자기 자신을 선행 조건으로 둔다")
        if len(set(self.requires)) != len(self.requires):
            raise ValueError(f"{self.local_ref} 의 requires 가 중복됐다")
        return self


class ExtractionEnvelope(Contract):
    """구간 하나의 추출 결과.

    부분 성공·유효한 빈 결과·실패를 구분한다 (MVP 31-2).
    빈 JSON 을 성공으로 만들지 않는다 — `assertions` 가 비었어도 `unresolved` 에
    왜 비었는지 남아야 한다.
    """

    schema_version: Literal["extraction/v1"] = SCHEMA_EXTRACTION
    # 서버가 요청에 묶어 넣는 값이다. 모델 출력의 값을 그대로 믿지 않는다 (RV-10)
    source_id: EntityId
    segment_id: str | None = Field(default=None, max_length=80)
    attempt_id: str | None = Field(default=None, max_length=80)
    result_status: ExtractionStatus
    assertions: list[Assertion] = Field(default_factory=list, max_length=500)
    # 사실로 만들지 못한 것. 확인이 필요한 것은 여기 남긴다
    unresolved: list[str] = Field(default_factory=list, max_length=100)
    # 출력 상한에 걸려 잘렸는가. 잘린 결과를 온전한 결과로 세지 않는다
    truncated: bool = False
    # FAILED·truncated 일 때 원문 응답을 어디 두었는가. 버리면 재현이 불가능하다
    raw_response_ref: str | None = Field(default=None, max_length=200)
    error: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _status_matches_payload(self) -> "ExtractionEnvelope":
        """상태와 내용이 어긋나면 거절한다.

        어긋난 채로 통과하면 지표가 조용히 틀린다 — 사실이 든 FAILED, 이유 없는
        NO_RESULT, 잘렸다면서 OK 인 봉투가 전부 같은 집계에 들어간다.
        """
        if self.result_status == "FAILED":
            if self.assertions:
                raise ValueError("FAILED 봉투에 사실을 담지 않는다")
            if not self.error:
                raise ValueError("FAILED 에는 오류 내용이 필요하다")
        elif self.error:
            raise ValueError(f"{self.result_status} 에 오류를 함께 두지 않는다")

        if self.result_status == "NO_RESULT":
            if self.assertions:
                raise ValueError("NO_RESULT 봉투에 사실을 담지 않는다")
            if not self.unresolved:
                raise ValueError(
                    "NO_RESULT 에는 왜 사실이 없었는지가 필요하다. "
                    "빈 결과를 이유 없이 성공으로 만들지 않는다")
        if self.result_status == "OK":
            if not self.assertions:
                raise ValueError("사실이 없으면 OK 가 아니라 NO_RESULT 다")
            if self.truncated:
                raise ValueError("잘린 결과는 OK 가 아니라 PARTIAL 이다")
        if (self.truncated or self.result_status == "FAILED") and not self.raw_response_ref:
            raise ValueError("잘림·실패는 원문 응답을 남겨야 한다 (RV-10)")
        return self

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
        cycle = _first_cycle({a.local_ref: a.requires for a in self.assertions})
        if cycle:
            raise ValueError(f"선행 조건이 순환한다: {' → '.join(cycle)}")
        return self


def _first_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """선행 관계의 순환을 하나 찾아 경로로 돌려준다.

    A 가 B 를 요구하고 B 가 A 를 요구하면 "먼저 할 것" 의 순서를 정할 수 없다.
    검증 없이 두면 나중에 절차를 펼치는 쪽이 무한히 돈다.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(edges, WHITE)
    path: list[str] = []

    def walk(node: str) -> list[str] | None:
        color[node] = GREY
        path.append(node)
        for nxt in edges.get(node, ()):
            if color.get(nxt) == GREY:
                return path[path.index(nxt):] + [nxt]
            if color.get(nxt) == WHITE:
                found = walk(nxt)
                if found:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for node in edges:
        if color[node] == WHITE:
            found = walk(node)
            if found:
                return found
    return None
