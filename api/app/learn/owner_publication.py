"""R receives W completion only after the current publication/index agree."""
from app.errors import ApiError
from app.reg.hybrid import read_current_index
from app.notifications.service import create_notification_event


async def publication_evidence(conn, *, store_id, result):
    if result.status not in ('PUBLISHED', 'LINKED'):
        return {}
    # Global lock order: publication, card, then pending/context in the caller.
    await conn.fetchrow('select store_id from knowledge_publications where store_id=$1 for update', store_id)
    snapshot, _, _ = await read_current_index(conn, store_id=store_id)
    card = snapshot.card(result.card_id) if result.card_id else None
    if (card is None or (result.knowledge_revision is not None and
            result.knowledge_revision != snapshot.knowledge_revision)):
        raise ApiError(409, 'STALE_KNOWLEDGE', '지식 반영 결과의 공개판·카드를 확인해 주세요.', retryable=True)
    if result.fact_revision_id and not any(result.fact_revision_id in b.fact_revision_ids for b in card.blocks):
        raise ApiError(409, 'INVALID_REFERENCE', '반영한 사실이 승인 카드에 없습니다.')
    current = await conn.fetchrow('''select published_version_id,review_status,is_verified from knowledge_cards
        where store_id=$1 and card_id=$2 for share''', store_id, int(card.card_id))
    if (not current or current['review_status'] != 'APPROVED' or not current['is_verified']
            or current['published_version_id'] != int(card.card_version_id)):
        raise ApiError(409, 'STALE_KNOWLEDGE', '반영 카드의 승인이 변경됐습니다.', retryable=True)
    return dict(published_card_version_id=card.card_version_id, snapshot_id=snapshot.snapshot_id,
                confirmed_knowledge_revision=snapshot.knowledge_revision)


async def notify_publication(conn, *, store_id, question_id, owner_answer_id):
    recipients = await conn.fetch('''select m.user_id,min(r.session_id) as session_id
        from r_answer_receipts r join store_members m on m.store_id=r.store_id and m.member_id=r.member_id
        where r.store_id=$1 and r.pending_id=$2 group by m.user_id''', store_id, question_id)
    for recipient in recipients:
        await create_notification_event(conn, store_id=store_id, recipient_user_id=recipient['user_id'],
            event_type='OWNER_ANSWER', aggregate_type='OWNER_ANSWER', aggregate_id=owner_answer_id,
            dedupe_key=f'r-knowledge-ready:{store_id}:{owner_answer_id}:{recipient["user_id"]}',
            title='답변이 매장 지식에 반영됐어요', body='승인된 내용을 확인하고 다시 질문할 수 있어요.',
            destination=f'/staff/chat/v2?session_id={recipient["session_id"]}')
