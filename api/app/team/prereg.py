"""R 유료 캠페인 사전등록 — 실행 **전에** 고정하고, 실행 **후에** 대조한다.

D17·D18 과 실험설계 §9-3 은 "실험 전에 정답·채점기·snapshot 버전·분모·반복 수·
실패 처리·대표 개선량을 고정한다" 를 요구한다. `v2_campaign.compare_campaign` 은
`registration_ref` 문자열을 받지만 **그 문자열이 진짜 사전등록인지 확인하지
않는다**(그 모듈 주석 그대로). 이 파일이 그 빈칸을 메운다.

쓰는 순서는 하나다.

    ① 유료 실행 전: build_registration(...) → 파일로 저장(hash 가 registration_ref)
    ② 호출 직전마다: authorize_live_call(reg, now=…, spent_usd=…) → 예산·기간 확인
    ③ 실행 후: check_campaign(report, reg) → 분모·반복·채점기·개선량 대조

사전등록은 **승격 근거가 아니다.** 등록대로 돌았는지만 증명한다. 품질 판정은
`paired_gate`·`compare_campaign` 이, 사람 truth 는 사람이 한다.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from app.contracts.common import Contract, EntityId, RevisionId
from app.contracts.hashing import digest

SCHEMA_VERSION = "r_campaign_registration/v1"

_HASH = r"^sha256:[0-9a-f]{64}$"
_MONEY = r"^(0|[1-9][0-9]{0,9})(\.[0-9]{1,6})?$"

# D17: A/B 각 최소 3회와 A/A 대조. 3회는 통계 보장이 아니라 하한이다.
# 이 하한은 **승격을 다투는 캠페인**에만 적용된다 (run_kind='CAMPAIGN').
MIN_REPEATS = 3
MIN_CONTROLS = 3


class PreregViolation(ValueError):
    """사전등록과 어긋난 실행. 결과를 품질 근거로 쓰지 않는다."""


class BudgetDeniedByPrereg(PreregViolation):
    """예산 상한·승인 기간을 벗어난 유료 호출. 호출 **전에** 막는다."""


class BudgetApproval(Contract):
    """사용자가 승인한 이번 캠페인의 예산. 과거 승인을 재사용하지 않는다.

    금액은 hash 안정성 때문에 decimal **문자열**이다(float 반올림 금지).
    원화 상한·환율은 모르면 `None` 으로 남긴다 — 0 으로 채우지 않는다(D21 UNKNOWN).
    """

    usd_cap: str = Field(pattern=_MONEY)
    krw_cap: str | None = Field(default=None, pattern=_MONEY)
    fx_krw_per_usd: str | None = Field(default=None, pattern=_MONEY)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    approval_ref: str = Field(min_length=1, max_length=500)

    @field_validator("approved_at")
    @classmethod
    def tz_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("승인 시각은 타임존이 있어야 한다")
        return value

    @model_validator(mode="after")
    def positive_cap(self):
        if Decimal(self.usd_cap) <= 0:
            raise ValueError("예산 상한은 0보다 커야 한다")
        if (self.krw_cap is None) != (self.fx_krw_per_usd is None):
            # 환율 없이 원화 상한만 적으면 두 상한이 서로를 검증하지 못한다
            raise ValueError("원화 상한과 환율은 함께 적거나 함께 비운다")
        return self

    def usd_limit(self) -> Decimal:
        return Decimal(self.usd_cap)


class FailurePolicy(Contract):
    """실패를 무엇으로 셀지 미리 정한다 (D17 "실패 처리").

    제품이 확정적으로 실패한 것은 False(실패), 평가자·환경 장애로 정답 여부를
    모르는 것은 None(미판정)이다. 이 구분을 실행 뒤에 바꾸면 분모가 흔들린다.
    """

    product_error: Literal["FALSE"] = "FALSE"
    evaluator_error: Literal["UNJUDGED"] = "UNJUDGED"
    timeout_as: Literal["FALSE", "UNJUDGED"]
    per_call_timeout_seconds: int = Field(ge=1, le=120)
    retry_limit: int = Field(ge=0, le=3)
    partial_run: Literal["DISCARD_RUN", "KEEP_AS_UNJUDGED"]


class CampaignRegistration(Contract):
    """유료 실행 전에 못 박는 전부. 한 글자 바뀌면 hash 가 달라진다."""

    schema_version: Literal["r_campaign_registration/v1"] = SCHEMA_VERSION
    registered_at: datetime
    registered_by: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=1000)

    # 정답·채점기·snapshot 버전
    manifest_hash: str = Field(pattern=_HASH)
    truth_kind: Literal["SYNTHETIC", "HUMAN_REVIEWED"]
    truth_version: str = Field(min_length=1, max_length=200)
    snapshot_id: EntityId
    knowledge_revision: RevisionId
    snapshot_hash: str = Field(pattern=_HASH)
    evaluator_hashes: dict[str, str] = Field(min_length=1)
    source_manifest_hash: str = Field(pattern=_HASH)

    # 분모
    question_ids: tuple[str, ...] = Field(min_length=1)
    must_have_ids: tuple[str, ...] = ()

    # 실행 종류 — 반복 하한과 채점 가능 여부를 가른다
    #   CAMPAIGN   승격을 다투는 A/B 캠페인. D17 의 3회·대조 3회 하한을 지킨다
    #   DIAGNOSTIC 소수 질문으로 배선·품질을 들여다보는 실행. 점수를 내지 않는다
    run_kind: Literal["CAMPAIGN", "DIAGNOSTIC"] = "CAMPAIGN"

    # 반복과 판정 기준
    repeat_count: int = Field(ge=1)
    control_count: int = Field(ge=0)
    min_median_delta: int | None = Field(default=None, ge=1)
    cost_neutral: StrictBool

    # 실행 조건
    provider_mode: Literal["SYNTHETIC", "LIVE"]
    model_ids: tuple[str, ...] = Field(min_length=1)
    failure_policy: FailurePolicy
    budget: BudgetApproval | None = None

    @field_validator("registered_at")
    @classmethod
    def tz_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("등록 시각은 타임존이 있어야 한다")
        return value

    @field_validator("evaluator_hashes")
    @classmethod
    def hashes_well_formed(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        for name, item in value.items():
            if not name.strip() or not re.match(_HASH, item):
                raise ValueError(f"채점기 hash 형식이 아니다: {name}")
        return value

    @model_validator(mode="after")
    def consistent(self):
        ids = set(self.question_ids)
        if len(ids) != len(self.question_ids) or any(not q.strip() for q in self.question_ids):
            raise ValueError("질문 분모에 중복·빈 ID 가 있다")
        required = set(self.must_have_ids)
        if len(required) != len(self.must_have_ids):
            raise ValueError("필수 질문 ID 중복")
        if not required <= ids:
            raise ValueError("분모 밖의 필수 질문 ID")
        if self.run_kind == "CAMPAIGN":
            if self.repeat_count < MIN_REPEATS or self.control_count < MIN_CONTROLS:
                raise ValueError(
                    f"캠페인은 반복 {MIN_REPEATS}회·대조 {MIN_CONTROLS}회가 하한이다 (D17)")
            if self.min_median_delta is None:
                raise ValueError("캠페인은 대표 개선량 최소치를 미리 고정한다 (D18)")
        elif self.min_median_delta is not None:
            # 진단은 개선량을 다투지 않는다. 숫자를 적어 두면 나중에 점수처럼 읽힌다
            raise ValueError("진단 실행에는 대표 개선량을 적지 않는다")
        if self.provider_mode == "LIVE" and self.budget is None:
            # 승인 없이 유료 실행을 등록할 수 없다 (로드맵 §0-6)
            raise ValueError("유료 실행은 예산 승인이 필요하다")
        if self.budget is not None and self.budget.approved_at > self.registered_at:
            raise ValueError("예산 승인은 등록보다 늦을 수 없다")
        return self


def registration_hash(registration: CampaignRegistration) -> str:
    """`compare_campaign` 의 `registration_ref` 에 넣을 값."""
    return digest(registration.model_dump(mode="json"))


def build_registration(**fields) -> tuple[CampaignRegistration, str]:
    registration = CampaignRegistration(**fields)
    return registration, registration_hash(registration)


def authorize_live_call(
    registration: CampaignRegistration,
    *,
    now: datetime,
    spent_usd: str | Decimal,
    pending_usd: str | Decimal = "0",
) -> None:
    """유료 호출 **직전**에 부른다. 상한에 닿으면 호출하지 않고 멈춘다.

    이미 받은 응답을 버리지 않는 대신 다음 호출을 막는다
    (`app/ingest/providers/budget.py` 와 같은 규칙).
    """
    if registration.provider_mode != "LIVE":
        raise PreregViolation("합성으로 등록된 캠페인에서 유료 호출을 할 수 없다")
    budget = registration.budget
    if budget is None:  # pragma: no cover - 모델 검증이 먼저 막는다
        raise BudgetDeniedByPrereg("예산 승인이 없다")
    if now.tzinfo is None:
        raise PreregViolation("현재 시각은 타임존이 있어야 한다")
    if now < registration.registered_at:
        raise PreregViolation("등록 시각보다 이른 실행은 사전등록이 아니다")
    try:
        used = Decimal(str(spent_usd)) + Decimal(str(pending_usd))
    except InvalidOperation as exc:
        raise PreregViolation(f"사용액을 읽을 수 없다: {spent_usd!r}") from exc
    if used < 0:
        raise PreregViolation("사용액은 음수가 될 수 없다")
    if used >= budget.usd_limit():
        raise BudgetDeniedByPrereg(
            f"예산 상한 {budget.usd_cap} USD 도달 (누적 {used})")


def verify_live_plan(
    registration: CampaignRegistration,
    *,
    challenge_hash: str,
    source_manifest_hash: str,
    model: str,
    turn_ids: list[str] | tuple[str, ...],
    max_krw: str | int | None = None,
) -> None:
    """유료 실행을 **시작하기 전에** 등록과 실제 입력이 같은지 확인한다.

    여기서 막는 것은 "등록은 해 두고 다른 입력으로 돌리기" 다. 예산 집행 자체는
    `app/team/evaluation_budget.py` 의 DB 예약이 맡는다 — 이 함수는 등록한 상한을
    넘는 계획을 들고 오는 것을 거절한다.
    """
    if registration.provider_mode != "LIVE":
        raise PreregViolation("합성으로 등록된 캠페인으로 유료 실행을 시작할 수 없다")
    if registration.manifest_hash != _with_hash_prefix(challenge_hash):
        raise PreregViolation("등록한 정답·질문 세트가 아니다")
    if registration.source_manifest_hash != _with_hash_prefix(source_manifest_hash):
        raise PreregViolation("등록 당시 코드가 아니다(source manifest 불일치)")
    if model not in registration.model_ids:
        raise PreregViolation(f"등록하지 않은 모델: {model}")
    if tuple(turn_ids) != registration.question_ids:
        raise PreregViolation("질문 분모가 등록과 다르다(순서·개수 포함)")
    budget = registration.budget
    if budget is None:  # pragma: no cover - 모델 검증이 먼저 막는다
        raise BudgetDeniedByPrereg("예산 승인이 없다")
    if max_krw is not None:
        if budget.krw_cap is None:
            raise PreregViolation("원화 상한을 등록하지 않았는데 계획이 원화 상한을 쓴다")
        if Decimal(str(max_krw)) > Decimal(budget.krw_cap):
            raise BudgetDeniedByPrereg(
                f"계획의 원화 상한 {max_krw} 이 등록한 {budget.krw_cap} 을 넘는다")


def _with_hash_prefix(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def check_campaign(report: dict, registration: CampaignRegistration) -> list[str]:
    """실행 결과가 등록대로인지 대조한다. 어긋난 것을 **전부** 돌려준다.

    빈 목록이면 "등록대로 돌았다" 는 뜻이고, 품질 통과나 승격이 아니다.
    여기서 예외를 던지지 않는 이유는 어긋난 항목을 기록에 남겨야 하기 때문이다.
    """
    problems: list[str] = []
    if registration.run_kind != "CAMPAIGN":
        # 진단 실행의 출력을 캠페인 점수로 바꿔 읽지 않는다
        return ["DIAGNOSTIC_NOT_A_CAMPAIGN"]
    expected_ref = registration_hash(registration)
    plan = report.get("plan") or {}

    if plan.get("registration_ref") != expected_ref:
        problems.append("REGISTRATION_REF_MISMATCH")
    if plan.get("manifest_hash") != registration.manifest_hash:
        problems.append("MANIFEST_MISMATCH")
    if plan.get("repeat_count") != registration.repeat_count:
        problems.append("REPEAT_COUNT_CHANGED")
    if plan.get("control_count") != registration.control_count:
        problems.append("CONTROL_COUNT_CHANGED")
    if plan.get("cost_neutral") != registration.cost_neutral:
        problems.append("COST_NEUTRALITY_CHANGED")

    if (report.get("evaluator_hashes") or {}) != registration.evaluator_hashes:
        # 채점기가 실행 뒤에 바뀌면 같은 입력의 점수가 달라진다
        problems.append("EVALUATOR_CHANGED")

    gate = report.get("gate") or {}
    if gate.get("question_count") != len(registration.question_ids):
        problems.append("DENOMINATOR_CHANGED")

    gate_required = gate.get("must_have_ids")
    if gate_required is None:
        problems.append("MUST_HAVE_MANIFEST_MISSING")
    elif not set(gate_required) <= set(registration.must_have_ids):
        # 등록한 적 없는 질문이 필수로 올라오면 사후에 분모를 고른 것이다
        problems.append("MUST_HAVE_NOT_REGISTERED")

    median_delta = gate.get("median_delta")
    if median_delta is None:
        problems.append("REPRESENTATIVE_DELTA_UNJUDGED")
    elif median_delta < registration.min_median_delta:
        problems.append("BELOW_REGISTERED_MIN_DELTA")

    return problems


def campaign_passes_prereg(report: dict, registration: CampaignRegistration) -> bool:
    """등록 대조와 산술 게이트를 **둘 다** 통과했는가. 승격 결정은 아니다."""
    return not check_campaign(report, registration) and bool(
        (report.get("gate") or {}).get("eligible"))
