"""평가 환경에서 제품과 동일한 SQL의 독립 검색 결과를 고정한다."""
from pathlib import Path

from app.contracts.hashing import digest
from app.reg import hybrid
from app.reg import index_audit
from app.team.retrieval_pool import build_retrieval_pool


async def collect_retrieval_pool(pool, *, store_id: int, question_id: str, question: str,
                                 query_vector: list[float], embedding_metadata: dict,
                                 expected_snapshot: dict, oracle: list, sample_size: int,
                                 seed: str, channel_limit: int = 20):
    """호출자는 격리 DB와 이미 계측한 query embedding을 제공한다. 모델 호출 없음.

    expected_snapshot은 oracle/질문이 속한 승인판이다. 공개가 바뀌면 이전 oracle을
    새 판에 옮기지 않는다. embedding metadata는 호출자 선언이며 실제 공급자 증명이 아니다.
    """
    if set(expected_snapshot) != {'snapshot_id', 'knowledge_revision', 'snapshot_hash'}:
        raise ValueError('exact expected snapshot identity required')
    if (set(embedding_metadata) != {'provider', 'model', 'mode', 'reference'}
            or any(not isinstance(v, str) or not v.strip() for v in embedding_metadata.values())
            or embedding_metadata['mode'] not in ('SYNTHETIC', 'LIVE')):
        raise ValueError('embedding provider/model/mode/reference required')
    source_hashes = {str(path.relative_to(Path(__file__).resolve().parents[1])):
        digest(path.read_text(encoding='utf-8')) for path in
        (Path(__file__), Path(hybrid.__file__), Path(index_audit.__file__), Path(__file__).with_name('retrieval_pool.py'))}
    result = await hybrid.search_channels(pool,store_id=store_id,question=question,
        query_vector=query_vector,channel_limit=channel_limit,include_universe=True)
    actual = {key: getattr(result.snapshot,key) for key in expected_snapshot}
    if actual != expected_snapshot:
        raise ValueError('snapshot changed: recollect oracle and question mapping')
    if result.eligible_references is None:
        raise ValueError('current approved universe required')
    if result.universe_audit is None or not result.universe_audit['complete']:
        raise ValueError('complete snapshot/index audit required')
    def refs(rows):
        return [[str(r['card_id']),str(r['card_version_id']),r['block_id']] for r in rows]
    review = build_retrieval_pool(snapshot=result.snapshot,question_id=question_id,question=question,
        channels=dict(lexical=refs(result.lexical),vector=refs(result.vector),oracle=oracle),
        sample_size=sample_size,seed=seed,eligible_references=result.eligible_references)
    payload = dict(schema_version='r_retrieval_collection/v1',store_id=str(store_id),
        snapshot=actual,index_revision=result.index_revision,channel_limit=channel_limit,
        normalized_query=result.normalized_query,alias_terms=list(result.alias_terms),
        normalization_version=hybrid.NORMALIZATION_VERSION,lexical_version=hybrid.LEXICAL_QUERY_VERSION,
        query_vector_hash=digest(query_vector),embedding_metadata=dict(embedding_metadata),
        source_hashes=source_hashes,lexical=list(result.lexical),vector=list(result.vector),
        universe_audit=result.universe_audit,
        review_pool=review,production_promotion=False)
    return dict(payload,collection_hash=digest(payload))
