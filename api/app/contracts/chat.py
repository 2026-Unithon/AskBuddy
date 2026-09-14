"""질문·답변 경계의 계약 (§5.1~5.4).

**모델이 제안하는 것과 서버가 확정한 것을 다른 타입으로 나눈다.**
`AnswerPlan` 은 모델의 선택 제안이다. 여기 있는 `ChatResponse` 는 서버가
승인 지식과 권한을 다시 확인하고 직접 렌더링해 내보내는 것이다. 하나로 두면
모델이 만든 문장이 검증을 건너뛰고 나갈 통로가 생긴다.

모델은 `context_id` 도 `snapshot_id` 도 새로 발급하지 못한다. 서버가 발급한
값만 쓴다 — 모델이 ID 를 지어낼 수 있으면 문맥 소유권 검사가 무의미해진다.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.answer import AnswerAction, AnswerPlan
from app.contracts.common import (
    Contract,
    EntityId,
    RevisionId,
    UtcDatetime,
)

# 정책 고정 문구 (§5.4). 모델이 안전·개인정보 판단을 생성하지 않는다
REFUSE_MESSAGE = (
    "개인정보에 관한 내용은 안내할 수 없어요. "
    "업무상 확인이 필요하면 사장님에게 직접 확인해 주세요.")
SAFE_ROUTE_MESSAGE = (
    "안전 여부는 여기서 판단할 수 없어요. "
    "현장의 안전 지침과 담당자의 확인을 따라 주세요.")
POLICY_MESSAGES: dict[str, str] = {
    "REFUSE": REFUSE_MESSAGE,
    "SAFE_ROUTE": SAFE_ROUTE_MESSAGE,
}
POLICY_VERSION = "policy/v1"

# 인용한 자료가 지금 열람 가능한가. **snapshot 이 아니라 조회 시점에 덧입힌다** (D20)
SourceAvailability = Literal["AVAILABLE", "DELETED", "UNAVAILABLE"]
BROKEN_CITATION_LABEL = "인용 끊김"
DELETED_SOURCE_NOTE = (
    "원본 자료가 삭제되었어요. 승인된 카드 내용은 확인할 수 있어요.")

# 점주 답변의 **지식화** 상태. 직원 전달 상태와 섞지 않는다 (§5.3)
KnowledgeState = Literal["PENDING", "LINKED", "REVIEW", "PUBLISHED", "FAILED"]


class QuestionContext(Contract):
    """되묻기를 이어가는 서버 문맥 (§5.1).

    `(store, member, session, contract_version)` 에 묶인다. 다른 대화로 복사되지
    않는다 — 복사되면 A 직원의 확정 슬롯으로 B 직원에게 답하게 된다.
    """

    # 서버가 발급한 UUID 다. 모델이 짐작할 수 있는 형식이면 문맥 소유권 검사가
    # 무의미해진다 (§5.1). AnswerPlan 과 같은 타입을 쓴다
    context_id: UUID
    store_id: EntityId
    member_id: EntityId
    chat_session_id: EntityId
    contract_version: str = Field(max_length=20)
    # 마지막으로 수락한 사용자 턴부터 10분
    expires_at: UtcDatetime
    # 사용자가 직접 고른 값과 모델이 짐작한 값을 갈라 둔다.
    # 섞으면 모델의 짐작이 다음 턴에 '확정' 으로 굳는다
    confirmed_slots: dict[str, str] = Field(default_factory=dict)
    proposed_slots: dict[str, str] = Field(default_factory=dict)
    original_question: str = Field(min_length=1, max_length=1000)
    clarify_turns: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def _slots_do_not_overlap(self) -> "QuestionContext":
        both = sorted(set(self.confirmed_slots) & set(self.proposed_slots))
        if both:
            raise ValueError(f"확정 슬롯과 짐작 슬롯에 같은 이름이 있다: {both}")
        return self


class Citation(Contract):
    """근거 칩 하나. 어느 카드 버전의 어느 블록인지까지 고정한다."""

    card_id: EntityId
    card_version_id: EntityId
    block_id: str = Field(min_length=1, max_length=40)
    fact_revision_id: EntityId | None = None
    raw_span_id: EntityId | None = None
    source_id: EntityId
    source_availability: SourceAvailability = "AVAILABLE"

    @model_validator(mode="after")
    def _points_at_something(self) -> "Citation":
        if bool(self.fact_revision_id) == bool(self.raw_span_id):
            raise ValueError("인용은 사실이나 원문 구간 중 정확히 하나를 가리킨다")
        return self

    @property
    def is_broken(self) -> bool:
        return self.source_availability != "AVAILABLE"


class ChatResponse(Contract):
    """서버가 확정해 내보내는 답변. 모델 출력이 그대로 여기 오지 않는다."""

    contract_version: Literal["v2"] = "v2"
    request_id: str = Field(min_length=1, max_length=80)
    action: AnswerAction
    message: str = Field(min_length=1, max_length=2000)
    snapshot_id: EntityId
    knowledge_revision: RevisionId
    citations: tuple[Citation, ...] = ()
    # CLARIFY 에서만 — 서버가 발급한 문맥과 고를 값
    context_id: UUID | None = None
    allowed_options: tuple[str, ...] = Field(default=(), max_length=10)
    clarification_slot: str | None = Field(default=None, max_length=60)
    # ESCALATE 성공 시에만 — WAITING 저장이 끝난 뒤다 (불변식 5)
    pending_id: EntityId | None = None

    @model_validator(mode="after")
    def _fields_match_action(self) -> "ChatResponse":
        if self.action == "ANSWER":
            if not self.citations:
                raise ValueError("ANSWER 는 인용 없이 나갈 수 없다 (불변식 3·6)")
            if self.context_id or self.pending_id:
                raise ValueError("ANSWER 에 문맥·대기 식별자를 함께 두지 않는다")
        elif self.citations:
            raise ValueError(f"{self.action} 은 매장 지식을 인용하지 않는다")

        if self.action == "CLARIFY":
            if not (self.context_id and self.allowed_options
                    and self.clarification_slot):
                raise ValueError("CLARIFY 에는 문맥·슬롯·고를 값이 필요하다")
            if self.pending_id:
                raise ValueError(
                    "CLARIFY 는 점주에게 넘기지 않는다. 불필요한 알림이 쌓인다")
        elif self.clarification_slot or self.allowed_options:
            raise ValueError(f"{self.action} 에 되묻기 필드를 두지 않는다")

        if self.action == "ESCALATE" and not self.pending_id:
            raise ValueError(
                "ESCALATE 응답은 WAITING 저장이 끝난 뒤에만 만든다 (불변식 5)")
        if self.action in POLICY_MESSAGES:
            if self.message != POLICY_MESSAGES[self.action]:
                raise ValueError(
                    f"{self.action} 은 고정 문구를 쓴다. 모델이 문장을 만들지 않는다")
            if self.pending_id:
                raise ValueError(f"{self.action} 은 자동으로 점주에게 넘기지 않는다")
        return self

    def citation_count(self) -> int:
        """저장되는 인용 행 기준이다. 사실 개수로 부풀리지 않는다 (§5.2)."""
        return len(self.citations)

    def broken_citations(self) -> tuple[Citation, ...]:
        return tuple(c for c in self.citations if c.is_broken)


class ValidateAndSaveAnswerRequest(Contract):
    """검증과 저장 사이의 TOCTOU 를 닫기 위해 예상 판을 함께 받는다 (§4.2)."""

    store_id: EntityId
    member_id: EntityId
    chat_session_id: EntityId
    request_id: str = Field(min_length=1, max_length=80)
    expected_snapshot_id: EntityId
    expected_knowledge_revision: RevisionId
    plan: AnswerPlan

    @model_validator(mode="after")
    def _plan_matches_expectation(self) -> "ValidateAndSaveAnswerRequest":
        if self.plan.snapshot_id != self.expected_snapshot_id:
            raise ValueError("계획과 예상 snapshot 이 다르다")
        if self.plan.knowledge_revision != self.expected_knowledge_revision:
            raise ValueError("계획과 예상 knowledge_revision 이 다르다")
        return self
