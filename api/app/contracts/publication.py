"""발행·색인·점주 답변 반영의 내부 서비스 계약 (§4.1~4.3).

여기 있는 것은 **내부 DTO 이지 공개 endpoint 가 아니다.** 이름이 같다고 해서
그대로 URL 이 되지 않는다.

두 가지를 타입으로 못 박는다:

1. **매장은 신뢰 범위에서 온다.** `TrustedScope` 를 따로 둬서 요청 본문에 실려 온
   store_id 를 그대로 쓰는 코드가 눈에 띄게 했다. RLS 가 없으므로 격리는 전부
   API 코드 책임이다 (D1·불변식 4).
2. **예상 revision 을 반드시 들고 온다.** 없으면 마지막 쓰기가 이긴다 —
   점주가 검수 중인 카드를 다른 발행이 조용히 덮어쓴다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import (
    Contract,
    EntityId,
    HashRef,
    RevisionId,
    UtcDatetime,
)
from app.contracts.errors import ErrorDetail

PrepareStatus = Literal["PREPARED", "FAILED"]
PublishStatus = Literal["PUBLISHED", "ALREADY_APPLIED", "STALE", "FAILED"]
OwnerApplyStatus = Literal["LINKED", "REVIEW", "PUBLISHED", "FAILED"]

EventType = Literal[
    "KNOWLEDGE_PUBLISHED",
    "CARD_EXCLUDED",
    "CARD_RESTORED",
    "OWNER_ANSWER_SUBMITTED",
]


class TrustedScope(Contract):
    """JWT 와 현재 membership 으로 확인한 범위. **요청 본문에서 만들지 않는다.**

    내부 worker 도 이 값을 필수로 전달받는다. "호출한 쪽이 알아서 걸렀겠지" 로
    두면 매장 격리가 호출 경로마다 달라진다.
    """

    store_id: EntityId
    member_id: EntityId | None = None


class IdempotencyKey(Contract):
    """같은 요청이 두 번 와도 업무가 두 번 생기지 않게 하는 키 (§4.3).

    같은 키에 다른 본문이면 `IDEMPOTENCY_CONFLICT` 다 — 조용히 덮지 않는다.
    """

    key: str = Field(min_length=8, max_length=80)
    body_hash: HashRef


class PrepareIndexRequest(Contract):
    scope: TrustedScope
    idempotency: IdempotencyKey
    # 준비 단위는 공개 요청의 변경 카드 묶음 전체다. 일부만 준비하고 공개하지 않는다
    card_ids: tuple[EntityId, ...] = Field(min_length=1, max_length=500)
    content_hash: HashRef
    expected_publication_revision: RevisionId
    expected_card_revisions: tuple[RevisionId, ...] = ()
    embedding_model: str = Field(min_length=1, max_length=60)
    glossary_version: str = Field(max_length=40)
    renderer_version: str = Field(max_length=40)


class PrepareIndexResult(Contract):
    status: PrepareStatus
    prepared_id: EntityId | None = None
    payload_hash: HashRef | None = None
    index_config_version: str | None = Field(default=None, max_length=40)
    # 준비 토큰 TTL 15분. 지나면 다시 준비한다 (§4.1)
    expires_at: UtcDatetime | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def _status_matches_payload(self) -> "PrepareIndexResult":
        if self.status == "PREPARED":
            missing = [n for n in ("prepared_id", "payload_hash",
                                   "index_config_version", "expires_at")
                       if getattr(self, n) is None]
            if missing:
                raise ValueError(f"PREPARED 에 빠진 값이 있다: {missing}")
            if self.error:
                raise ValueError("PREPARED 에 오류를 함께 두지 않는다")
        elif not self.error:
            raise ValueError("FAILED 에는 구조화된 오류가 필요하다")
        return self


class PublishKnowledgeRequest(Contract):
    scope: TrustedScope
    idempotency: IdempotencyKey
    prepared_id: EntityId
    expected_publication_revision: RevisionId
    expected_draft_revision: RevisionId | None = None
    expected_card_revisions: tuple[RevisionId, ...] = ()
    # 점주 승인 없이 공개하지 않는다. 누가 언제 승인했는지가 근거다
    approved_by: EntityId
    approved_at: UtcDatetime


class PublishKnowledgeResult(Contract):
    status: PublishStatus
    snapshot_id: EntityId | None = None
    snapshot_hash: HashRef | None = None
    knowledge_revision: RevisionId | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def _status_matches_payload(self) -> "PublishKnowledgeResult":
        if self.status in ("PUBLISHED", "ALREADY_APPLIED"):
            # 멱등 재시도도 **어느 판이 됐는지** 돌려준다. 아니면 재시도한 쪽이
            # 성공했는지 모른 채 또 부른다
            missing = [n for n in ("snapshot_id", "snapshot_hash",
                                   "knowledge_revision")
                       if getattr(self, n) is None]
            if missing:
                raise ValueError(f"{self.status} 에 빠진 값이 있다: {missing}")
            if self.error:
                raise ValueError(f"{self.status} 에 오류를 함께 두지 않는다")
        elif not self.error:
            raise ValueError(f"{self.status} 에는 구조화된 오류가 필요하다")
        return self


class CardVisibilityRequest(Contract):
    """카드 제외·복원. 공개와 같은 조정 서비스를 쓴다 (§4.1)."""

    scope: TrustedScope
    idempotency: IdempotencyKey
    card_id: EntityId
    action: Literal["EXCLUDE", "RESTORE"]
    expected_publication_revision: RevisionId
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _exclusion_has_a_reason(self) -> "CardVisibilityRequest":
        if self.action == "EXCLUDE" and not self.reason:
            raise ValueError("제외에는 사유가 필요하다. 나중에 왜 빠졌는지 답해야 한다")
        return self


class ApplyOwnerAnswerRequest(Contract):
    scope: TrustedScope
    owner_answer_id: EntityId
    event_id: EntityId


class ApplyOwnerAnswerResult(Contract):
    status: OwnerApplyStatus
    # 원문 전파 상태와 지식화 상태를 한 enum 에 섞지 않는다 (§5.3).
    # 여기 담기는 것은 **지식화** 상태뿐이다
    fact_revision_id: EntityId | None = None
    card_id: EntityId | None = None
    knowledge_revision: RevisionId | None = None
    retryable: bool = False
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def _status_matches_payload(self) -> "ApplyOwnerAnswerResult":
        if self.status == "FAILED":
            if not self.error:
                raise ValueError("FAILED 에는 구조화된 오류가 필요하다")
        elif self.error:
            raise ValueError(f"{self.status} 에 오류를 함께 두지 않는다")
        if self.status == "PUBLISHED" and self.knowledge_revision is None:
            raise ValueError("PUBLISHED 는 어느 판으로 나갔는지 밝힌다")
        return self


class OutboxEvent(Contract):
    """소비자에게 나가는 사건. **업무 내용을 담지 않는다** (§4.3).

    원문·직원 목록을 payload 에 실으면 권한이 바뀐 뒤에도 옛 내용이 전달된다.
    소비자는 이 사건을 신호로만 쓰고 내용은 권한 있는 조회로 가져온다.
    """

    contract_version: Literal["v1"] = "v1"
    event_id: EntityId
    store_id: EntityId
    type: EventType
    aggregate_id: EntityId
    knowledge_revision: RevisionId | None = None
    owner_answer_id: EntityId | None = None
    occurred_at: UtcDatetime

    @model_validator(mode="after")
    def _payload_matches_type(self) -> "OutboxEvent":
        if self.type == "OWNER_ANSWER_SUBMITTED":
            if not self.owner_answer_id:
                raise ValueError("OWNER_ANSWER_SUBMITTED 에는 owner_answer_id 가 필요하다")
        elif self.knowledge_revision is None:
            raise ValueError(f"{self.type} 에는 knowledge_revision 이 필요하다")
        return self
