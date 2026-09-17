"""불변 pool에 연결된 사람 관련성 판정과 보수적인 검색 지표. 제품 허가는 아니다."""
import math
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.common import Contract
from app.contracts.hashing import digest
from app.team.retrieval_pool import build_retrieval_pool

Reference = tuple[str, str, str]


class RelevanceJudgment(Contract):
    pool_hash: str
    reference: Reference
    relevance: Literal['RELEVANT', 'IRRELEVANT', 'UNDETERMINED']
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def evidence(self):
        if not self.reviewer.strip() or not self.reason.strip():
            raise ValueError('review attribution and reason required')
        return self


def validate_pool(pool):
    if pool.get('pool_hash') != digest({k:v for k,v in pool.items() if k!='pool_hash'}):
        raise ValueError('pool hash mismatch')
    args = {k:pool[k] for k in ('snapshot','question_id','question','channels')}
    args.update(sample_size=pool['sampling']['requested'],seed=pool['sampling']['seed'])
    if 'eligible_references' in pool: args['eligible_references']=pool['eligible_references']
    rebuilt = build_retrieval_pool(**args)
    if rebuilt != pool: raise ValueError('pool structure or original review fields changed')
    return rebuilt


def review_retrieval(pool, judgments, *, rankings=None, k=10):
    """전체 모집단을 검토하지 않았다면 recall/MRR/nDCG 확정값을 만들지 않는다."""
    validate_pool(pool)
    if type(k) is not int or k<1: raise ValueError('positive integer k required')
    entries = {tuple(row['reference']):row for row in pool['entries']}
    labels = {}
    for raw in judgments:
        label = RelevanceJudgment.model_validate(raw)
        if label.pool_hash != pool['pool_hash']: raise ValueError('foreign/stale pool judgment')
        if label.reference not in entries or label.reference in labels:
            raise ValueError('foreign or duplicate reference judgment')
        labels[label.reference] = label
    universe = set(tuple(r) for r in pool.get('eligible_references', [])) if 'eligible_references' in pool else {
        (c['card_id'],c['card_version_id'],b['block_id']) for c in pool['snapshot']['cards'] for b in c['blocks']}
    known = {ref:label.relevance=='RELEVANT' for ref,label in labels.items() if label.relevance!='UNDETERMINED'}
    relevant = {ref for ref,value in known.items() if value}
    complete = set(known)==universe
    rankings = pool['channels'] if rankings is None else rankings
    if not isinstance(rankings,dict) or not rankings: raise ValueError('rankings required')
    metrics = {}
    for name,raw_refs in rankings.items():
        if not isinstance(name,str) or not name.strip() or not isinstance(raw_refs,(list,tuple)):
            raise ValueError('named ranked reference lists required')
        refs=[]
        for ref in raw_refs:
            if not isinstance(ref,(list,tuple)) or len(ref)!=3 or any(not isinstance(x,str) for x in ref):
                raise ValueError('invalid ranked reference')
            refs.append(tuple(ref))
        if len(set(refs))!=len(refs) or not set(refs)<=universe: raise ValueError('foreign/duplicate ranked reference')
        top=refs[:k]
        top_known=all(ref in known for ref in top)
        hits=sum(ref in relevant for ref in top)
        dcg=sum(1/math.log2(i+2) for i,ref in enumerate(top) if ref in relevant)
        ideal=sum(1/math.log2(i+2) for i in range(min(k,len(relevant))))
        first=next((i for i,ref in enumerate(refs,1) if ref in relevant),None)
        metrics[name]=dict(retrieved_count=len(refs),k=k,
            precision_at_k=hits/k if top_known else None,
            recall_at_k=hits/len(relevant) if complete and relevant else None,
            mrr=1/first if complete and relevant and first else 0.0 if complete and relevant else None,
            ndcg_at_k=dcg/ideal if complete and ideal else None,
            unjudged_at_k=sum(ref not in known for ref in top))
    result=dict(schema_version='r_retrieval_review/v1',pool_hash=pool['pool_hash'],
        judgments=[labels[ref].model_dump(mode='json') for ref in sorted(labels)],
        universe_count=len(universe),judged_count=len(known),unjudged_count=len(universe-set(known)),
        relevant_count=len(relevant),relevance_complete=complete,metrics=metrics,
        rankings=rankings,k=k,production_promotion=False)
    return dict(result,review_hash=digest(result))
