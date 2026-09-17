"""점주만 현재 승인 지식을 내보낸다. 응답 생성과 EXPORT 감사 기록은 같은 읽기 판이다."""
from app.learn.owner_delivery import require_owner
from app.reg.hybrid import read_current_index


async def export_approved_knowledge(pool, *, store_id: int, member_id: int):
    async with pool.acquire() as conn:
        async with conn.transaction(isolation='repeatable_read'):
            user_id=await require_owner(conn,store_id=store_id,member_id=member_id)
            snapshot,_,index_revision=await read_current_index(conn,store_id=store_id)
            rows=await conn.fetch("""select card_id,published_version_id from knowledge_cards
                where store_id=$1 and review_status='APPROVED' and is_verified=true""",store_id)
            current={(str(r['card_id']),str(r['published_version_id'])) for r in rows}
            cards=[c for c in snapshot.cards if (c.card_id,c.card_version_id) in current]
            fact_ids={fid for c in cards for b in c.blocks for fid in b.fact_revision_ids}
            raw_ids={b.raw_span_id for c in cards for b in c.blocks if b.raw_span_id}
            payload=dict(schema_version='r_owner_knowledge_export/v1',store_id=str(store_id),
                source_snapshot_id=snapshot.snapshot_id,source_snapshot_hash=snapshot.snapshot_hash,
                knowledge_revision=snapshot.knowledge_revision,index_revision=index_revision,
                scope='CURRENT_APPROVED_CARDS_AT_TRANSACTION',
                cards=[c.model_dump(mode='json') for c in cards],
                fact_revisions=[f.model_dump(mode='json') for f in snapshot.fact_revisions if f.fact_revision_id in fact_ids],
                raw_spans=[r.model_dump(mode='json') for r in snapshot.raw_spans if r.raw_span_id in raw_ids])
            # 일부 카드 제외 후 payload를 완전한 PublishedKnowledgeSnapshot으로 표시하지 않는다.
            await conn.execute("insert into access_logs(store_id,user_id,action_type) values($1,$2,'EXPORT')",store_id,user_id)
    return payload
