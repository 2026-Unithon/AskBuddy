"""Human review -> snapshot-bound R manifest, for isolated dev evaluation only."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, StrictBool, model_validator
from app.contracts.common import Contract
from app.contracts.hashing import digest, verify_snapshot_hash
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.team.v2_evaluation import Action, EvaluationCase, EvaluationManifest


class RawEvidence(Contract):
    card_id: str = Field(min_length=1)
    card_version_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    raw_span_id: str = Field(min_length=1)


class ReviewedCase(Contract):
    meaning_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=1000)
    expected_action: Action
    must_have: StrictBool
    applicability: Literal['SPECIFIC', 'COMMON', 'NOT_APPLICABLE', 'UNDETERMINED']
    # Null and empty are deliberately different in drafts. Reviews must provide
    # explicit lists, with a reason even when no conditions or exceptions apply.
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    scope_reason: str = Field(min_length=1)
    forbidden_claims: tuple[str, ...]
    required_fact_revisions: tuple[str, ...]
    required_raw_blocks: tuple[RawEvidence, ...] = ()
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def evidence(self):
        if any(not value.strip() for value in (self.meaning_id, self.question, self.scope_reason, self.reviewer, self.reason)):
            raise ValueError('review attribution and scope evidence required')
        if len(set(self.required_fact_revisions)) != len(self.required_fact_revisions):
            raise ValueError('duplicate required revision')
        raw_keys=[(item.card_id,item.card_version_id,item.block_id,item.raw_span_id) for item in self.required_raw_blocks]
        if len(set(raw_keys))!=len(raw_keys):
            raise ValueError('duplicate required RAW block')
        if self.expected_action == 'ANSWER' and (not (self.required_fact_revisions or self.required_raw_blocks) or self.applicability == 'UNDETERMINED'):
            raise ValueError('ANSWER truth requires resolved applicability and approved evidence')
        return self


def finalize_review(review: dict, *, review_hash: str, judgments: list[dict],
                    snapshot, store_id: int, truth_version: str,
                    selected_meaning_ids: list[str] | None = None, selection_reason: str | None = None) -> dict:
    """Does not decide whether human labels are correct or publish any knowledge.

    A question suite may select source facts before evaluation. The full source
    count, selection and omissions remain visible; all selected rows require
    review. Fact must-have labels do not become R question labels automatically.
    """
    if (review.get('schema_version') != 'r_dev_review/v1' or review.get('split') != 'dev'
            or review.get('store') not in ('store-a', 'store-b')
            or review.get('source_label_status') not in ('TEAM_TEST', 'OWNER_CONFIRMED')
            or not review.get('source_reviewer') or not review.get('source_reviewed_at')):
        raise ValueError('reviewed dev source labels required')
    if review_hash != review.get('review_hash') or digest({k:v for k,v in review.items() if k!='review_hash'}) != review_hash:
        raise ValueError('stale or altered source review')
    if type(store_id) is not int or store_id <= 0 or not truth_version.strip():
        raise ValueError('explicit store and truth version required')
    snapshot = PublishedKnowledgeSnapshot.model_validate(snapshot)
    verify_snapshot_hash(snapshot)
    if snapshot.store_id != str(store_id):
        raise ValueError('snapshot store mismatch')
    rows = review['cases']
    source = {row['meaning_id']:row for row in rows}
    if not rows or len(source) != len(rows) or review['summary']['fact_count'] != len(rows):
        raise ValueError('source denominator mismatch')
    selected=list(source) if selected_meaning_ids is None else selected_meaning_ids
    if (not selected or any(not isinstance(item,str) for item in selected)
            or len(set(selected))!=len(selected) or not set(selected)<=source.keys()):
        raise ValueError('invalid question suite selection')
    if set(selected)!=source.keys() and (not isinstance(selection_reason,str) or not selection_reason.strip()):
        raise ValueError('explicit reason required for question suite selection')
    parsed = [ReviewedCase.model_validate(row) for row in judgments]
    by_id = {row.meaning_id:row for row in parsed}
    if len(by_id) != len(parsed) or set(by_id) != set(selected):
        raise ValueError('missing, duplicate or foreign reviewed question')
    facts = {fact.fact_revision_id:fact for fact in snapshot.fact_revisions}
    raw_refs={(card.card_id,card.card_version_id,block.block_id,block.raw_span_id)
              for card in snapshot.cards for block in card.blocks if block.raw_span_id}
    cases, mappings = [], []
    for original in rows:
        if original['meaning_id'] not in by_id:
            continue
        judgment = by_id[original['meaning_id']]
        required = set(judgment.required_fact_revisions)
        if not required <= facts.keys():
            raise ValueError('required revision absent from approved snapshot')
        if any(not set(facts[fid].requires) <= required for fid in required):
            raise ValueError('required evidence omits a prerequisite')
        required_raw=[item.model_dump(mode='json') for item in judgment.required_raw_blocks]
        if any((item.card_id,item.card_version_id,item.block_id,item.raw_span_id) not in raw_refs
               for item in judgment.required_raw_blocks):
            raise ValueError('required RAW reference absent from approved snapshot')
        cases.append(EvaluationCase(question_id=judgment.meaning_id, question=judgment.question,
            expected_action=judgment.expected_action, must_have=judgment.must_have,
            required_facts=tuple(sorted({facts[fid].fact_id for fid in required})),
            required_raw_blocks=tuple(required_raw),
            forbidden_claims=judgment.forbidden_claims))
        mappings.append(dict(meaning_id=judgment.meaning_id, source_fact_id=original['source_fact_id'],
            source_fact_hash=original['source_fact_hash'],
            required=[dict(fact_id=facts[fid].fact_id,fact_revision_id=fid) for fid in sorted(required)],
            required_raw_blocks=required_raw,
            judgment=judgment.model_dump(mode='json')))
    manifest = EvaluationManifest(truth_kind='HUMAN_REVIEWED', truth_version=truth_version,
        snapshot_id=snapshot.snapshot_id,knowledge_revision=snapshot.knowledge_revision,
        snapshot_hash=snapshot.snapshot_hash,cases=tuple(cases)).model_dump(mode='json')
    result = dict(schema_version='r_reviewed_manifest/v1', review_hash=review_hash,
        store=review['store'],store_id=str(store_id),source_label_status=review['source_label_status'],
        source_fact_count=len(rows),selected_meaning_ids=sorted(selected),
        omitted_meaning_ids=sorted(source.keys()-set(selected)),selection_reason=selection_reason,
        manifest=manifest, mappings=mappings, source_truth_hash=review['truth_hash'],
        source_manifest_hash=review['manifest_hash'],sources=review['sources'],
        semantic_accuracy=None,production_promotion=False)
    result['artifact_hash'] = digest(result)
    return result
