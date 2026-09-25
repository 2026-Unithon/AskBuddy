from __future__ import annotations

import json

import asyncpg


async def find_by_idempotency(
    conn: asyncpg.Connection, store_id: int, key: str
):
    return await conn.fetchrow(
        """
        select job_id, status, category_version, total_source_count
        from ingest_jobs
        where store_id = $1 and idempotency_key = $2
        """,
        store_id,
        key,
    )


async def source_rows(
    conn: asyncpg.Connection, store_id: int, source_ids: list[int]
):
    return await conn.fetch(
        """
        select source_id, status
        from sources
        where store_id = $1 and source_id = any($2::bigint[])
        order by source_id
        """,
        store_id,
        source_ids,
    )


async def create_job(
    conn: asyncpg.Connection,
    store_id: int,
    user_id: int,
    *,
    title: str | None,
    source_ids: list[int],
    category_version: int,
    prompt_version: str,
    settings: dict,
    idempotency_key: str | None,
):
    job = await conn.fetchrow(
        """
        insert into ingest_jobs (
          store_id, created_by, title, status, category_version,
          prompt_version, settings, total_source_count, idempotency_key, updated_at
        )
        values ($1, $2, $3, 'QUEUED', $4, $5, $6::jsonb, $7, $8, now())
        returning job_id, status, category_version, total_source_count
        """,
        store_id,
        user_id,
        title,
        category_version,
        prompt_version,
        json.dumps(settings, ensure_ascii=False),
        len(source_ids),
        idempotency_key,
    )
    await conn.executemany(
        """
        insert into ingest_job_sources (store_id, job_id, source_id, status, updated_at)
        values ($1, $2, $3, 'QUEUED', now())
        """,
        [(store_id, int(job["job_id"]), source_id) for source_id in source_ids],
    )
    return job


async def list_jobs(
    conn: asyncpg.Connection,
    store_id: int,
    *,
    job_status: str | None,
    cursor: int | None,
    limit: int,
):
    return await conn.fetch(
        """
        select job_id, title, status, category_version,
               total_source_count, card_count, created_at, completed_at
        from ingest_jobs j
        where j.store_id = $1
          and ($2::varchar is null or j.status = $2::varchar)
          and ($3::bigint is null or j.job_id < $3)
          and (
            coalesce(j.idempotency_key, '') not like 'legacy-source-%'
            or not exists (
              select 1
              from ingest_job_sources legacy_source
              join ingest_job_sources grouped_source
                on grouped_source.store_id = legacy_source.store_id
               and grouped_source.source_id = legacy_source.source_id
               and grouped_source.job_id <> legacy_source.job_id
              join ingest_jobs grouped_job
                on grouped_job.store_id = grouped_source.store_id
               and grouped_job.job_id = grouped_source.job_id
              where legacy_source.store_id = j.store_id
                and legacy_source.job_id = j.job_id
                and coalesce(grouped_job.idempotency_key, '') not like 'legacy-source-%'
            )
          )
        order by j.job_id desc
        limit $4
        """,
        store_id,
        job_status,
        cursor,
        limit,
    )


async def count_jobs(
    conn: asyncpg.Connection, store_id: int, job_status: str | None
) -> int:
    return int(
        await conn.fetchval(
            """
            select count(*) from ingest_jobs j
            where j.store_id = $1
              and ($2::varchar is null or j.status = $2::varchar)
              and (
                coalesce(j.idempotency_key, '') not like 'legacy-source-%'
                or not exists (
                  select 1
                  from ingest_job_sources legacy_source
                  join ingest_job_sources grouped_source
                    on grouped_source.store_id = legacy_source.store_id
                   and grouped_source.source_id = legacy_source.source_id
                   and grouped_source.job_id <> legacy_source.job_id
                  join ingest_jobs grouped_job
                    on grouped_job.store_id = grouped_source.store_id
                   and grouped_job.job_id = grouped_source.job_id
                  where legacy_source.store_id = j.store_id
                    and legacy_source.job_id = j.job_id
                    and coalesce(grouped_job.idempotency_key, '') not like 'legacy-source-%'
                )
              )
            """,
            store_id,
            job_status,
        )
        or 0
    )


async def get_job(conn: asyncpg.Connection, store_id: int, job_id: int):
    return await conn.fetchrow(
        """
        select job_id, title, status, category_version,
               total_source_count, success_source_count, failed_source_count,
               card_count, error_code, error_message, created_at, completed_at
        from ingest_jobs
        where store_id = $1 and job_id = $2
        """,
        store_id,
        job_id,
    )


async def get_job_sources(conn: asyncpg.Connection, store_id: int, job_id: int):
    return await conn.fetch(
        """
        select js.source_id, coalesce(s.original_filename, s.title) as filename,
               js.status, js.card_count, js.error_code, js.error_message
        from ingest_job_sources js
        join sources s on s.store_id = js.store_id and s.source_id = js.source_id
        where js.store_id = $1 and js.job_id = $2
        order by js.source_id
        """,
        store_id,
        job_id,
    )


async def reset_retryable_sources(
    conn: asyncpg.Connection,
    store_id: int,
    job_id: int,
    *,
    include_no_result: bool,
) -> int:
    statuses = ["FAILED", "NO_RESULT"] if include_no_result else ["FAILED"]
    # 실패·무결과 자료는 처음부터 다시 돈다. 지난 구간 기록도 함께 비운다
    rows = await conn.fetch(
        """
        update ingest_job_sources
        set status = 'QUEUED', error_code = null, error_message = null,
            card_count = 0, segments_total = null, segments_failed = null,
            failed_segment_ids = null,
            started_at = null, completed_at = null, updated_at = now()
        where store_id = $1 and job_id = $2 and status = any($3::varchar[])
        returning source_id
        """,
        store_id,
        job_id,
        statuses,
    )
    # PARTIAL 은 이미 카드가 있다. 잃은 구간만 다시 읽도록 카드 수와 구간
    # 기록을 남긴다 — 비우면 전체 재실행이 되어 카드가 중복된다
    partial_rows = await conn.fetch(
        """
        update ingest_job_sources
        set status = 'QUEUED', error_code = null, error_message = null,
            started_at = null, completed_at = null, updated_at = now()
        where store_id = $1 and job_id = $2 and status = 'PARTIAL'
        returning source_id
        """,
        store_id,
        job_id,
    )
    rows = [*rows, *partial_rows]
    if rows:
        await conn.execute(
            """
            update ingest_jobs
            set status = 'QUEUED', error_code = null, error_message = null,
                success_source_count = (
                  select count(*) from ingest_job_sources
                  where store_id = $1 and job_id = $2 and status = 'SUCCEEDED'
                ),
                failed_source_count = (
                  select count(*) from ingest_job_sources
                  where store_id = $1 and job_id = $2 and status = 'FAILED'
                ),
                card_count = (
                  select coalesce(sum(card_count), 0) from ingest_job_sources
                  where store_id = $1 and job_id = $2
                ),
                completed_at = null, updated_at = now()
            where store_id = $1 and job_id = $2
            """,
            store_id,
            job_id,
        )
    return len(rows)
