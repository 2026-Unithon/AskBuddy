"""직원 지난 대화 목록(계획 7 Task 8). 제목은 첫 질문, 마지막 시각 순. 매장·직원(member) 단위로만 읽는다."""
from __future__ import annotations

TITLE_MAX = 40


async def list_member_sessions(conn, store_id: int, member_id: int, query: str | None, limit: int = 100):
    """내 v2 대화. query 가 있으면 내가 쓴 질문에 그 말이 든 대화만."""
    return await conn.fetch(
        """
        select s.session_id,
               (select left(m.content, $4) from chat_messages m
                 where m.session_id = s.session_id and m.sender_type = 'USER'
                 order by m.message_id limit 1) as title,
               coalesce((select max(m.created_at) from chat_messages m where m.session_id = s.session_id),
                        s.started_at) as last_at
          from chat_sessions s
         where s.store_id = $1 and s.member_id = $2 and s.contract_version = 'v2'
           and ($3::text is null or exists (
                 select 1 from chat_messages m
                  where m.session_id = s.session_id and m.sender_type = 'USER'
                    and m.content ilike '%' || $3 || '%'))
         order by last_at desc, s.session_id desc
         limit $5
        """,
        store_id, member_id, query, TITLE_MAX, limit,
    )
