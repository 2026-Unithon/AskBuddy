"""사람이 지정한 안정적 의미 ID와 승인 사실 revision의 평가 전용 매핑."""
from pydantic import Field, model_validator

from app.contracts.common import Contract
from app.contracts.hashing import digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.team.retrieval_review import validate_pool


class MeaningMapping(Contract):
    meaning_id: str = Field(min_length=1)
    fact_id: str = Field(min_length=1)
    fact_revision_id: str = Field(min_length=1)


class RawMeaningMapping(Contract):
    meaning_id: str = Field(min_length=1)
    card_id: str = Field(min_length=1)
    card_version_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    raw_span_id: str = Field(min_length=1)

    def reference(self):
        return self.card_id,self.card_version_id,self.block_id


class EvidenceTruth(Contract):
    pool_hash: str
    truth_version: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    required: tuple[MeaningMapping,...] = ()
    required_raw: tuple[RawMeaningMapping,...] = ()

    @model_validator(mode='after')
    def distinct(self):
        if any(not value.strip() for value in (self.truth_version,self.reviewer,self.reason)):
            raise ValueError('truth attribution required')
        if not self.required and not self.required_raw:
            raise ValueError('nonempty required evidence')
        for key in ('meaning_id','fact_id','fact_revision_id'):
            values=[getattr(row,key) for row in self.required]
            if any(not value.strip() for value in values) or len(set(values))!=len(values):
                raise ValueError('duplicate or empty meaning mapping')
        meanings=[item.meaning_id for item in (*self.required,*self.required_raw)]
        if any(not value.strip() for value in meanings) or len(set(meanings))!=len(meanings):
            raise ValueError('duplicate or empty cross-kind meaning mapping')
        refs=[item.reference() for item in self.required_raw]
        if len(set(refs))!=len(refs):
            raise ValueError('duplicate required RAW reference')
        return self


def resolve_evidence(pool, truth):
    validate_pool(pool)
    truth=EvidenceTruth.model_validate(truth)
    if truth.pool_hash!=pool['pool_hash']: raise ValueError('truth belongs to another pool')
    snapshot=PublishedKnowledgeSnapshot.model_validate(pool['snapshot'])
    facts={fact.fact_revision_id:fact for fact in snapshot.fact_revisions}
    for item in truth.required:
        if item.fact_revision_id not in facts or facts[item.fact_revision_id].fact_id!=item.fact_id:
            raise ValueError('stable fact/revision mismatch')
    needed=set()
    def visit(fid):
        if fid not in needed:
            needed.add(fid)
            for dep in facts[fid].requires: visit(dep)
    for item in truth.required: visit(item.fact_revision_id)
    blocks={(c.card_id,c.card_version_id,b.block_id):set(b.fact_revision_ids)
        for c in snapshot.cards for b in c.blocks}
    eligible=set(tuple(r) for r in pool.get('eligible_references',blocks))
    blocks={key:value for key,value in blocks.items() if key in eligible}
    raw_blocks={(c.card_id,c.card_version_id,b.block_id):b.raw_span_id
                for c in snapshot.cards for b in c.blocks if b.raw_span_id}
    for item in truth.required_raw:
        if item.reference() not in blocks or raw_blocks.get(item.reference())!=item.raw_span_id:
            raise ValueError('required RAW evidence is not currently eligible')
    covered=set().union(*blocks.values()) if blocks else set()
    if not needed<=covered: raise ValueError('required evidence is not currently eligible')
    return snapshot,truth,needed,blocks


def evidence_recall(pool,truth,ranked_references,*,k=10):
    snapshot,truth,needed,blocks=resolve_evidence(pool,truth)
    if type(k) is not int or k<1: raise ValueError('positive integer k required')
    refs=[]
    for ref in ranked_references:
        if not isinstance(ref,(list,tuple)) or len(ref)!=3 or any(not isinstance(v,str) for v in ref):
            raise ValueError('exact ranked reference required')
        refs.append(tuple(ref))
    if len(refs)!=len(set(refs)) or not set(refs)<=set(blocks): raise ValueError('foreign/duplicate rank')
    found=set().union(*(blocks[ref] for ref in refs[:k])) if refs else set()
    raw_needed={item.reference() for item in truth.required_raw}
    raw_found=raw_needed&set(refs[:k])
    result=dict(schema_version='r_evidence_recall/v2',pool_hash=pool['pool_hash'],
        truth=truth.model_dump(mode='json'),truth_hash=digest(truth.model_dump(mode='json')),k=k,
        required_fact_revision_ids=sorted(needed),missing_fact_revision_ids=sorted(needed-found),
        fact_recall_at_k=len(needed&found)/len(needed) if needed else None,
        raw_recall_at_k=len(raw_found)/len(raw_needed) if raw_needed else None,
        complete_evidence_at_k=needed<=found and raw_needed<=set(refs[:k]),
        missing_raw_references=[list(ref) for ref in sorted(raw_needed-raw_found)],
        meaning_coverage={**{item.meaning_id:item.fact_revision_id in found for item in truth.required},
            **{item.meaning_id:item.reference() in raw_found for item in truth.required_raw}},
        # 승인 사실의 조건/예외는 블록과 함께 검토한다. 텍스트 적합성 자동 승인 아님.
        required_fact_details=[snapshot.fact(fid).model_dump(mode='json') for fid in sorted(needed)],
        required_raw_details=[dict(mapping=item.model_dump(mode='json'),
            span=next(span for span in snapshot.raw_spans if span.raw_span_id==item.raw_span_id).model_dump(mode='json'))
            for item in truth.required_raw],
        production_promotion=False)
    return result
