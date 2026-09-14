"""C0 공통 계약. W(쓰기)와 R(읽기)의 유일한 접점이다.

한쪽만 고치면 계약이 깨진다. 변경은 양쪽 검토를 거친다 (TODO C0-5).
"""
from app.contracts.answer import AnswerAction, AnswerPlan, SelectedBlock
from app.contracts.card import (
    BlockKind,
    CardBlock,
    CardPlan,
    Disposition,
    OccurrenceDisposition,
)
from app.contracts.common import (
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
)
from app.contracts.validate import AnswerPlanViolation, validate_answer_plan

__all__ = [
    "AnswerAction", "AnswerPlan", "SelectedBlock",
    "BlockKind", "CardBlock", "CardPlan", "Disposition", "OccurrenceDisposition",
    "Contract", "EntityId", "FrozenContract", "Polarity", "Quantity", "Variant",
    "RawText", "RevisionId", "Sha256Hex", "UtcDatetime", "MAX_BIGINT", "as_id",
    "SCHEMA_ANSWER_PLAN", "SCHEMA_CARD_PLAN", "SCHEMA_EXTRACTION", "SCHEMA_PUBLISHED",
    "Assertion", "EvidenceLocator", "ExtractionEnvelope", "ExtractionStatus",
    "LocatorType",
    "FactProvenance", "FactRevision", "PublishedCard", "PublishedKnowledgeSnapshot",
    "AnswerPlanViolation", "validate_answer_plan",
]
