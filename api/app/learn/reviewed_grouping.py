"""Exact human-reviewed scope, never a model-supplied pending ID."""
from dataclasses import dataclass
from typing import Literal
from pydantic import Field, model_validator
from app.contracts.common import Contract
from app.contracts.hashing import digest

VERSION = 'r-reviewed-grouping/v1'


class GroupingReview(Contract):
    entity: str = Field(min_length=1, max_length=100)
    predicate: str = Field(min_length=1, max_length=100)
    temperature: Literal['HOT', 'ICE']
    size: str | None
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    scope_bindings: tuple[str, ...]
    polarity: Literal['POSITIVE', 'NEGATIVE']
    # Empty arrays and null size require explicit review too; no defaults.
    complete: Literal[True]

    @model_validator(mode='after')
    def complete_scope(self):
        if not self.entity.strip() or not self.predicate.strip() or (self.size is not None and not self.size.strip()):
            raise ValueError('blank scope')
        for values in (self.conditions, self.exceptions, self.scope_bindings):
            if any(not x.strip() for x in values) or tuple(sorted(set(values))) != values:
                raise ValueError('scope must be complete, distinct and sorted')
        return self


@dataclass(frozen=True)
class GroupingEvidence:
    """Server-only capability produced after pinned catalog admission."""
    store_id: str
    snapshot_hash: str
    question: str
    approval_id: str
    scope: GroupingReview


def reviewed_context(snapshot, *, evidence, question):
    if not isinstance(evidence, GroupingEvidence):
        raise ValueError('server review evidence required')
    if (evidence.store_id != snapshot.store_id or evidence.snapshot_hash != snapshot.snapshot_hash
            or evidence.question != question or not evidence.approval_id.strip()):
        raise ValueError('review binding mismatch')
    scope = GroupingReview.model_validate(evidence.scope.model_dump())
    if scope.entity not in {c.entity_id for c in snapshot.cards}:
        raise ValueError('review entity outside approved snapshot')
    return dict(version=VERSION, store_id=snapshot.store_id, snapshot_id=snapshot.snapshot_id,
        knowledge_revision=snapshot.knowledge_revision, snapshot_hash=snapshot.snapshot_hash,
        scope=scope.model_dump(mode='json'))


def reviewed_key(*, store_id, context):
    if (set(context) != {'version','store_id','snapshot_id','knowledge_revision','snapshot_hash','scope'}
            or context['version'] != VERSION or context['store_id'] != str(store_id)):
        raise ValueError('review scope mismatch')
    GroupingReview.model_validate(context['scope'])
    return digest(context)
