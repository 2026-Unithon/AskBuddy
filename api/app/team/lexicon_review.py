"""수집한 공개 용어/매장 별칭을 승인 전 검토 묶음으로 정리한다. 검색에 쓰지 않는다."""
from app.contracts.hashing import digest
from app.reg.lexicon import LexiconEntry, validated_entries
from pathlib import Path
import json


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


def collect_lexicon_review(directory, entries, *, collection_reference):
    """Immutable local imports, content-addressed deduplication; no inferred variants.

    Keep this directory within the corresponding private store directory. Reimporting
    an identical collection is idempotent; an edited artifact is never overwritten.
    """
    review = prepare_lexicon_review(entries, collection_reference=collection_reference)
    root = Path(directory).resolve(strict=True)
    target = root / ('lexicon-' + review['review_hash'].split(':')[1] + '.json')
    if target.resolve().parent != root:
        raise ValueError('redirected collection artifact')
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8')) != review:
            raise ValueError('existing collection changed')
    else:
        with target.open('x', encoding='utf-8') as stream:
            json.dump(review, stream, ensure_ascii=False, indent=2)
    return review


async def approve_lexicon_review(pool, *, store_id, member_id, review, expected_hash):
    """Trusted owner administration only. Existing DB approval enforces owner membership."""
    from app.reg.lexicon import approve_lexicon
    payload = {k: v for k, v in review.items() if k != 'review_hash'}
    if expected_hash != review.get('review_hash') or expected_hash != digest(payload):
        raise ValueError('review content changed')
    rebuilt = prepare_lexicon_review(review['entries'], collection_reference=review['collection_reference'])
    # Input count retains original duplicate observations, so compare invariant fields.
    for key in ('schema_version', 'entries', 'unique_count', 'status', 'approval_version', 'production_promotion'):
        if rebuilt[key] != review[key]:
            raise ValueError('invalid approval package')
    return await approve_lexicon(pool, store_id=store_id, member_id=member_id,
        entries=tuple(LexiconEntry.model_validate(e) for e in review['entries']))
