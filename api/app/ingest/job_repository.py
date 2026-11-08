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
        select source_id, status, source_availability
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
               js.status, js.card_count, js.error_code, js.error_message,
               s.source_availability
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
    # 실패는 조립 대기 복구본을 보존한다. 무결과의 명시 재실행만 복구본을 비운다.
    rows = await conn.fetch(
        """
        update ingest_job_sources
        set status = 'QUEUED', error_code = null, error_message = null,
            card_count = 0, segments_total = null, segments_failed = null,
            failed_segment_ids = null,
            recovery_state = case when status = 'NO_RESULT' then null else recovery_state end,
            started_at = null, completed_at = null, updated_at = now()
        where store_id = $1 and job_id = $2 and status = any($3::varchar[])
          -- D20: 삭제된 자료는 원본을 열 수 없으므로 다시 처리하지 않는다
          and not exists (
            select 1 from sources s
            where s.store_id = $1 and s.source_id = ingest_job_sources.source_id
              and s.source_availability = 'DELETED')
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
          and not exists (
            select 1 from sources s
            where s.store_id = $1 and s.source_id = ingest_job_sources.source_id
              and s.source_availability = 'DELETED')
        returning source_id
        """,
        store_id,
        job_id,
    )
    rows = [*rows, *partial_rows]
    if rows:
        await _requeue_job(conn, store_id, job_id)
    return len(rows)


async def _requeue_job(conn: asyncpg.Connection, store_id: int, job_id: int) -> None:
    """작업을 다시 대기(QUEUED)로 두고 자료 행에서 건수를 다시 센다."""
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


async def lock_job_source(conn: asyncpg.Connection, store_id: int, job_id: int,
                          source_id: int):
    """작업과 그 작업의 자료 행 하나를 잠그고 판단에 쓸 상태를 돌려준다. 없으면 None."""
    return await conn.fetchrow(
        """
        select j.status as job_status, js.status, js.error_code, s.source_availability
        from ingest_jobs j
        join ingest_job_sources js on js.store_id = j.store_id and js.job_id = j.job_id
        join sources s on s.store_id = js.store_id and s.source_id = js.source_id
        where j.store_id = $1 and j.job_id = $2 and js.source_id = $3
        for update of j, js
        """,
        store_id,
        job_id,
        source_id,
    )


async def requeue_intake_none_source(conn: asyncpg.Connection, store_id: int, job_id: int,
                                     source_id: int) -> bool:
    """업무 자료 아님(INTAKE_NONE)으로 끝난 자료 하나만 다시 대기열에 넣는다(후속 1).

    같은 작업의 다른 무결과 자료는 건드리지 않는다(유료 재추출 방지). 무결과라 조립 대기
    복구본은 비운다 — reset_retryable_sources 의 무결과 재실행과 같다. 대상이 아니면 False.
    """
    got = await conn.fetchval(
        """
        update ingest_job_sources
        set status = 'QUEUED', error_code = null, error_message = null,
            card_count = 0, segments_total = null, segments_failed = null,
            failed_segment_ids = null, recovery_state = null,
            started_at = null, completed_at = null, updated_at = now()
        where store_id = $1 and job_id = $2 and source_id = $3
          and status = 'NO_RESULT' and error_code = 'INTAKE_NONE'
          and not exists (
            select 1 from sources s
            where s.store_id = $1 and s.source_id = ingest_job_sources.source_id
              and s.source_availability = 'DELETED')
        returning source_id
        """,
        store_id,
        job_id,
        source_id,
    )
    if got is None:
        return False
    await _requeue_job(conn, store_id, job_id)
    return True


async def source_in_progress(conn: asyncpg.Connection, store_id: int, source_id: int) -> bool:
    """자료가 지금 처리 중(대기 포함)인가. 처리 중 자료는 삭제하지 않는다."""
    return bool(await conn.fetchval(
        """
        select exists (
          select 1 from sources
          where store_id = $1 and source_id = $2 and status = 'PROCESSING'
        ) or exists (
          select 1 from ingest_job_sources js
          join ingest_jobs j on j.store_id = js.store_id and j.job_id = js.job_id
          where js.store_id = $1 and js.source_id = $2
            and js.status in ('QUEUED', 'EXTRACTING', 'CLASSIFYING')
            -- 자료 등록 트리거가 만드는 호환 작업은 상태 변경 때만 동기화된다.
            -- 처리하지 않은 자료도 QUEUED 로 남으므로 처리 중으로 보지 않는다
            and j.prompt_version <> 'legacy-adapter'
        )
        """,
        store_id,
        source_id,
    ))


_ACTIVE = ("QUEUED", "EXTRACTING", "CLASSIFYING")
CANCELED_MESSAGE = "정리를 취소했어요."
STALLED_MESSAGE = "정리가 오래 멈춰 있어 중단했어요. 다시 시도해 주세요."


async def cancel_job(conn, store_id: int, job_id: int) -> bool:
    """정리 중인 작업 취소(2026-11-08 사용자). 진행 중이 아니거나 다른 매장이면 False.

    뒤에서 돌던 처리는 error_code 가 JOB_CANCELED 인 작업·자료를 덮어쓰지 않는다(job_worker).
    """
    async with conn.transaction():
        updated = await conn.fetchval(
            """
            update ingest_jobs set status = 'FAILED', error_code = 'JOB_CANCELED', error_message = $3,
                   completed_at = now(), updated_at = now()
             where store_id = $1 and job_id = $2 and status = any($4::varchar[])
            returning job_id
            """,
            store_id, job_id, CANCELED_MESSAGE, list(_ACTIVE))
        if updated is None:
            return False
        await conn.execute(
            """
            update ingest_job_sources set status = 'FAILED', error_code = 'JOB_CANCELED', error_message = $3,
                   completed_at = now(), updated_at = now()
             where store_id = $1 and job_id = $2 and status in ('QUEUED', 'EXTRACTING')
            """,
            store_id, job_id, CANCELED_MESSAGE)
    return True


async def fail_stalled_jobs(conn, store_id: int | None, *, minutes: int) -> int:
    """오래 갱신이 없는 진행 중 작업을 '멈춤'으로 실패 처리한다. 서버가 꺼지면 백그라운드 처리가 사라져
    작업이 '읽는 중'에 영원히 남던 문제(2026-11-08). store_id 가 None 이면 서버 시작 때 모든 매장.
    """
    # store-isolation-ok: 서버 시작 때(store_id None)는 매장 구분 없이 고아 작업만 정리한다
    rows = await conn.fetch(
        """
        update ingest_jobs set status = 'FAILED', error_code = 'JOB_STALLED', error_message = $3,
               completed_at = now(), updated_at = now()
         where ($1::bigint is null or store_id = $1) and status = any($4::varchar[])
           and updated_at < now() - make_interval(mins => $2)
        returning store_id, job_id
        """,
        store_id, minutes, STALLED_MESSAGE, list(_ACTIVE))
    for row in rows:
        await conn.execute(
            """
            update ingest_job_sources set status = 'FAILED', error_code = 'JOB_STALLED', error_message = $3,
                   completed_at = now(), updated_at = now()
             where store_id = $1 and job_id = $2 and status in ('QUEUED', 'EXTRACTING')
            """,
            row["store_id"], row["job_id"], STALLED_MESSAGE)
    return len(rows)
