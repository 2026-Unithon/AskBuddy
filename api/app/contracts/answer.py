"""답변 계약 — R 이 무엇을 어떻게 답할지 (MVP 31-5).

`action` 이 다섯이고 인프라 `ERROR` 는 별도 응답이다. 이 구분이 중요한 이유:
  - `CLARIFY`(되묻기)를 기존 miss 로 처리하면 불필요한 WAITING·점주 알림이 쌓인다
  - `ERROR`(장애)를 지식 miss 로 만들면 "모르는 것" 과 "고장난 것" 이 섞인다

`ANSWER` 는 **승인 블록 최소 하나와 인용**이 있어야 한다 (불변식 3·6).
서버가 검사하며, 모델의 판단을 믿지 않는다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import (
    SCHEMA_ANSWER_PLAN,
    Contract,
    EntityId,
    FrozenContract,
    RevisionId,
)

AnswerAction = Literal["ANSWER", "CLARIFY", "ESCALATE", "REFUSE", "SAFE_ROUTE"]
"""
ANSWER      승인 근거를 서버가 렌더링한 답변·인용   pending 없음
CLARIFY     모호한 슬롯을 되묻는다                  pending 없음
ESCALATE    지식 부족·미해소 충돌                   WAITING 저장 성공 시에만 생성
REFUSE      정책상 답할 수 없다는 안내              자동 pending 없음
SAFE_ROUTE  안전 판정을 추측하지 않는 고정 안내      자동 pending 없음
"""


class SelectedBlock(FrozenContract):
    """인용할 블록. 카드 버전까지 고정해 과거 인용이 재현되게 한다."""

    card_id: EntityId
    card_version_id: EntityId
    block_id: str = Field(min_length=1, max_length=40)
    fact_revision_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _no_duplicate_citation(self) -> "SelectedBlock":
        if len(set(self.fact_revision_ids)) != len(self.fact_revision_ids):
            raise ValueError("같은 사실을 두 번 인용하지 않는다")
        return self


class AnswerPlan(Contract):
    schema_version: Literal["answer_plan/v1"] = SCHEMA_ANSWER_PLAN
    # 어느 공개 상태에서 답했는가. 재현과 캐시 무효화에 쓴다
    snapshot_id: EntityId
    knowledge_revision: RevisionId
    action: AnswerAction

    selected_blocks: tuple[SelectedBlock, ...] = Field(default=(), max_length=20)
    # CLARIFY — 무엇이 모호한지와 고를 수 있는 값
    clarification_slot: str | None = Field(default=None, max_length=60)
    allowed_options: tuple[str, ...] = Field(default=(), max_length=10)
    context_id: str | None = Field(default=None, max_length=80)
    # ESCALATE — 왜 넘기는지
    escalation_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _fields_match_action(self) -> "AnswerPlan":
        """action 마다 쓰는 필드를 **배타적으로** 고정한다 (RV-03).

        필요한 것이 있는지만 보면 남는 것이 섞여도 통과한다. ESCALATE 에 되묻기
        슬롯과 context_id 가 함께 실린 계획은 R 이 "넘김" 으로 저장하면서 동시에
        되묻기 화면을 띄울 수 있다 — 점주에게 알림이 가는데 신입은 답을 고르고 있다.
        """
        present = {
            "selected_blocks": bool(self.selected_blocks),
            "clarification_slot": self.clarification_slot is not None,
            "allowed_options": bool(self.allowed_options),
            "context_id": self.context_id is not None,
            "escalation_reason": self.escalation_reason is not None,
        }
        allowed: dict[str, set[str]] = {
            "ANSWER": {"selected_blocks"},
            "CLARIFY": {"clarification_slot", "allowed_options", "context_id"},
            "ESCALATE": {"escalation_reason"},
            "REFUSE": set(),
            "SAFE_ROUTE": set(),
        }
        extra = sorted(k for k, v in present.items()
                       if v and k not in allowed[self.action])
        if extra:
            raise ValueError(
                f"{self.action} 에 쓰지 않는 필드가 들어 있다: {extra}")

        if self.action == "ANSWER" and not self.selected_blocks:
            raise ValueError(
                "ANSWER 에는 승인 블록 인용이 최소 하나 필요하다 (불변식 3·6)")
        if self.action == "CLARIFY":
            if not self.clarification_slot or not self.allowed_options:
                raise ValueError("CLARIFY 에는 슬롯과 고를 값이 필요하다")
            if not self.context_id:
                raise ValueError("CLARIFY 에는 소유권·TTL 을 검사할 context_id 가 필요하다")
            if len(set(self.allowed_options)) != len(self.allowed_options):
                raise ValueError("고를 값이 중복됐다")
        if self.action == "ESCALATE" and not self.escalation_reason:
            raise ValueError("ESCALATE 에는 넘기는 사유가 필요하다")

        seen = [(b.card_id, b.block_id) for b in self.selected_blocks]
        if len(seen) != len(set(seen)):
            raise ValueError("같은 블록을 두 번 인용하지 않는다")
        return self

    def citation_count(self) -> int:
        return sum(len(b.fact_revision_ids) for b in self.selected_blocks)
