from __future__ import annotations

from uuid import uuid4

import asyncpg


async def get_store_for_update(conn: asyncpg.Connection, store_id: int):
    return await conn.fetchrow(
        "select store_id, category_version from stores where store_id = $1 for update",
        store_id,
    )


async def list_current(conn: asyncpg.Connection, store_id: int):
    return await conn.fetch(
        """
        select category_id, category_name, is_system, sort_order
        from task_categories
        where store_id = $1 and deleted_at is null and is_enabled = true
        order by sort_order, category_id
        """,
        store_id,
    )


async def latest_job(conn: asyncpg.Connection, store_id: int):
    return await conn.fetchrow(
        """
        select reclass_job_id, status
        from reclassification_jobs
        where store_id = $1
        order by reclass_job_id desc
        limit 1
        """,
        store_id,
    )


async def create_category(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    name: str,
    sort_order: int,
    version: int,
):
    existing = await conn.fetchrow(
        """
        select category_id, is_enabled, deleted_at
        from task_categories
        where store_id = $1 and lower(category_name) = lower($2)
        for update
        """,
        store_id,
        name,
    )
    if existing and existing["deleted_at"] is None and existing["is_enabled"]:
        return None
    if existing:
        return await conn.fetchrow(
            """
            update task_categories
            set category_name = $3, is_enabled = true, sort_order = $4,
                is_system = false, created_version = $5,
                deleted_version = null, deleted_at = null, updated_at = now()
            where store_id = $1 and category_id = $2
            returning category_id, category_name, is_system, sort_order
            """,
            store_id,
            int(existing["category_id"]),
            name,
            sort_order,
            version,
        )
    return await conn.fetchrow(
        """
        insert into task_categories (
          store_id, category_name, is_enabled, sort_order, is_system,
          created_version, updated_at
        )
        values ($1, $2, true, $3, false, $4, now())
        returning category_id, category_name, is_system, sort_order
        """,
        store_id,
        name,
        sort_order,
        version,
    )


async def get_category_for_update(
    conn: asyncpg.Connection, store_id: int, category_id: int
):
    return await conn.fetchrow(
        """
        select category_id, category_name, is_system, sort_order
        from task_categories
        where store_id = $1 and category_id = $2 and deleted_at is null
        for update
        """,
        store_id,
        category_id,
    )


async def get_category_by_name_for_update(
    conn: asyncpg.Connection, store_id: int, name: str
):
    return await conn.fetchrow(
        """
        select category_id, category_name, is_system, is_enabled, sort_order, deleted_at
        from task_categories
        where store_id = $1 and category_name = $2
        for update
        """,
        store_id,
        name,
    )


async def soft_delete_category(
    conn: asyncpg.Connection,
    store_id: int,
    category_id: int,
    *,
    version: int,
) -> None:
    await conn.execute(
        """
        update task_categories
        set is_enabled = false, deleted_version = $3, deleted_at = now(), updated_at = now()
        where store_id = $1 and category_id = $2 and is_system = false
        """,
        store_id,
        category_id,
        version,
    )


async def move_deleted_manual_cards_to_other(
    conn: asyncpg.Connection, store_id: int, category_id: int, version: int
) -> int:
    result = await conn.execute(
        """
        update knowledge_cards c
        set category_id = other.category_id,
            category_version = $3,
            needs_review_reason = 'CATEGORY_DELETED',
            updated_at = now()
        from task_categories other
        where c.store_id = $1
          and c.category_id = $2
          and c.assignment_type = 'MANUAL'
          and other.store_id = c.store_id
          and other.is_system = true
          and other.category_name = '기타'
          and other.deleted_at is null
        """,
        store_id,
        category_id,
        version,
    )
    return int(result.split()[-1])


async def set_store_version(
    conn: asyncpg.Connection, store_id: int, version: int
) -> None:
    await conn.execute(
        "update stores set category_version = $2 where store_id = $1",
        store_id,
        version,
    )


async def create_job(
    conn: asyncpg.Connection,
    store_id: int,
    user_id: int,
    version: int,
    *,
    retry: bool = False,
) -> int | None:
    total = await conn.fetchval(
        """
        select count(*) from knowledge_cards
        where store_id = $1 and review_status <> 'EXCLUDED'
        """,
        store_id,
    )
    if not total:
        return None

    key = f"category-version-{version}"
    if retry:
        key += f"-retry-{uuid4().hex}"
    job_id = await conn.fetchval(
        """
        insert into reclassification_jobs (
          store_id, requested_by, target_category_version, status,
          total_count, idempotency_key, updated_at
        )
        values ($1, $2, $3, 'QUEUED', $4, $5, now())
        returning reclass_job_id
        """,
        store_id,
        user_id,
        version,
        int(total),
        key,
    )
    await conn.execute(
        """
        insert into reclassification_results (
          store_id, reclass_job_id, card_id, source_category_id,
          card_updated_at_snapshot
        )
        select store_id, $2, card_id, category_id, coalesce(updated_at, created_at)
        from knowledge_cards
        where store_id = $1 and review_status <> 'EXCLUDED'
        """,
        store_id,
        int(job_id),
    )
    return int(job_id)


async def get_job(conn: asyncpg.Connection, store_id: int, job_id: int):
    return await conn.fetchrow(
        """
        select reclass_job_id, target_category_version, status,
               total_count, applied_count, skipped_count, failed_count,
               error_code, error_message, started_at, completed_at
        from reclassification_jobs
        where store_id = $1 and reclass_job_id = $2
        """,
        store_id,
        job_id,
    )
