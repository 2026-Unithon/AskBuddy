"""R 질문 적합성 경계. 승인 참조 검사는 contracts.validate 한 곳에 위임한다.

SuitabilityAssessment는 서버 R3/사람 검토의 결과이며 모델의 자기 승인 DTO가 아니다.
R3 의미 판정 구현은 이 접점 작업에 포함하지 않는다. 누락 판정은 통과시키지 않는다.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from app.contracts import validate as references
from app.contracts.answer import AnswerPlan
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.hashing import verify_snapshot_hash


class AnswerReferenceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FactSuitability:
    """해당 revision의 조건/예외 적용성과 규격 범위를 서버가 확인한 기록."""
    fact_revision_id: str
    variant_scope: Literal["SPECIFIC", "NOT_APPLICABLE"]
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuitabilityAssessment:
    """질문과 승인 판에 결속된 서버 판단. HTTP/LLM 입력으로 노출하지 않는다."""
    store_id: str
    snapshot_id: str
    knowledge_revision: str
    snapshot_hash: str
    question_hash: str
    entity_id: str
    predicate: str
    variants: tuple[tuple[str | None, str | None], ...]
    target_fact_ids: tuple[str, ...] = ()
    facts: tuple[FactSuitability, ...] = ()
    raw_blocks: tuple[tuple[str, str, str, str], ...] = ()


@dataclass(frozen=True)
class ResolvedSelection:
    entity_id: str
    predicate: str
    variants: tuple[tuple[str | None, str | None], ...]
    question: str = ""
    assessment: SuitabilityAssessment | None = None


def question_hash(question: str) -> str:
    """정규화 추정 없이 원문 질문에 판단을 결속한다."""
    return "sha256:" + sha256(question.encode("utf-8")).hexdigest()


def validate_answer_for_question(
    plan: AnswerPlan, snapshot: PublishedKnowledgeSnapshot,
    resolved_query: ResolvedSelection, *, store_id: int,
) -> AnswerPlan:
    """공통 승인 참조 검사 → R 질문 적합성 검사. 모델/DB/알림 호출은 없다."""
    if type(store_id) is not int or not 0 < store_id <= 9223372036854775807:
        raise AnswerReferenceError("INVALID_REFERENCE")
    try:
        validated = references.validate_answer_references(plan, snapshot, store_id=str(store_id))
    except references.AnswerPlanViolation as exc:
        raise AnswerReferenceError(exc.code) from exc
    plan, snapshot = validated.plan, validated.snapshot
    if plan.action != "ANSWER":
        # action 결정·context 소유권·pending 저장은 이 함수의 책임이 아니다.
        return plan
    query = resolved_query
    if not query.entity_id or not query.predicate:
        raise AnswerReferenceError("UNRESOLVED_CONTEXT")
    facts = {f.fact_revision_id: f for f in snapshot.fact_revisions}
    assessment = query.assessment
    checks = {}
    if assessment is not None:
        try:
            verify_snapshot_hash(snapshot)
        except ValueError as exc:
            raise AnswerReferenceError("HASH_MISMATCH") from exc
        expected = (str(store_id), snapshot.snapshot_id, snapshot.knowledge_revision,
                    snapshot.snapshot_hash, question_hash(query.question),
                    query.entity_id, query.predicate, query.variants)
        actual = (assessment.store_id, assessment.snapshot_id, assessment.knowledge_revision,
                  assessment.snapshot_hash, assessment.question_hash,
                  assessment.entity_id, assessment.predicate, assessment.variants)
        if not query.question or expected != actual:
            raise AnswerReferenceError("INVALID_REFERENCE")
        checks = {check.fact_revision_id: check for check in assessment.facts}
        if len(checks) != len(assessment.facts) or not set(checks).issubset(facts):
            raise AnswerReferenceError("INVALID_REFERENCE")
        targets = set(assessment.target_fact_ids)
        if len(targets) != len(assessment.target_fact_ids) or not targets.issubset(facts):
            raise AnswerReferenceError("INVALID_REFERENCE")
        if set(validated.raw_blocks) != set(assessment.raw_blocks):
            raise AnswerReferenceError("INVALID_REFERENCE")
    else:
        if validated.raw_blocks:
            raise AnswerReferenceError("UNRESOLVED_CONTEXT")
        targets = {fid for fid in validated.fact_ids if facts[fid].predicate == query.predicate}
    if not targets and not validated.raw_blocks:
        raise AnswerReferenceError("INVALID_REFERENCE")
    allowed = set()
    pending = list(targets)
    while pending:
        fid = pending.pop()
        if fid not in allowed:
            allowed.add(fid)
            pending.extend(facts[fid].requires)
    if allowed != set(validated.fact_ids):
        raise AnswerReferenceError("INVALID_REFERENCE")
    target_variants = set()
    for fid in validated.fact_ids:
        fact = facts[fid]
        if fact.entity_id != query.entity_id:
            raise AnswerReferenceError("INVALID_REFERENCE")
        if fid in targets and fact.predicate is not None and fact.predicate != query.predicate:
            raise AnswerReferenceError("INVALID_REFERENCE")
        check = checks.get(fid)
        if assessment is not None and check is None:
            raise AnswerReferenceError("UNRESOLVED_CONTEXT")
        if check is None and (fact.conditions or fact.exceptions):
            raise AnswerReferenceError("UNSUPPORTED_SCHEMA")
        if check and (check.conditions != fact.conditions or check.exceptions != fact.exceptions):
            raise AnswerReferenceError("UNRESOLVED_CONTEXT")
        variant = (fact.variant.temperature, fact.variant.size)
        scope = check.variant_scope if check else "SPECIFIC"
        if scope == "NOT_APPLICABLE":
            if variant != (None, None):
                raise AnswerReferenceError("INVALID_REFERENCE")
        elif scope == "SPECIFIC":
            if variant == (None, None) or variant not in query.variants:
                raise AnswerReferenceError("UNRESOLVED_CONTEXT")
            if fid in targets:
                target_variants.add(variant)
        else:
            raise AnswerReferenceError("UNSUPPORTED_SCHEMA")
        if fact.quantity is not None and (not fact.quantity.unit or not fact.quantity.unit.strip()):
            raise AnswerReferenceError("UNRESOLVED_CONTEXT")
    if targets and target_variants != set(query.variants):
        raise AnswerReferenceError("INVALID_REFERENCE")
    for card_id, _, _, _ in validated.raw_blocks:
        if snapshot.card(card_id).entity_id != query.entity_id:
            raise AnswerReferenceError("INVALID_REFERENCE")
    return plan


def validate_answer_plan(plan, snapshot, resolved_query, *, store_id: int) -> AnswerPlan:
    """기존 R 호출자의 호환 이름. 신규 코드는 validate_answer_for_question을 쓴다."""
    return validate_answer_for_question(plan, snapshot, resolved_query, store_id=store_id)
