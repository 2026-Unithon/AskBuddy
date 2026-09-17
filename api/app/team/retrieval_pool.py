"""격리 평가용 검토 후보. 검색/oracle 포함 여부는 정답 판정이 아니다."""
from app.contracts.hashing import digest, verify_snapshot_hash
from app.contracts.snapshot import PublishedKnowledgeSnapshot


def build_retrieval_pool(*, snapshot, question_id, question, channels,
                         sample_size, seed, eligible_references=None):
    """같은 승인판의 채널 합집합과 미회수 표본을 만든다.

    channels는 lexical/vector/oracle 각각 순서 있는 [card, version, block] 목록.
    oracle은 외부에서 찾은 후보일 뿐 자동 positive가 아니다. 표본은 hash 순서로
    재현하며 통계적 전수 정답/recall을 추정하지 않는다. 런타임 검색에 주입하지 않는다.
    """
    snapshot = PublishedKnowledgeSnapshot.model_validate(snapshot)
    verify_snapshot_hash(snapshot)
    if any(not isinstance(v, str) or not v.strip() for v in (question_id, question, seed)):
        raise ValueError('question and sampling seed required')
    if type(sample_size) is not int or sample_size < 0:
        raise ValueError('sample_size must be a nonnegative integer')
    if not isinstance(channels, dict) or set(channels) != {'lexical', 'vector', 'oracle'}:
        raise ValueError('all three candidate channels required, empty lists allowed')
    universe = {}
    for card in snapshot.cards:
        for block in card.blocks:
            key = (card.card_id, card.card_version_id, block.block_id)
            universe[key] = dict(reference=list(key), title=card.title,
                block=block.model_dump(mode='json'))
    if eligible_references is not None:
        if not isinstance(eligible_references, (list, tuple)):
            raise ValueError('eligible references must be a sequence')
        allowed = set()
        for ref in eligible_references:
            if (not isinstance(ref, (list, tuple)) or len(ref) != 3
                    or any(not isinstance(v, str) for v in ref)):
                raise ValueError('invalid eligible reference')
            key = tuple(ref)
            if key not in universe or key in allowed:
                raise ValueError('foreign or duplicate eligible reference')
            allowed.add(key)
        universe = {key: value for key, value in universe.items() if key in allowed}
    ranks = {}
    for channel in ('lexical', 'vector', 'oracle'):
        if not isinstance(channels[channel], (list, tuple)):
            raise ValueError('ranked channel must be a sequence')
        seen = set()
        for rank, ref in enumerate(channels[channel], 1):
            if (not isinstance(ref, (list, tuple)) or len(ref) != 3
                    or any(not isinstance(v, str) for v in ref)):
                raise ValueError('exact card/version/block reference required')
            key = tuple(ref)
            if key not in universe or key in seen:
                raise ValueError('foreign or duplicate channel reference')
            seen.add(key)
            ranks.setdefault(key, {})[channel] = rank
    remaining = set(universe) - set(ranks)
    sampled = sorted(remaining, key=lambda key: (digest(dict(seed=seed,
        snapshot_hash=snapshot.snapshot_hash, question_id=question_id, reference=key)), key))[:sample_size]
    entries = []
    for key in sorted(set(ranks) | set(sampled)):
        entry = dict(universe[key], channel_ranks=ranks.get(key, {}),
            unpooled_sample=key in sampled, relevance=None, reviewer=None, reason=None)
        entries.append(entry)
    result = dict(schema_version='r_retrieval_pool/v1', question_id=question_id,
        question=question, snapshot=snapshot.model_dump(mode='json'),
        channels=channels, sampling=dict(seed=seed, requested=sample_size,
            available=len(remaining), selected=len(sampled), method='sha256-order/v1'),
        universe_size=len(universe), pooled_size=len(ranks), entries=entries,
        unreviewed_outside_pool=len(remaining)-len(sampled),
        truth_status='UNREVIEWED', production_promotion=False)
    if eligible_references is not None:
        result['eligible_references'] = [list(key) for key in sorted(universe)]
    return dict(result, pool_hash=digest(result))
