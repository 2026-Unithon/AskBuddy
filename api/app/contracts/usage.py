"""원가 계측 계약 (CP-00A) — 유료 호출 한 건이 남기는 것.

왜 필요한가: D21(매장당 월 3,000원)은 **잴 수 없으면 집행할 수 없는 약속**이다.
지금 읽기 경로만 토큰을 남기고 추출·STT·임베딩·Storage 는 전혀 안 잰다.
등록 원가의 대부분이 그쪽인데 보이지 않는다.

핵심 규칙 셋:
  1. **결측과 0 을 구분한다.** 무상 항목만 0 이고 못 잰 것은 null 이다.
     0 으로 채우면 합계가 사실보다 싸 보이고, 그 수치로 D21 통과를 선언하게 된다.
  2. **호출 1회 = receipt 1행.** 한 호출이 여러 자료를 조립해도 receipt 는 하나다.
     배치를 자료 수만큼 세면 원가가 부풀려진다.
  3. **계측 실패로 유료 호출을 반복하지 않는다.** 시작 receipt 저장이 실패하면
     호출하지 않고 멈춘다. 응답 후 저장이 실패하면 DB 저장만 재시도한다.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import Contract, EntityId

# 어느 단계에서 쓴 돈인가. 등록은 1회성이고 운영은 매월이라 섞으면 D21 을 판정할 수 없다
CostPhase = Literal["REGISTRATION", "OPERATING"]

# 제품 운영비인가, 우리가 개발·평가하느라 쓴 것인가.
# 평가 호출을 고객 월 비용에 합산하면 D21 이 거짓으로 실패한다
CostPurpose = Literal["PRODUCT", "EVALUATION", "DEVELOPMENT"]

UsageStage = Literal[
    "STT", "EXTRACT", "ASSEMBLE", "CLASSIFY", "RELATION",
    "EMBED", "QUERY", "RERANK", "ANSWER", "VALIDATE",
]

AttemptStatus = Literal["STARTED", "SUCCEEDED", "FAILED", "UNKNOWN"]

# COMPLETE   공급자가 보고한 과금 단위를 전부 받았다
# PARTIAL    일부만 받았다. known_cost 로만 더한다
# UNKNOWN    못 받았다. 총액을 null 로 둔다
# NOT_BILLABLE 과금 대상이 아니다 (mock 실행 등). 0 이 사실이다
UsageStatus = Literal["COMPLETE", "PARTIAL", "UNKNOWN", "NOT_BILLABLE"]

PriceStatus = Literal["PRICED", "NO_RATE", "UNKNOWN_UNITS"]


class UsageContext(Contract):
    """호출을 어느 매장·어느 단계·무슨 목적에 귀속시킬 것인가.

    호출부에 명시 인자로 넘긴다. 전역 상태에서 읽으면 병렬 작업에서 뒤섞인다.
    `store_id` 는 필수다 — 매장 귀속 없는 비용은 D21 계산에 쓸 수 없다 (D1 과 같은 취지).
    """

    store_id: EntityId
    cost_phase: CostPhase
    cost_purpose: CostPurpose = "PRODUCT"
    stage: UsageStage

    # 같은 논리 호출의 재시도를 하나로 묶는다. 재시도를 새 호출로 세면 원가가 부풀려진다
    logical_call_id: str = Field(min_length=1, max_length=80)
    attempt_no: int = Field(default=1, ge=1)

    # 등록 캠페인 하나를 복구 재시도까지 묶는다
    registration_campaign_id: str | None = Field(default=None, max_length=80)
    operation_id: str | None = Field(default=None, max_length=80)

    job_id: EntityId | None = None
    source_id: EntityId | None = None
    segment_id: str | None = Field(default=None, max_length=80)
    question_id: EntityId | None = None
    extraction_run_id: EntityId | None = None
    evaluation_run_id: EntityId | None = None


class ModelUsage(Contract):
    """공급자가 보고한 과금 단위. **못 받은 값은 null 이다.**

    `raw` 에 공급자 응답을 그대로 남긴다. 나중에 새 과금 항목이 생겨도
    과거 호출을 다시 해석할 수 있다.
    """

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    thought_tokens: int | None = Field(default=None, ge=0)
    # 토큰이 아닌 과금 단위 (STT 의 분, 이미지 장수 등)
    billable_units: Decimal | None = None
    billable_unit_name: str | None = Field(default=None, max_length=40)
    raw: dict | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in (
            self.prompt_tokens, self.completion_tokens,
            self.cached_tokens, self.thought_tokens, self.billable_units))


class InputScale(Contract):
    """입력 규모. 토큰을 못 받아도 이것으로 사후 추정할 수 있다."""

    input_bytes: int | None = Field(default=None, ge=0)
    media_duration_sec: float | None = Field(default=None, ge=0)
    page_count: int | None = Field(default=None, ge=0)
    frame_count: int | None = Field(default=None, ge=0)


class UsageAttempt(Contract):
    """유료 호출 한 번의 원장 한 행. 확정 후에는 불변이다.

    늦은 공급자 정산과 요율 재계산은 이 행을 고치지 않고 별도 append 로 남긴다 —
    과거 보고서를 조용히 바꾸면 무엇을 보고 판단했는지 되짚을 수 없다.
    """

    context: UsageContext
    status: AttemptStatus = "STARTED"
    requested_model: str = Field(max_length=100)
    reported_model: str | None = Field(default=None, max_length=100)
    provider_request_id: str | None = Field(default=None, max_length=200)
    # real 인가 mock 인가. mock 실행을 원가로 집계하지 않는다 (D10)
    mode: Literal["real", "mock"] = "real"
    prompt_hash: str | None = Field(default=None, max_length=80)
    config_hash: str | None = Field(default=None, max_length=80)
    rate_card_version: str | None = Field(default=None, max_length=40)

    started_at: datetime | None = None
    finished_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=80)
    cache_state: str | None = Field(default=None, max_length=40)

    usage: ModelUsage = ModelUsage()
    scale: InputScale = InputScale()
    usage_status: UsageStatus = "UNKNOWN"
    missing_reason: str | None = Field(default=None, max_length=200)

    # 요율을 곱한 결과. 요율이 없으면 null 이고 토큰은 그대로 남는다
    currency: str = Field(default="USD", max_length=8)
    known_cost_usd: Decimal | None = None
    cost_usd: Decimal | None = None
    price_status: PriceStatus = "NO_RATE"

    @model_validator(mode="after")
    def _consistency(self) -> "UsageAttempt":
        if self.usage_status == "NOT_BILLABLE" and not self.usage.is_empty():
            raise ValueError("과금 대상이 아닌데 usage 가 있다. 둘 중 하나가 틀렸다")
        if self.usage_status == "COMPLETE" and self.usage.is_empty():
            raise ValueError("COMPLETE 인데 usage 가 비었다. UNKNOWN 이어야 한다")
        if self.usage_status in ("PARTIAL", "UNKNOWN") and self.cost_usd is not None:
            raise ValueError(
                "관측이 불완전하면 총액(cost_usd)을 내지 않는다. known_cost_usd 만 쓴다")
        if self.status == "SUCCEEDED" and self.finished_at is None:
            raise ValueError("SUCCEEDED 에는 finished_at 이 필요하다")
        return self
