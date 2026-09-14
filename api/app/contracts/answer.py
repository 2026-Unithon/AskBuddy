"""답변 계약 — R 이 무엇을 어떻게 답할지 (MVP 31-5).

`action` 이 다섯이고 인프라 `ERROR` 는 별도 응답이다. 이 구분이 중요한 이유:
  - `CLARIFY`(되묻기)를 기존 miss 로 처리하면 불필요한 WAITING·점주 알림이 쌓인다
  - `ERROR`(장애)를 지식 miss 로 만들면 "모르는 것" 과 "고장난 것" 이 섞인다

`ANSWER` 는 **승인 블록 최소 하나와 인용**이 있어야 한다 (불변식 3·6).
서버가 검사하며, 모델의 판단을 믿지 않는다.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, ConfigDict, Field, model_validator

from app.contracts.common import SCHEMA_ANSWER_PLAN, Contract


def _bigint(value: str) -> str:
    if int(value) > 9223372036854775807:
        raise ValueError("bigint 범위를 벗어났다")
    return value


# W 공통 ID 타입 동결 전에도 R 입력 경계는 엄격하게 검사한다.
AnswerId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$"), AfterValidator(_bigint)]
Revision = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,18})$"), AfterValidator(_bigint)]

AnswerAction = Literal["ANSWER", "CLARIFY", "ESCALATE", "REFUSE", "SAFE_ROUTE"]
"""
ANSWER      승인 근거를 서버가 렌더링한 답변·인용   pending 없음
CLARIFY     모호한 슬롯을 되묻는다                  pending 없음
ESCALATE    지식 부족·미해소 충돌                   WAITING 저장 성공 시에만 생성
REFUSE      정책상 답할 수 없다는 안내              자동 pending 없음
SAFE_ROUTE  안전 판정을 추측하지 않는 고정 안내      자동 pending 없음
"""


class SelectedBlock(Contract):
    """인용할 블록. 카드 버전까지 고정해 과거 인용이 재현되게 한다."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    card_id: AnswerId
    card_version_id: AnswerId
    block_id: str = Field(min_length=1, max_length=40)
    fact_revision_ids: tuple[AnswerId, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_facts(self) -> "SelectedBlock":
        if not self.block_id.strip() or len(set(self.fact_revision_ids)) != len(self.fact_revision_ids):
            raise ValueError("빈 블록 식별자 또는 중복 사실 참조")
        return self


class AnswerPlan(Contract):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)
    schema_version: Literal["answer_plan/v1"] = SCHEMA_ANSWER_PLAN
    # 어느 공개 상태에서 답했는가. 재현과 캐시 무효화에 쓴다
    snapshot_id: AnswerId
    knowledge_revision: Revision
    action: AnswerAction

    selected_blocks: tuple[SelectedBlock, ...] = ()
    # CLARIFY — 무엇이 모호한지와 고를 수 있는 값
    clarification_slot: str | None = Field(default=None, max_length=60)
    allowed_options: tuple[str, ...] = Field(default=(), max_length=10)
    context_id: UUID | None = None
    # ESCALATE — 왜 넘기는지
    escalation_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _fields_match_action(self) -> "AnswerPlan":
        clarification = (
            self.clarification_slot is not None or bool(self.allowed_options)
            or self.context_id is not None
        )
        if self.action != "CLARIFY" and clarification:
            raise ValueError("CLARIFY 전용 필드는 다른 action에 허용하지 않는다")
        if self.action != "ESCALATE" and self.escalation_reason is not None:
            raise ValueError("ESCALATE 전용 필드는 다른 action에 허용하지 않는다")
        keys = [(b.card_id, b.card_version_id, b.block_id) for b in self.selected_blocks]
        if len(keys) != len(set(keys)):
            raise ValueError("중복 블록 인용")
        if self.action == "ANSWER":
            if not self.selected_blocks:
                raise ValueError(
                    "ANSWER 에는 승인 블록 인용이 최소 하나 필요하다 (불변식 3·6)")
            if self.clarification_slot or self.escalation_reason:
                raise ValueError("ANSWER 에 되묻기·넘김 필드를 함께 두지 않는다")
        elif self.action == "CLARIFY":
            if not self.clarification_slot or not self.clarification_slot.strip() or not self.allowed_options:
                raise ValueError("CLARIFY 에는 슬롯과 고를 값이 필요하다")
            if not self.context_id:
                raise ValueError("CLARIFY 에는 소유권·TTL 을 검사할 context_id 가 필요하다")
            if any(not option.strip() for option in self.allowed_options) or len(set(self.allowed_options)) != len(self.allowed_options):
                raise ValueError("빈 선택지 또는 중복 선택지")
            if self.selected_blocks:
                raise ValueError("CLARIFY 는 아직 답하지 않는다. 블록을 고르지 않는다")
        elif self.action == "ESCALATE":
            if not self.escalation_reason or not self.escalation_reason.strip():
                raise ValueError("ESCALATE 에는 넘기는 사유가 필요하다")
            if self.selected_blocks:
                raise ValueError("ESCALATE 는 답하지 않는다. 블록을 고르지 않는다")
        else:  # REFUSE · SAFE_ROUTE
            if self.selected_blocks:
                raise ValueError(f"{self.action} 은 매장 지식을 인용하지 않는다")
        return self

    def citation_count(self) -> int:
        return len(self.selected_blocks)
