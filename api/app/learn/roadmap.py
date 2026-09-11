from __future__ import annotations

import asyncpg


def learning_status(progress_status: str | None, completed_version_id, current_version_id) -> str:
    """레거시 잠금 상태는 미시작으로, 완료한 구버전은 재확인으로 해석한다."""
    if completed_version_id is not None:
        if int(completed_version_id) == int(current_version_id):
            return "DONE"
        return "RECONFIRM_REQUIRED"
    if progress_status == "DONE":
        # 버전 없는 레거시 DONE은 현재 버전 완료로 백필된 뒤에만 DONE이다.
        return "NOT_STARTED"
    return "NOT_STARTED"


async def roadmap_rows(conn: asyncpg.Connection, store_id: int, member_id: int):
    return await conn.fetch(
        """
        select s.store_name, c.category_id, c.category_name, c.sort_order,
               i.item_id, k.card_id, k.published_version_id,
               v.title, p.status as progress_status, p.completed_version_id
        from knowledge_cards k
        join card_versions v
          on v.store_id = k.store_id and v.version_id = k.published_version_id
        join task_categories c
          on c.store_id = k.store_id and c.category_id = k.category_id
        join stores s on s.store_id = k.store_id
        join roadmap_items i
          on i.card_id = k.card_id and i.category_id = k.category_id
         and i.published_version_id = k.published_version_id and i.is_active = true
        join roadmap_stages g
          on g.stage_id = i.stage_id and g.store_id = k.store_id
         and g.category_id = k.category_id and g.is_active = true
        left join learning_progress p
          on p.item_id = i.item_id and p.member_id = $2
        where k.store_id = $1 and k.review_status = 'APPROVED'
        order by c.sort_order, c.category_id, i.item_order, i.item_id
        """,
        store_id,
        member_id,
    )


async def item_row(
    conn: asyncpg.Connection, store_id: int, member_id: int, item_id: int
):
    return await conn.fetchrow(
        """
        select i.item_id, k.card_id, k.published_version_id,
               v.title, v.content, c.category_id, c.category_name,
               p.status as progress_status, p.completed_version_id
        from roadmap_items i
        join roadmap_stages g
          on g.stage_id = i.stage_id and g.store_id = $1 and g.is_active = true
        join knowledge_cards k
          on k.store_id = g.store_id and k.card_id = i.card_id
         and k.review_status = 'APPROVED'
         and k.published_version_id = i.published_version_id
        join card_versions v
          on v.store_id = k.store_id and v.version_id = k.published_version_id
        join task_categories c
          on c.store_id = k.store_id and c.category_id = k.category_id
        left join learning_progress p
          on p.item_id = i.item_id and p.member_id = $2
        where i.item_id = $3 and i.is_active = true
        """,
        store_id,
        member_id,
        item_id,
    )


async def set_completion(
    conn: asyncpg.Connection,
    store_id: int,
    member_id: int,
    item_id: int,
    *,
    published_version_id: int,
    completed: bool,
):
    item = await conn.fetchrow(
        """
        select i.item_id, i.card_id, i.published_version_id,
               p.completed_version_id
        from roadmap_items i
        join roadmap_stages g
          on g.stage_id = i.stage_id and g.store_id = $1 and g.is_active = true
        join knowledge_cards k
          on k.store_id = g.store_id and k.card_id = i.card_id
         and k.review_status = 'APPROVED'
         and k.published_version_id = i.published_version_id
        left join learning_progress p
          on p.item_id = i.item_id and p.member_id = $2
        where i.item_id = $3 and i.is_active = true
        for update of i
        """,
        store_id,
        member_id,
        item_id,
    )
    if item is None:
        return None
    current_version_id = int(item["published_version_id"])
    if current_version_id != published_version_id:
        return item
    reconfirming = (
        completed
        and item["completed_version_id"] is not None
        and int(item["completed_version_id"]) != current_version_id
    )
    await conn.execute(
        """
        insert into learning_progress (
          member_id, item_id, status, completed_at, completed_version_id, reconfirmed_at
        ) values (
          $1, $2, $3::varchar,
          case when $4::boolean then now() else null end,
          case when $4::boolean then $5::bigint else null end,
          case when $6::boolean then now() else null end
        )
        on conflict (member_id, item_id) do update set
          status = excluded.status,
          completed_at = excluded.completed_at,
          completed_version_id = excluded.completed_version_id,
          reconfirmed_at = case
            when $6 then now() else learning_progress.reconfirmed_at
          end
        """,
        member_id,
        item_id,
        "DONE" if completed else "NOT_STARTED",
        completed,
        current_version_id,
        reconfirming,
    )
    return item


async def counts(conn: asyncpg.Connection, store_id: int, member_id: int) -> dict[str, int]:
    row = await conn.fetchrow(
        """
        select count(*)::int as total,
               count(*) filter (
                 where p.completed_version_id = i.published_version_id
               )::int as done,
               count(*) filter (
                 where p.completed_version_id is not null
                   and p.completed_version_id <> i.published_version_id
               )::int as reconfirm_required
        from roadmap_items i
        join roadmap_stages g
          on g.stage_id = i.stage_id and g.store_id = $1 and g.is_active = true
        join knowledge_cards k
          on k.store_id = g.store_id and k.card_id = i.card_id
         and k.review_status = 'APPROVED'
         and k.published_version_id = i.published_version_id
        left join learning_progress p
          on p.item_id = i.item_id and p.member_id = $2
        where i.is_active = true
        """,
        store_id,
        member_id,
    )
    return {
        "total": int(row["total"]),
        "done": int(row["done"]),
        "reconfirm_required": int(row["reconfirm_required"]),
    }


async def update_member_rate(
    conn: asyncpg.Connection, store_id: int, member_id: int, summary: dict[str, int]
) -> float:
    total = summary["total"]
    rate = round(summary["done"] / total * 100, 2) if total else 0.0
    await conn.execute(
        """
        update store_members m
        set progress_rate = $3::numeric,
            is_deployable = $3::numeric >= (
              select deploy_threshold from stores where store_id = $2
            )
        where m.member_id = $1 and m.store_id = $2
        """,
        member_id,
        store_id,
        rate,
    )
    return rate
