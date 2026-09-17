"""Offline pending-group evaluation with fixed pairs and explicit unknowns."""
from itertools import combinations
from pathlib import Path
from pydantic import Field, StrictBool, model_validator
from app.contracts.common import Contract
from app.contracts.hashing import digest


class GroupCase(Contract):
    question_id: str = Field(min_length=1)
    store_id: str = Field(pattern=r'^[1-9][0-9]*$')
    snapshot_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    question: str = Field(min_length=1,max_length=1000)
    confirmed_context: dict

    @model_validator(mode='after')
    def nonempty(self):
        if not self.question_id.strip() or not self.question.strip():
            raise ValueError('nonempty question ID and text required')
        return self


class PairJudgment(Contract):
    left: str
    right: str
    pair_hash: str
    should_share_pending: StrictBool
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def evidence(self):
        if self.left==self.right or not self.reviewer.strip() or not self.reason.strip():
            raise ValueError('distinct questions and review evidence required')
        return self


def pair_hash(left, right):
    rows=[GroupCase.model_validate(row).model_dump(mode='json') for row in (left,right)]
    if rows[0]['question_id']==rows[1]['question_id']:
        raise ValueError('distinct questions required')
    return digest(sorted(rows,key=lambda row:row['question_id']))


def evaluate_grouping(cases, assignments, judgments):
    rows=[GroupCase.model_validate(row) for row in cases]
    by_id={row.question_id:row for row in rows}
    if not 1<=len(rows)<=200 or len(rows)!=len(by_id):
        raise ValueError('1..200 distinct questions required')
    if set(assignments)!=set(by_id) or any(value is not None and
            (not isinstance(value,str) or not value.strip()) for value in assignments.values()):
        raise ValueError('every question needs a group ID or explicit abstention')
    labels={}
    for raw in judgments:
        item=PairJudgment.model_validate(raw)
        key=tuple(sorted((item.left,item.right)))
        if not set(key)<=by_id.keys() or key in labels:
            raise ValueError('foreign or duplicate reviewed pair')
        a,b=(by_id[qid] for qid in key)
        if item.pair_hash!=pair_hash(a,b):
            raise ValueError('stale question/context pair review')
        if item.should_share_pending and (a.store_id,a.snapshot_hash)!=(b.store_id,b.snapshot_hash):
            raise ValueError('review cannot authorize cross-store or cross-snapshot grouping')
        labels[key]=item
    pair_rows=[]
    tp=fp=fn=tn=unjudged_merged=violations=abstained=0
    for left,right in combinations(sorted(by_id),2):
        a,b=by_id[left],by_id[right]
        abstain=assignments[left] is None or assignments[right] is None
        merged=not abstain and assignments[left]==assignments[right]
        violation=merged and (a.store_id,a.snapshot_hash)!=(b.store_id,b.snapshot_hash)
        label=labels.get((left,right))
        expected=label.should_share_pending if label else None
        if expected is True:
            tp+=int(merged);fn+=int(not merged)
        elif expected is False:
            fp+=int(merged);tn+=int(not merged)
        elif merged:
            unjudged_merged+=1
        abstained+=int(abstain)
        violations+=int(violation)
        pair_rows.append(dict(left=left,right=right,merged=merged,abstained=abstain,
            should_share_pending=expected,scope_violation=violation,
            pair_hash=pair_hash(a,b)))
    all_reviewed=len(labels)==len(pair_rows)
    result=dict(schema_version='r_grouping_evaluation/v1',question_count=len(rows),pair_count=len(pair_rows),
        reviewed_pair_count=len(labels),unjudged_pair_count=len(pair_rows)-len(labels),
        true_merge=tp,false_merge=fp,false_split_or_abstention=fn,true_separation_or_abstention=tn,
        abstained_pair_count=abstained,unjudged_merged_pairs=unjudged_merged,scope_violations=violations,
        # Missing labels are never silently scored as different meanings.
        precision=tp/(tp+fp) if tp+fp and not unjudged_merged else None,
        recall=tp/(tp+fn) if all_reviewed and tp+fn else None,
        cases=[row.model_dump(mode='json') for row in rows],assignments=assignments,
        judgments=[item.model_dump(mode='json') for _,item in sorted(labels.items())],pairs=pair_rows,
        evaluator_source_hash=digest(Path(__file__).read_text(encoding='utf-8')),
        production_promotion=False)
    result['report_hash']=digest(result)
    return result
