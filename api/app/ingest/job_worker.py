"""다중 자료 ingest 작업 오케스트레이터."""
from __future__ import annotations

import logging

from app.deps import get_pool
from app.ingest import pipeline
from app.notifications.service import (
    create_ingest_completed_notification,
    deliver_notification,
)

logger = logging.getLogger(__name__)

PARTIAL_RETRY_UNAVAILABLE_MESSAGE = (
    "구간 구성이 바뀌어 잃은 구간만 다시 읽을 수 없습니다. 자료를 새로 올려 주세요."
)
PARTIAL_RETRY_FAILED_MESSAGE = "잃은 구간을 다시 읽다가 실패했습니다. 다시 시도해 주세요."


def final_job_status(*, total: int, failed: int, cards: int,
                     partial: bool = False) -> str:
    """`partial` 은 자료는 끝났지만 그 안의 구간 일부를 잃었다는 뜻이다.

    구간을 버리고도 카드가 나왔다는 이유로 성공이라고 적으면, 점주는 빠진
    내용을 영영 모른다.
    """
    if failed == total:
        return "FAILED"
    if failed > 0:
        return "PARTIAL"
    if cards == 0:
        return "NO_RESULT"
    if partial:
        return "PARTIAL"
    return "SUCCEEDED"


def _run_tag(started_at) -> int | None:
    """자료 시작 시각을 epoch 밀리초 정수로 바꾼다. 행이 없으면 표지 없이 돈다."""
    if started_at is None:
        return None
    return int(started_at.timestamp() * 1000)


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
            select source_id, failed_segment_ids, segments_total
            from ingest_job_sources
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
                started_at = await conn.fetchval(
                    """
                    update ingest_job_sources
                    set status = 'EXTRACTING', started_at = now(), updated_at = now()
                    where store_id = $1 and job_id = $2 and source_id = $3
                    returning started_at
                    """,
                    store_id,
                    job_id,
                    source_id,
                )
            # 실행 표지 — 같은 작업을 다시 돌리면 job_id 가 같아 원가 receipt 의
            # 논리 호출 ID 가 지난 실행과 겹친다 (원장 unique). 시작 시각으로 가른다
            run_tag = _run_tag(started_at)

            # PARTIAL 재시도면 잃은 구간만 다시 읽는다. 전체를 다시 돌리면 카드가 겹친다
            lost_ids = row["failed_segment_ids"]
            if lost_ids:
                outcome = await pipeline.process_source(
                    store_id, source_id, job_id=job_id,
                    retry_segments=list(lost_ids),
                    expected_segments_total=row["segments_total"],
                    run_tag=run_tag,
                )
            else:
                outcome = await pipeline.process_source(
                    store_id, source_id, job_id=job_id, run_tag=run_tag)

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
                if lost_ids and source is not None and source["status"] == "FAILED":
                    # 잃은 구간 재시도가 예외로 끝났다. 앞서 만든 카드는 그대로 있다.
                    # FAILED 로 적으면 다음 재시도가 전체를 다시 돌려 카드가 겹치므로
                    # PARTIAL 로 남기고 구간 기록도 건드리지 않는다
                    result_status = "PARTIAL"
                    error_code = "PARTIAL_RETRY_FAILED"
                    detail = source["error_message"]
                    error_message = (
                        f"{PARTIAL_RETRY_FAILED_MESSAGE} ({detail})" if detail
                        else PARTIAL_RETRY_FAILED_MESSAGE
                    )[:1000]
                elif source is None or source["status"] == "FAILED":
                    result_status = "FAILED"
                    error_code = "EXTRACTION_FAILED"
                    error_message = (
                        source["error_message"] if source else "자료를 찾을 수 없습니다."
                    )
                elif outcome == pipeline.PARTIAL_RETRY_UNAVAILABLE:
                    result_status = 'PARTIAL' if card_count else 'FAILED'
                    error_code = 'PARTIAL_RETRY_UNAVAILABLE'
                    error_message = PARTIAL_RETRY_UNAVAILABLE_MESSAGE
                elif card_count == 0:
                    result_status = "NO_RESULT"
                    error_code = "NO_RESULT"
                    error_message = "추출된 업무 카드가 없습니다."
                else:
                    # 카드가 나왔어도 잃은 구간이 있으면 성공으로 적지 않는다
                    lost = await conn.fetchrow(
                        """
                        select segments_total, segments_failed
                        from ingest_job_sources
                        where store_id = $1 and job_id = $2 and source_id = $3
                        """,
                        store_id,
                        job_id,
                        source_id,
                    )
                    failed_segments = int(
                        (lost and lost["segments_failed"]) or 0)
                    if failed_segments:
                        result_status = "PARTIAL"
                        error_code = "PARTIAL_EXTRACTION"
                        error_message = (
                            f"자료의 일부 구간 {failed_segments}/"
                            f"{lost['segments_total']}개를 읽지 못했습니다."
                        )
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

        notification_id: int | None = None
        async with pool.acquire() as conn:
            status, card_count = await _refresh_job(conn, store_id, job_id, final=True)
            if status in ("SUCCEEDED", "PARTIAL") and card_count > 0:
                try:
                    notification_id = await create_ingest_completed_notification(
                        conn, store_id, job_id, card_count
                    )
                except Exception:
                    logger.exception(
                        "ingest notification create failed store=%s job=%s",
                        store_id,
                        job_id,
                    )
        if notification_id is not None:
            await deliver_notification(store_id, notification_id)
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


async def _refresh_job(
    conn, store_id: int, job_id: int, *, final: bool
) -> tuple[str, int]:
    counts = await conn.fetchrow(
        """
        select count(*)::int as total,
               count(*) filter (where status = 'SUCCEEDED')::int as succeeded,
               count(*) filter (where status = 'FAILED')::int as failed,
               count(*) filter (where status = 'NO_RESULT')::int as no_result,
               count(*) filter (where status = 'PARTIAL')::int as partial,
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
            partial=int(counts["partial"]) > 0,
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
    return status, int(counts["cards"])
