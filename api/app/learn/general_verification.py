"""Bounded verifier diagnostics and server-owned rejection routing.

The verifier may reject an answer; that is not evidence that its subject is
unknown. Never replay a planner's broad entity choice after such a rejection.
"""
import logging
from typing import Literal
from uuid import uuid4

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.contracts.answer import AnswerPlan
from app.contracts.common import Contract, EntityId
from app.errors import ApiError
from app.learn.answer_validation import ResolvedSelection
from app.learn.clarification_scope import validate_options
from app.learn.planner import Decision
from app.learn.case_clarification import CaseOption, validate_case_options
from dataclasses import replace
from app.learn.grounded_conclusions import CandidateCoverage,RuleCoverage,CaseActionReview,SituationReview

logger = logging.getLogger(__name__)


class VerificationClarification(Contract):
    slot: Literal['entity', 'temperature', 'size', 'case']
    allowed_options: tuple[str, ...] = Field(min_length=2, max_length=10)
    # Separate acceptance of the proposed subject/predicate, not of the answer.
    scope_supported: StrictBool
    case_options: tuple[CaseOption, ...] = Field(default=(), max_length=10)


class Verification(Contract):
    request_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    supported: StrictBool
    unresolved: tuple[str, ...] = Field(max_length=20)
    checked_fact_ids: tuple[EntityId, ...] = Field(max_length=100,
        description='Only the selected answer facts: copy selected_reference_check.checked_fact_ids exactly. Do not add unselected candidate facts; inspect those in candidate_coverage.')
    checked_raw_blocks: tuple[tuple[str, str, str, str], ...] = Field(max_length=100,
        description='Only selected answer RAW references: copy selected_reference_check.checked_raw_blocks exactly. Each tuple is [card_id,card_version_id,block_id,raw_span_id]. Not all inspected candidates; those belong in candidate_coverage.')
    checked_user_turn_ids: tuple[StrictInt, ...] = Field(default=(), max_length=11)
    reason_code: Literal['MISSING_USER_INFO', 'MISSING_KNOWLEDGE', 'CONTEXT_CONFLICT',
                         'UNSUPPORTED_OPERATION', 'INCOMPLETE_ANSWER', 'UNVERIFIABLE'] | None = None
    reason_detail: str = Field(default='', max_length=1000)
    clarification: VerificationClarification | None = None
    checked_conclusion_ids: tuple[StrictInt,...] = Field(default=(),max_length=8)
    case_action_review: CaseActionReview | None = Field(default=None,
        description='Required for grounded ANSWER. Independently decide whether the question asks actions for named cases with user-stated states. CASE_ACTIONS enumerates every relevant case and binds its exact user subject/state to its conclusion and exact next action quote; missing conclusion is null. NOT_APPLICABLE needs a reason and cases=[]. Non-answer/original mode: null.')
    rule_coverage: tuple[RuleCoverage,...] = Field(default=(),max_length=200,
        description='Inspect every selected_rules item. Select the server conclusion_units.unit_id whose text actually applies the rule; never copy policy text or invent IDs. Required but missing application: conclusion_unit_id=null; reject INCOMPLETE_ANSWER.')
    situation_review: tuple[SituationReview,...] = Field(default=(),max_length=200,
        description='Inspect every conclusion_units item exactly once. Distinguish general/conditional guidance (NO_CASE_FACTS), case facts fully supported by cited user utterances (GROUNDED_CASE_FACTS), and any invented/unconfirmed case condition (UNSUPPORTED_CASE_FACTS). Policy conditions are not evidence that this case meets them. Unsupported claims require rejection even if other facts are grounded.')
    candidate_coverage: tuple[CandidateCoverage,...] = Field(default=(),max_length=200,
        description='For supported ANSWER, classify every candidate_reference_units item exactly once, including unselected candidates. This is separate from checked_fact_ids/checked_raw_blocks, which contain selected references only.')

    @model_validator(mode='after')
    def consistent_verdict(self):
        if self.supported and (self.unresolved or self.reason_code or self.reason_detail or self.clarification):
            raise ValueError('supported verdict cannot contain rejection diagnostics')
        if self.reason_code and not self.reason_detail.strip():
            raise ValueError('classified rejection requires an explanation')
        if self.clarification and self.reason_code != 'MISSING_USER_INFO':
            raise ValueError('only missing user information may request clarification')
        return self


def rejection_decision(search, *, verdict, proposal, question, trusted_slots, user_turns=(),
                       context_id, clarify_turns, audit):
    """No answer reference or unconfirmed slot survives a rejected answer."""
    reason = verdict.reason_code or 'UNVERIFIABLE'
    diagnostic = dict(audit, status='VERIFIER_REJECTED', reason_code=reason,
                      reason_detail=verdict.reason_detail, unresolved=list(verdict.unresolved),
                      checked_user_turn_ids=list(verdict.checked_user_turn_ids))
    # Error responses have no receipt. Log only codes/hashes, not user text or
    # the model's arbitrary explanation. Successful fallbacks persist full audit.
    logger.warning('general_verification_rejected reason=%s verification=%s',
                   reason, audit['verification_hash'], extra={'general_verification': {
        k: v for k, v in diagnostic.items() if k not in ('reason_detail', 'unresolved')}})
    base = dict(snapshot_id=search.snapshot.snapshot_id, knowledge_revision=search.snapshot.knowledge_revision)
    resolved = ResolvedSelection('', '', (), question)
    if reason == 'MISSING_USER_INFO' and verdict.clarification:
        clarify = verdict.clarification
        query = proposal.interpretation
        if (proposal.parts and clarify.slot!='case') or not clarify.scope_supported:
            raise ValueError('clarification scope was not independently accepted')
        if clarify.slot == 'case':
            validate_case_options(clarify.case_options,allowed_options=clarify.allowed_options,
                question=question,user_turns=user_turns,confirmed_slots=trusted_slots)
            resolved=replace(resolved,case_options=clarify.case_options,case_user_turns=tuple(user_turns))
        elif clarify.case_options:
            raise ValueError('case evidence belongs only to case clarification')
        elif clarify.slot == 'entity':
            if query is not None:
                raise ValueError('cannot discard a proposed subject for broad entity clarification')
        else:
            if query is None:
                raise ValueError('targeted clarification requires a bound subject and predicate')
            resolved = ResolvedSelection(query.entity_id, query.predicate, (), question)
        plan = AnswerPlan(**base, action='CLARIFY', clarification_slot=clarify.slot,
                          allowed_options=clarify.allowed_options, context_id=context_id or uuid4())
        if clarify.slot!='case':
            validate_options(search, plan=plan, slots=trusted_slots,
                             entity_id=resolved.entity_id, predicate=resolved.predicate)
        if clarify_turns >= 2:
            plan = AnswerPlan(**base, action='ESCALATE', escalation_reason='UNRESOLVED_CONTEXT')
        return Decision(plan, resolved, dict(trusted_slots), None), dict(diagnostic, fallback_action=plan.action)
    if reason in ('MISSING_KNOWLEDGE', 'UNSUPPORTED_OPERATION', 'MISSING_USER_INFO'):
        # Missing fields outside the supported choice contract cannot be invented
        # as entity/temperature/size options. Preserve the question for the owner.
        escalation = 'UNRESOLVED_CONTEXT' if reason == 'MISSING_USER_INFO' else 'INSUFFICIENT_KNOWLEDGE'
        plan = AnswerPlan(**base, action='ESCALATE', escalation_reason=escalation)
        return Decision(plan, resolved, dict(trusted_slots), None), dict(diagnostic, fallback_action='ESCALATE')
    raise ApiError(503, 'GENERAL_VERIFICATION_REJECTED',
                   '질문에 맞는 답변인지 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.',
                   retryable=True, details={'reason_code': reason, 'verification_hash': audit['verification_hash']})
