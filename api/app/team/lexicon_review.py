"""수집한 공개 용어/매장 별칭을 승인 전 검토 묶음으로 정리한다. 검색에 쓰지 않는다."""
from app.contracts.hashing import digest
from app.reg.lexicon import LexiconEntry, validated_entries


def prepare_lexicon_review(entries, *, collection_reference):
    if not isinstance(collection_reference,str) or not collection_reference.strip():
        raise ValueError('collection reference required')
    if not isinstance(entries,list) or len(entries)>500:
        raise ValueError('bounded term input required')
    unique={}
    for raw in entries:
        entry=LexiconEntry.model_validate(raw)
        payload=entry.model_dump(mode='json')
        unique[digest(payload)]=entry
    ordered=validated_entries(tuple(unique.values()))
    result=dict(schema_version='r_lexicon_review/v1',collection_reference=collection_reference,
        input_count=len(entries),unique_count=len(ordered),
        entries=[e.model_dump(mode='json') for e in ordered],status='REVIEW_REQUIRED',
        approval_version=None,production_promotion=False)
    return dict(result,review_hash=digest(result))
