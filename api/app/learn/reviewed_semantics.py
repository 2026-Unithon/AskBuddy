"""Deploy-reviewed model proposals -> server assessment -> ordinary v2 persistence.

This is exact reviewed-input admission, not unrestricted model authority. The
catalog is a private deployment artifact pinned by an out-of-band content hash.
Neither a request nor a model response can install an approval.
"""
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator
from app.contracts.common import Contract, EntityId
from app.contracts.hashing import digest
from app.errors import ApiError
from app.learn.answer_validation import (
    SuitabilityAssessment, FactSuitability, ResolvedSelection,
    question_hash, validate_answer_for_question,
)
from app.learn.planner import Decision, policy_action
from app.learn.semantic_proposals import SemanticProposal, proposal_input, validate_proposal


class FactReview(Contract):
    fact_revision_id: EntityId
    variant_scope: Literal['SPECIFIC', 'NOT_APPLICABLE']
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]


class InterpretationReview(Contract):
    entity_id: str = Field(min_length=1, max_length=100)
    predicate: str = Field(min_length=1, max_length=100)
    variants: tuple[tuple[str | None, str | None], ...]
    target_fact_ids: tuple[EntityId, ...]
    facts: tuple[FactReview, ...]
    raw_blocks: tuple[tuple[str, str, str, str], ...]


class ReviewedProposal(Contract):
    approval_id: str = Field(min_length=1, max_length=100)
    store_id: EntityId
    question: str = Field(min_length=1, max_length=1000)
    user_turns: tuple[str, ...] = Field(max_length=10)
    confirmed_slots: dict[str, str]
    proposal: SemanticProposal
    interpretation: InterpretationReview | None
    reviewer: str = Field(min_length=1, max_length=100)
    review_reference: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def admissible(self):
        if not all(s.strip() for s in (self.approval_id, self.question, self.reviewer, self.review_reference)):
            raise ValueError('explicit review evidence required')
        if self.proposal.unresolved or self.proposal.equivalent_question_ids:
            raise ValueError('unresolved interpretation or automatic merge is not admitted')
        if self.proposal.plan.action == 'ANSWER' and self.interpretation is None:
            raise ValueError('ANSWER requires a separate human interpretation review')
        if self.proposal.plan.action in ('REFUSE', 'SAFE_ROUTE'):
            raise ValueError('policy actions belong to the server policy')
        return self


class ReviewedCatalog(Contract):
    schema_version: Literal['r_reviewed_semantics/v1'] = 'r_reviewed_semantics/v1'
    acceptance_reference: str = Field(min_length=1, max_length=500)
    entries: tuple[ReviewedProposal, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def distinct(self):
        keys = [(e.store_id, e.proposal.input_hash, digest(e.confirmed_slots)) for e in self.entries]
        if not self.acceptance_reference.strip() or len(set(keys)) != len(keys):
            raise ValueError('acceptance evidence and unambiguous reviews required')
        if len({e.approval_id for e in self.entries}) != len(self.entries):
            raise ValueError('duplicate approval id')
        return self


def load_catalog(path, expected_hash):
    if not path or not expected_hash:
        raise ValueError('private catalog and pinned acceptance hash required')
    with Path(path).open('rb') as stream:
        data = stream.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('catalog too large')
    raw = json.loads(data)
    if digest(raw) != expected_hash:
        raise ValueError('catalog acceptance hash mismatch')
    return ReviewedCatalog.model_validate(raw)


def apply_reviewed(search, *, store_id, question, user_turns, baseline,
                   catalog, context_id=None, context_verified=False, clarify_turns=0):
    # Confirmed policy/explicit answers and unresolved selection offers are never overwritten.
    if baseline.plan.action != 'ESCALATE' or policy_action(question):
        return baseline, None
    if (user_turns or context_id is not None) and not context_verified:
        return baseline, None
    payload = proposal_input(search, store_id=store_id, question=question, user_turns=user_turns)
    match = next((e for e in catalog.entries if e.store_id == str(store_id)
        and e.question == question and e.user_turns == tuple(user_turns)
        and e.confirmed_slots == baseline.confirmed_slots and e.proposal.input_hash == payload['input_hash']), None)
    if match is None:
        return baseline, None
    proposal = validate_proposal(match.proposal.model_dump(), search, payload)
    plan = proposal.plan
    resolved = baseline.resolved
    if plan.action == 'ANSWER':
        review = match.interpretation
        assessment = SuitabilityAssessment(store_id=str(store_id), snapshot_id=search.snapshot.snapshot_id,
            knowledge_revision=search.snapshot.knowledge_revision, snapshot_hash=search.snapshot.snapshot_hash,
            question_hash=question_hash(question), entity_id=review.entity_id, predicate=review.predicate,
            variants=review.variants, target_fact_ids=review.target_fact_ids,
            facts=tuple(FactSuitability(**f.model_dump()) for f in review.facts), raw_blocks=review.raw_blocks)
        resolved = ResolvedSelection(review.entity_id, review.predicate, review.variants, question, assessment)
        validate_answer_for_question(plan, search.snapshot, resolved, store_id=store_id)
    elif plan.action == 'CLARIFY':
        if clarify_turns >= 2:
            return baseline, None
        # The reviewed/model UUID never becomes a reusable context capability.
        plan = plan.model_copy(update={'context_id': context_id or uuid4()})
    # Model slots are proposals, not confirmed values. Model grouping IDs are rejected above.
    return Decision(plan, resolved, dict(baseline.confirmed_slots), None), match.approval_id


def product_decision(search, *, settings, **kwargs):
    if not getattr(settings, 'r_reviewed_semantics_enabled', False):
        return kwargs['baseline'], None
    try:
        catalog = load_catalog(settings.r_reviewed_semantics_path, settings.r_reviewed_semantics_hash)
        return apply_reviewed(search, catalog=catalog, **kwargs)
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        raise ApiError(503, 'SEMANTIC_REVIEW_UNAVAILABLE', '확인된 답변 설정을 검증하지 못했습니다.', retryable=False) from exc
