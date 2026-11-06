"""완료 이력은 보존하되 현재 공개 여부를 매장 범위에서 별도로 읽는다."""


async def knowledge_availability(conn, *, store_id, owner_answer_ids):
    if not owner_answer_ids:
        return {}
    rows = await conn.fetch('''select k.owner_answer_id,
        case when k.status in ('PUBLISHED','LINKED') then
          case when c.card_id is null or c.review_status<>'APPROVED' or not c.is_verified
                    or c.published_version_id is null then 'UNAVAILABLE'
               when c.published_version_id::text=k.result->>'published_card_version_id' then 'CURRENT'
               else 'CHANGED' end
        when k.status='REVIEW' and not exists(
          select 1 from knowledge_change_proposals p
          where p.store_id=k.store_id and p.answer_id=k.owner_answer_id)
          then 'UNAVAILABLE'
        else 'NOT_APPLICABLE' end as availability
        from r_owner_knowledge_states k left join knowledge_cards c
          on c.store_id=k.store_id and c.card_id::text=k.result->>'card_id'
        where k.store_id=$1 and k.owner_answer_id=any($2::bigint[])''',
        store_id,list(owner_answer_ids))
    return {r['owner_answer_id']:r['availability'] for r in rows}
