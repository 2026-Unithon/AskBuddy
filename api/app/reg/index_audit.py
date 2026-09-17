"""색인에서 발견한 목록과 독립적으로 승인 snapshot의 전체 블록을 대조한다."""
from collections import Counter

from app.contracts.hashing import digest, verify_snapshot_hash


def audit_index_universe(snapshot, indexed_references):
    verify_snapshot_hash(snapshot)
    expected = {(c.card_id,c.card_version_id,b.block_id)
                for c in snapshot.cards for b in c.blocks}
    references = []
    for ref in indexed_references:
        if (not isinstance(ref,(list,tuple)) or len(ref)!=3
                or any(not isinstance(v,str) or not v for v in ref)):
            raise ValueError('exact string card/version/block reference required')
        references.append(tuple(ref))
    counts = Counter(references)
    actual = set(counts)
    missing = sorted(expected-actual)
    unexpected = sorted(actual-expected)
    duplicates = sorted(key for key,count in counts.items() if count>1)
    report = dict(schema_version='r_index_universe_audit/v1',
        snapshot_id=snapshot.snapshot_id,snapshot_hash=snapshot.snapshot_hash,
        expected_count=len(expected),indexed_count=len(references),
        missing=[list(r) for r in missing],unexpected=[list(r) for r in unexpected],
        duplicates=[dict(reference=list(r),count=counts[r]) for r in duplicates],
        complete=not (missing or unexpected or duplicates))
    return dict(report,audit_hash=digest(report))


class IndexUniverseMismatch(ValueError):
    def __init__(self, audit):
        self.audit = audit
        super().__init__('approved snapshot and index universe differ')
