"""C0 공통 계약. W(쓰기)와 R(읽기)의 유일한 접점이다.

한쪽만 고치면 계약이 깨진다. 변경은 양쪽 검토를 거친다 (TODO C0-5).
"""
from app.contracts.answer import AnswerAction, AnswerPlan, SelectedBlock
from app.contracts.chat import (
    BROKEN_CITATION_LABEL,
    DELETED_SOURCE_NOTE,
    POLICY_MESSAGES,
    POLICY_VERSION,
    REFUSE_MESSAGE,
    SAFE_ROUTE_MESSAGE,
    ChatResponse,
    Citation,
    KnowledgeState,
    QuestionContext,
    SourceAvailability,
    ValidateAndSaveAnswerRequest,
)
from app.contracts.errors import (
    CONTRACT_VERSION,
    ERROR_TABLE,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    error,
)
from app.contracts.hashing import (
    canonical_json,
    digest,
    snapshot_digest,
    snapshot_payload,
    verify_snapshot_hash,
)
from app.contracts.publication import (
    ApplyOwnerAnswerRequest,
    ApplyOwnerAnswerResult,
    CardVisibilityRequest,
    EventType,
    IdempotencyKey,
    OutboxEvent,
    PrepareIndexRequest,
    PrepareIndexResult,
    PublishKnowledgeRequest,
    PublishKnowledgeResult,
    TrustedScope,
)
from app.contracts.card import (
    BlockKind,
    CardBlock,
    CardPlan,
    Disposition,
    OccurrenceDisposition,
)
from app.contracts.common import (
    HashRef,
    MAX_BIGINT,
    SCHEMA_ANSWER_PLAN,
    SCHEMA_CARD_PLAN,
    SCHEMA_EXTRACTION,
    SCHEMA_PUBLISHED,
    Contract,
    EntityId,
    FrozenContract,
    Polarity,
    Quantity,
    RawText,
    RevisionId,
    Sha256Hex,
    UtcDatetime,
    Variant,
    as_id,
)
from app.contracts.extraction import (
    Assertion,
    EvidenceLocator,
    ExtractionEnvelope,
    ExtractionStatus,
    LocatorType,
)
from app.contracts.snapshot import (
    FactProvenance,
    FactRevision,
    PublishedCard,
    PublishedKnowledgeSnapshot,
    RawSpan,
)
from app.contracts.validate import AnswerPlanViolation, validate_answer_plan

__all__ = [
    "AnswerAction", "AnswerPlan", "SelectedBlock",
    "BlockKind", "CardBlock", "CardPlan", "Disposition", "OccurrenceDisposition",
    "Contract", "EntityId", "FrozenContract", "Polarity", "Quantity", "Variant",
    "RawText", "RevisionId", "Sha256Hex", "HashRef", "UtcDatetime", "MAX_BIGINT",
    "as_id",
    "ChatResponse", "Citation", "QuestionContext", "ValidateAndSaveAnswerRequest",
    "KnowledgeState", "SourceAvailability", "POLICY_MESSAGES", "POLICY_VERSION",
    "REFUSE_MESSAGE", "SAFE_ROUTE_MESSAGE", "BROKEN_CITATION_LABEL",
    "DELETED_SOURCE_NOTE",
    "ErrorCode", "ErrorDetail", "ErrorEnvelope", "ERROR_TABLE", "CONTRACT_VERSION",
    "error",
    "canonical_json", "digest", "snapshot_payload", "snapshot_digest",
    "verify_snapshot_hash",
    "TrustedScope", "IdempotencyKey", "OutboxEvent", "EventType",
    "PrepareIndexRequest", "PrepareIndexResult",
    "PublishKnowledgeRequest", "PublishKnowledgeResult",
    "CardVisibilityRequest", "ApplyOwnerAnswerRequest", "ApplyOwnerAnswerResult",
    "SCHEMA_ANSWER_PLAN", "SCHEMA_CARD_PLAN", "SCHEMA_EXTRACTION", "SCHEMA_PUBLISHED",
    "Assertion", "EvidenceLocator", "ExtractionEnvelope", "ExtractionStatus",
    "LocatorType",
    "FactProvenance", "FactRevision", "PublishedCard", "PublishedKnowledgeSnapshot",
    "RawSpan",
    "AnswerPlanViolation", "validate_answer_plan",
]
