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
    SCHEMA_ANSWER_PLAN,
    SCHEMA_CARD_PLAN,
    SCHEMA_EXTRACTION,
    SCHEMA_PUBLISHED,
    Contract,
    EntityId,
    Polarity,
    Quantity,
    Variant,
    as_id,
)
from app.contracts.extraction import (
    Assertion,
    EvidenceLocator,
    ExtractionEnvelope,
    LocatorType,
)
from app.contracts.snapshot import (
    FactRevision,
    PublishedCard,
    PublishedKnowledgeSnapshot,
)

__all__ = [
    "AnswerAction", "AnswerPlan", "SelectedBlock",
    "BlockKind", "CardBlock", "CardPlan", "Disposition", "OccurrenceDisposition",
    "Contract", "EntityId", "Polarity", "Quantity", "Variant", "as_id",
    "SCHEMA_ANSWER_PLAN", "SCHEMA_CARD_PLAN", "SCHEMA_EXTRACTION", "SCHEMA_PUBLISHED",
    "Assertion", "EvidenceLocator", "ExtractionEnvelope", "LocatorType",
    "FactRevision", "PublishedCard", "PublishedKnowledgeSnapshot",
]
