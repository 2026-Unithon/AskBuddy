from __future__ import annotations

import json

import asyncpg


def _status_clause(review_status: str | None, staff: bool) -> tuple[str, list[str]]:
    if staff:
        return "and k.review_status = 'APPROVED'", []
    if review_status in (None, "pending"):
        return "and k.review_status = 'PENDING'", []
    if review_status == "needs_review":
        return (
            "and (k.review_status = 'NEEDS_REVIEW' or k.needs_review_reason is not null)",
            [],
        )
    if review_status == "all":
        return "", []
    return "and k.review_status = $STATUS", [review_status.upper()]


async def list_cards(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    review_status: str,
    job_id: int | None,
    category_id: int | None,
    query: str | None,
    cursor: int | None,
    limit: int,
    staff: bool,
):
    status_sql, status_args = _status_clause(review_status, staff)
    args: list[object] = [store_id]
    if status_args:
        args.extend(status_args)
        status_sql = status_sql.replace("$STATUS", f"${len(args)}")
    filters = [status_sql]
    if job_id is not None:
        args.append(job_id)
        filters.append(f"and k.origin_job_id = ${len(args)}")
    if category_id is not None:
        args.append(category_id)
        filters.append(f"and k.category_id = ${len(args)}")
    if query:
        args.append(f"%{query}%")
        filters.append(
            f"and (v.title ilike ${len(args)} or v.content ilike ${len(args)})"
        )
    if cursor is not None:
        args.append(cursor)
        filters.append(f"and k.card_id < ${len(args)}")
    args.append(limit)
    visible_version = "k.published_version_id" if staff else "k.draft_version_id"
    return await conn.fetch(
        f"""
        select k.card_id, k.review_status, v.title, v.content,
               k.assignment_type, k.origin_job_id, k.needs_review_reason,
               k.updated_at, c.category_id, c.category_name,
               s.source_id, s.source_type,
               coalesce(s.original_filename, s.title) as source_title,
               exists (
                 select 1 from card_evidence e
                 where e.store_id = k.store_id and e.version_id = v.version_id
               ) as has_evidence
        from knowledge_cards k
        join card_versions v
          on v.store_id = k.store_id and v.version_id = {visible_version}
        left join task_categories c
          on c.store_id = k.store_id and c.category_id = k.category_id
        left join sources s
          on s.store_id = k.store_id and s.source_id = k.source_id
        where k.store_id = $1
          {' '.join(filters)}
        order by k.card_id desc
        limit ${len(args)}
        """,
        *args,
    )


async def count_cards(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    review_status: str,
    job_id: int | None,
    category_id: int | None,
    query: str | None,
    staff: bool,
) -> int:
    status_sql, status_args = _status_clause(review_status, staff)
    args: list[object] = [store_id]
    if status_args:
        args.extend(status_args)
        status_sql = status_sql.replace("$STATUS", f"${len(args)}")
    filters = [status_sql]
    if job_id is not None:
        args.append(job_id)
        filters.append(f"and k.origin_job_id = ${len(args)}")
    if category_id is not None:
        args.append(category_id)
        filters.append(f"and k.category_id = ${len(args)}")
    if query:
        args.append(f"%{query}%")
        filters.append(
            f"and (v.title ilike ${len(args)} or v.content ilike ${len(args)})"
        )
    visible_version = "k.published_version_id" if staff else "k.draft_version_id"
    return int(
        await conn.fetchval(
            f"""
            select count(*)
            from knowledge_cards k
            join card_versions v
              on v.store_id = k.store_id and v.version_id = {visible_version}
            where k.store_id = $1 {' '.join(filters)}
            """,
            *args,
        )
    )


async def get_card(conn: asyncpg.Connection, store_id: int, card_id: int):
    return await conn.fetchrow(
        """
        select k.*, c.category_name,
               s.source_type, coalesce(s.original_filename, s.title) as source_title,
               s.file_url
        from knowledge_cards k
        left join task_categories c
          on c.store_id = k.store_id and c.category_id = k.category_id
        left join sources s
          on s.store_id = k.store_id and s.source_id = k.source_id
        where k.store_id = $1 and k.card_id = $2
        """,
        store_id,
        card_id,
    )


async def get_card_for_update(
    conn: asyncpg.Connection, store_id: int, card_id: int
):
    return await conn.fetchrow(
        "select * from knowledge_cards where store_id = $1 and card_id = $2 for update",
        store_id,
        card_id,
    )


async def get_version(conn: asyncpg.Connection, store_id: int, version_id: int | None):
    if version_id is None:
        return None
    return await conn.fetchrow(
        """
        select version_id, version_no, title, content, change_source, created_at
        from card_versions where store_id = $1 and version_id = $2
        """,
        store_id,
        version_id,
    )


async def create_draft(
    conn: asyncpg.Connection,
    store_id: int,
    card_id: int,
    *,
    title: str,
    content: str,
    actor_id: int,
    source_version_id: int,
) -> int:
    version_id = await conn.fetchval(
        """
        insert into card_versions (
          store_id, card_id, version_no, title, content, change_source, created_by
        )
        select $1, $2, coalesce(max(version_no), 0) + 1,
               $3, $4, 'OWNER_EDIT', $5
        from card_versions where store_id = $1 and card_id = $2
        returning version_id
        """,
        store_id,
        card_id,
        title,
        content,
        actor_id,
    )
    await conn.execute(
        """
        insert into card_evidence (
          store_id, version_id, source_id, locator_type, locator, excerpt
        )
        select store_id, $3, source_id, locator_type, locator, excerpt
        from card_evidence where store_id = $1 and version_id = $2
        """,
        store_id,
        source_version_id,
        version_id,
    )
    await conn.execute(
        """
        update knowledge_cards
        set title = $3, content = $4, draft_version_id = $5
        where store_id = $1 and card_id = $2
        """,
        store_id,
        card_id,
        title,
        content,
        version_id,
    )
    return int(version_id)


async def add_event(
    conn: asyncpg.Connection,
    store_id: int,
    card_id: int,
    actor_id: int,
    action: str,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    from_category_id: int | None = None,
    to_category_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    await conn.execute(
        """
        insert into card_review_events (
          store_id, card_id, actor_id, action, from_status, to_status,
          from_category_id, to_category_id, metadata
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
        """,
        store_id,
        card_id,
        actor_id,
        action,
        from_status,
        to_status,
        from_category_id,
        to_category_id,
        json.dumps(metadata or {}, ensure_ascii=False),
    )


async def list_evidence(
    conn: asyncpg.Connection, store_id: int, version_id: int
):
    return await conn.fetch(
        """
        select e.evidence_id, e.locator_type, e.locator, e.excerpt,
               s.source_id, s.source_type,
               coalesce(s.original_filename, s.title) as source_title, s.file_url
        from card_evidence e
        join sources s on s.store_id = e.store_id and s.source_id = e.source_id
        where e.store_id = $1 and e.version_id = $2
        order by e.evidence_id
        """,
        store_id,
        version_id,
    )


async def list_events(conn: asyncpg.Connection, store_id: int, card_id: int):
    return await conn.fetch(
        """
        select event_id, action, from_status, to_status, from_category_id,
               to_category_id, metadata, created_at
        from card_review_events
        where store_id = $1 and card_id = $2
        order by event_id desc
        """,
        store_id,
        card_id,
    )


async def mutation_row(conn: asyncpg.Connection, store_id: int, card_id: int):
    return await conn.fetchrow(
        """
        select card_id, review_status, draft_version_id, published_version_id, updated_at
        from knowledge_cards where store_id = $1 and card_id = $2
        """,
        store_id,
        card_id,
    )


async def active_category(
    conn: asyncpg.Connection, store_id: int, category_id: int
):
    return await conn.fetchrow(
        """
        select category_id from task_categories
        where store_id = $1 and category_id = $2
          and is_enabled = true and deleted_at is null
        """,
        store_id,
        category_id,
    )


async def last_exclusion_event(
    conn: asyncpg.Connection, store_id: int, card_id: int
):
    return await conn.fetchrow(
        """
        select metadata from card_review_events
        where store_id = $1 and card_id = $2 and action = 'EXCLUDE'
        order by event_id desc limit 1
        """,
        store_id,
        card_id,
    )
