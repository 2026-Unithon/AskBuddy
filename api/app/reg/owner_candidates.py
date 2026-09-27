"""점주 답변 비교 후보: 활성 공개 블록 색인을 카드 단위로 회수한다."""
import math

from app.errors import ApiError
from app.reg.embeddings import vector_literal
from app.reg.hybrid import read_current_index
from app.reg.index_audit import audit_index_universe
from app.reg.index_preparation import INDEX_CONFIG_VERSION


async def published_owner_candidates(db, *, store_id: int, query_vector: list[float],
                                     embedding_model: str, top_k: int) -> list[dict]:
    if (type(top_k) is not int or not 1 <= top_k <= 100 or len(query_vector) != 1536
            or not any(query_vector)
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in query_vector)):
        raise ValueError('invalid owner candidate vector or limit')
    # 임베딩은 호출 전에 끝났다. 포인터·문서·카드 본문을 같은 판에서 읽는다.
    async with db.transaction(isolation='repeatable_read', readonly=True):
        snapshot, pid, _ = await read_current_index(db, store_id=store_id)
        metadata = await db.fetchrow('''select embedding_model,index_config_version
            from r_index_preparations where store_id=$1 and prepared_id=$2''', store_id, pid)
        if (metadata is None or metadata['embedding_model'] != embedding_model
                or metadata['index_config_version'] != INDEX_CONFIG_VERSION):
            raise ApiError(503, 'INDEX_UNAVAILABLE', '공개 색인 모델·설정을 확인해 주세요.', retryable=True)
        refs = await db.fetch('''select card_id,card_version_id,block_id from r_index_documents
            where store_id=$1 and prepared_id=$2''', store_id, pid)
        audit = audit_index_universe(snapshot, tuple(
            (str(r['card_id']), str(r['card_version_id']), r['block_id']) for r in refs))
        if not audit['complete']:
            raise ApiError(503, 'INDEX_UNAVAILABLE', '공개 색인의 승인 블록이 일치하지 않습니다.', retryable=True)
        rows = await db.fetch('''
            with ranked as (
                select d.card_id,d.card_version_id,max(1-(d.embedding <=> $3::vector)) as score
                from r_index_documents d join knowledge_cards c
                  on c.store_id=d.store_id and c.card_id=d.card_id
                  and c.published_version_id=d.card_version_id
                  and c.review_status='APPROVED' and c.is_verified=true
                where d.store_id=$1 and d.prepared_id=$2
                group by d.card_id,d.card_version_id
                order by score desc,d.card_id limit $4
            )
            select r.card_id as id,v.title,v.content,r.score,r.card_version_id as version_id,
                   c.category_id,c.assignment_type,coalesce(tc.category_name,'') as category_name
            from ranked r join knowledge_cards c on c.store_id=$1 and c.card_id=r.card_id
            join card_versions v on v.store_id=c.store_id and v.card_id=c.card_id
              and v.version_id=r.card_version_id
            left join task_categories tc on tc.store_id=c.store_id and tc.category_id=c.category_id
            order by r.score desc,r.card_id
            ''', store_id, pid, vector_literal(query_vector), top_k)
        return [dict(row) for row in rows]
