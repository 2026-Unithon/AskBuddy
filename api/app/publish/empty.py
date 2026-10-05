"""Persist a real empty initial publication so the first question can be escalated."""
from app.contracts.usage import UsageContext
from app.errors import ApiError
from app.publish.approval import publish_cards


async def ensure_initial_publication(pool, *, store_id: int, member_id: int, user_id: int):
    async with pool.acquire() as conn:
        exists = await conn.fetchval('''select exists(select 1 from knowledge_publications
            where store_id=$1 and current_snapshot_id is not null)
            or exists(select 1 from knowledge_cards where store_id=$1
                and review_status='APPROVED' and published_version_id is not null)''', store_id)
    if exists:
        return
    result = await publish_cards(pool, store_id=store_id, member_id=member_id,
        actor_user_id=user_id, changes=[], idempotency_key='r-initial-empty', initialize_empty=True,
        usage_context=UsageContext(store_id=str(store_id), stage='EMBED', cost_phase='OPERATING',
            cost_purpose='PRODUCT', operation_id='initial-empty', logical_call_id='initial-empty'))
    if result.status not in ('PUBLISHED', 'ALREADY_APPLIED', 'STALE'):
        raise ApiError(503, 'INDEX_UNAVAILABLE', '빈 공개 지식을 준비하지 못했습니다.', retryable=True)
