"""v2 오류 봉투 (§5.4).

**오류는 action 이 아니다.** 다섯 action 에 `ERROR` 를 끼워 넣으면 "모르는 것" 과
"고장난 것" 이 같은 집계에 들어가고, 장애가 지식 부족으로 보고돼 점주에게
쓸데없는 알림이 간다 (불변식 5).

재시도 가능 여부를 **부르는 쪽이 정하지 못하게** 표로 고정한다. 의미가 틀린
요청을 retryable 로 표시하면 클라이언트가 같은 요청을 영원히 되보낸다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import Contract

ErrorCode = Literal[
    "INVALID_CONTRACT",
    "UNSUPPORTED_SCHEMA",
    "INVALID_REFERENCE",
    "STALE_DRAFT",
    "STALE_PUBLICATION",
    "STALE_KNOWLEDGE",
    "HASH_MISMATCH",
    "INDEX_PREPARE_FAILED",
    "INDEX_PREPARE_TIMEOUT",
    "CONTEXT_EXPIRED",
    "IDEMPOTENCY_CONFLICT",
    "RATE_LIMITED",
    "MODEL_UNAVAILABLE",
    "STORAGE_FAILED",
]

# code → (HTTP 상태, 자동 재시도 가능)
ERROR_TABLE: dict[str, tuple[int, bool]] = {
    "INVALID_CONTRACT": (422, False),
    "UNSUPPORTED_SCHEMA": (422, False),
    "INVALID_REFERENCE": (422, False),
    # 예상 revision 이 어긋난 것이다. 현재 상태를 다시 읽고 보내면 된다
    "STALE_DRAFT": (409, True),
    "STALE_PUBLICATION": (409, True),
    "STALE_KNOWLEDGE": (409, True),
    # 내용과 hash 가 다르다. 같은 요청을 되보내도 같은 결과다
    "HASH_MISMATCH": (409, False),
    "INDEX_PREPARE_FAILED": (503, False),
    "INDEX_PREPARE_TIMEOUT": (504, True),
    # 만료된 문맥은 되살릴 수 없다. 원문 재질문으로 안내한다
    "CONTEXT_EXPIRED": (410, False),
    # 같은 키에 다른 본문이다. 되보내면 또 충돌한다
    "IDEMPOTENCY_CONFLICT": (409, False),
    "RATE_LIMITED": (429, True),
    "MODEL_UNAVAILABLE": (503, True),
    "STORAGE_FAILED": (503, True),
}

CONTRACT_VERSION = "v2"


class ErrorDetail(Contract):
    code: ErrorCode
    # 사용자에게 보일 문장. 타 매장 ID·내부 SQL·모델 원문을 담지 않는다 (§5.4)
    message: str = Field(min_length=1, max_length=300)
    retryable: bool
    request_id: str = Field(min_length=1, max_length=80)
    operation_id: str | None = Field(default=None, max_length=80)
    retry_after_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _matches_table(self) -> "ErrorDetail":
        expected = ERROR_TABLE[self.code][1]
        if self.retryable != expected:
            raise ValueError(
                f"{self.code} 의 재시도 가능 여부는 {expected} 로 고정이다. "
                "부르는 쪽이 바꾸지 않는다")
        if self.code == "RATE_LIMITED" and self.retry_after_ms is None:
            raise ValueError("RATE_LIMITED 는 언제 다시 오라는지 알려줘야 한다")
        if self.retry_after_ms is not None and not self.retryable:
            raise ValueError("재시도할 수 없는 오류에 재시도 시각을 주지 않는다")
        return self


class ErrorEnvelope(Contract):
    contract_version: Literal["v2"] = CONTRACT_VERSION
    error: ErrorDetail

    @property
    def http_status(self) -> int:
        return ERROR_TABLE[self.error.code][0]


def error(code: str, message: str, *, request_id: str, **kw) -> ErrorEnvelope:
    """표가 정한 retryable 로 봉투를 만든다. 호출부가 고르지 않는다."""
    return ErrorEnvelope(error=ErrorDetail(
        code=code, message=message, request_id=request_id,
        retryable=ERROR_TABLE[code][1], **kw))
