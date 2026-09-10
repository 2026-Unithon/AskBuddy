"""다중 자료 ingest 작업 오케스트레이터."""
from __future__ import annotations

import logging

from app.deps import get_pool
from app.ingest import pipeline

logger = logging.getLogger(__name__)


def final_job_status(*, total: int, failed: int, cards: int) -> str:
    if failed == total:
        return "FAILED"
    if failed > 0:
        return "PARTIAL"
    if cards == 0:
        return "NO_RESULT"
    return "SUCCEEDED"


async def process_ingest_job(store_id: int, job_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        claimed = await conn.fetchrow(
            """
            update ingest_jobs
            set status = 'EXTRACTING', started_at = coalesce(started_at, now()),
                completed_at = null, error_code = null, error_message = null,
                updated_at = now()
            where store_id = $1 and job_id = $2 and status = 'QUEUED'
            returning category_version
            """,
            store_id,
            job_id,
        )
        if claimed is None:
            return
        source_ids = await conn.fetch(
            """
            select source_id from ingest_job_sources
            where store_id = $1 and job_id = $2 and status = 'QUEUED'
            order by source_id
            """,
            store_id,
            job_id,
        )

    try:
        for row in source_ids:
            source_id = int(row["source_id"])
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    update ingest_job_sources
                    set status = 'EXTRACTING', started_at = now(), updated_at = now()
                    where store_id = $1 and job_id = $2 and source_id = $3
                    """,
                    store_id,
                    job_id,
                    source_id,
                )

            await pipeline.process_source(store_id, source_id, job_id=job_id)

            async with pool.acquire() as conn:
                source = await conn.fetchrow(
                    """
                    select status, error_message from sources
                    where store_id = $1 and source_id = $2
                    """,
                    store_id,
                    source_id,
                )
                card_count = int(
                    await conn.fetchval(
                        """
                        select count(*) from knowledge_cards
                        where store_id = $1 and source_id = $2 and origin_job_id = $3
                        """,
                        store_id,
                        source_id,
                        job_id,
                    )
                    or 0
                )
                if source is None or source["status"] == "FAILED":
                    result_status = "FAILED"
                    error_code = "EXTRACTION_FAILED"
                    error_message = (
                        source["error_message"] if source else "자료를 찾을 수 없습니다."
                    )
                elif card_count == 0:
                    result_status = "NO_RESULT"
                    error_code = "NO_RESULT"
                    error_message = "추출된 업무 카드가 없습니다."
                else:
                    result_status = "SUCCEEDED"
                    error_code = None
                    error_message = None
                await conn.execute(
                    """
                    update ingest_job_sources
                    set status = $4, card_count = $5, error_code = $6,
                        error_message = $7, completed_at = now(), updated_at = now()
                    where store_id = $1 and job_id = $2 and source_id = $3
                    """,
                    store_id,
                    job_id,
                    source_id,
                    result_status,
                    card_count,
                    error_code,
                    error_message,
                )
                await _refresh_job(conn, store_id, job_id, final=False)

        async with pool.acquire() as conn:
            await _refresh_job(conn, store_id, job_id, final=True)
    except Exception as exc:
        logger.exception("ingest job FAILED store=%s job=%s", store_id, job_id)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                update ingest_jobs
                set status = 'FAILED', error_code = 'JOB_WORKER_FAILED',
                    error_message = $3, completed_at = now(), updated_at = now()
                where store_id = $1 and job_id = $2
                """,
                store_id,
                job_id,
                str(exc)[:1000],
            )


async def _refresh_job(conn, store_id: int, job_id: int, *, final: bool) -> None:
    counts = await conn.fetchrow(
        """
        select count(*)::int as total,
               count(*) filter (where status = 'SUCCEEDED')::int as succeeded,
               count(*) filter (where status = 'FAILED')::int as failed,
               count(*) filter (where status = 'NO_RESULT')::int as no_result,
               coalesce(sum(card_count), 0)::int as cards
        from ingest_job_sources
        where store_id = $1 and job_id = $2
        """,
        store_id,
        job_id,
    )
    if final:
        status = final_job_status(
            total=int(counts["total"]),
            failed=int(counts["failed"]),
            cards=int(counts["cards"]),
        )
    else:
        status = "EXTRACTING"
    await conn.execute(
        """
        update ingest_jobs
        set status = $3, success_source_count = $4, failed_source_count = $5,
            card_count = $6,
            category_version = (select category_version from stores where store_id = $1),
            completed_at = case when $7 then now() else completed_at end,
            updated_at = now()
        where store_id = $1 and job_id = $2
        """,
        store_id,
        job_id,
        status,
        int(counts["succeeded"]),
        int(counts["failed"]),
        int(counts["cards"]),
        final,
    )
