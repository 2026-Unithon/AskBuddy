"""카테고리 변경 후 기존 카드의 비동기 재분류 작업."""
from __future__ import annotations

import logging

from app.categories.classifier import classify_cards
from app.deps import get_pool

logger = logging.getLogger(__name__)


async def process_reclassification_job(store_id: int, job_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        job = await conn.fetchrow(
            """
            update reclassification_jobs
            set status = 'RUNNING', started_at = now(), completed_at = null,
                error_code = null, error_message = null, updated_at = now()
            where store_id = $1 and reclass_job_id = $2 and status = 'QUEUED'
            returning reclass_job_id, target_category_version, status
            """,
            store_id,
            job_id,
        )
        # 같은 작업이 중복 예약돼도 한 워커만 원자적으로 가져간다.
        if job is None:
            return

        current_version = await conn.fetchval(
            "select category_version from stores where store_id = $1", store_id
        )
        if current_version != job["target_category_version"]:
            await _finish_stale(conn, store_id, job_id)
            return

        try:
            categories = await conn.fetch(
                """
                select category_id, category_name
                from task_categories
                where store_id = $1 and deleted_at is null and is_enabled = true
                order by sort_order, category_id
                """,
                store_id,
            )
            category_ids = {
                row["category_name"]: int(row["category_id"]) for row in categories
            }
            rows = await conn.fetch(
                """
                select r.card_id, r.card_updated_at_snapshot,
                       c.title, c.content, c.assignment_type,
                       tc.category_name
                from reclassification_results r
                join knowledge_cards c
                  on c.store_id = r.store_id and c.card_id = r.card_id
                left join task_categories tc on tc.category_id = c.category_id
                where r.store_id = $1 and r.reclass_job_id = $2 and r.result = 'PENDING'
                order by r.card_id
                """,
                store_id,
                job_id,
            )

            automatic = [
                dict(row) for row in rows if row["assignment_type"] == "AUTOMATIC"
            ]
            choices = (
                await classify_cards(automatic, list(category_ids)) if automatic else {}
            )

            for row in rows:
                latest_version = await conn.fetchval(
                    "select category_version from stores where store_id = $1", store_id
                )
                if latest_version != job["target_category_version"]:
                    await _finish_stale(conn, store_id, job_id)
                    return

                if row["assignment_type"] == "MANUAL":
                    await _mark_result(
                        conn, store_id, job_id, row["card_id"], "SKIPPED_MANUAL"
                    )
                    continue

                proposed_id = category_ids[choices[int(row["card_id"])]]
                updated = await conn.fetchrow(
                    """
                    update knowledge_cards
                    set category_id = $4, category_version = $5, updated_at = now()
                    where store_id = $1 and card_id = $2
                      and assignment_type = 'AUTOMATIC'
                      and coalesce(updated_at, created_at) = $3
                      and (select category_version from stores where store_id = $1) = $5
                    returning card_id
                    """,
                    store_id,
                    int(row["card_id"]),
                    row["card_updated_at_snapshot"],
                    proposed_id,
                    int(job["target_category_version"]),
                )
                if updated is None:
                    await _mark_result(
                        conn, store_id, job_id, row["card_id"], "SKIPPED_NEWER_EDIT"
                    )
                else:
                    await conn.execute(
                        """
                        update reclassification_results
                        set proposed_category_id = $4, result = 'APPLIED', applied_at = now()
                        where store_id = $1 and reclass_job_id = $2 and card_id = $3
                        """,
                        store_id,
                        job_id,
                        int(row["card_id"]),
                        proposed_id,
                    )

            await _finish_from_results(conn, store_id, job_id)
        except Exception as exc:
            logger.exception("reclassification FAILED store=%s job=%s", store_id, job_id)
            await conn.execute(
                """
                update reclassification_results
                set result = 'FAILED', reason = $3
                where store_id = $1 and reclass_job_id = $2 and result = 'PENDING'
                """,
                store_id,
                job_id,
                str(exc)[:500],
            )
            await conn.execute(
                """
                update reclassification_jobs
                set status = 'FAILED', error_code = 'RECLASSIFICATION_FAILED',
                    error_message = $3, completed_at = now(), updated_at = now(),
                    failed_count = (
                      select count(*) from reclassification_results
                      where store_id = $1 and reclass_job_id = $2 and result = 'FAILED'
                    )
                where store_id = $1 and reclass_job_id = $2
                """,
                store_id,
                job_id,
                str(exc)[:1000],
            )


async def _mark_result(conn, store_id: int, job_id: int, card_id: int, result: str) -> None:
    await conn.execute(
        """
        update reclassification_results set result = $4::varchar
        where store_id = $1 and reclass_job_id = $2 and card_id = $3
        """,
        store_id,
        job_id,
        int(card_id),
        result,
    )


async def _finish_from_results(conn, store_id: int, job_id: int) -> None:
    await conn.execute(
        """
        update reclassification_jobs j
        set status = case when counts.failed > 0 then 'FAILED' else 'SUCCEEDED' end,
            applied_count = counts.applied,
            skipped_count = counts.skipped,
            failed_count = counts.failed,
            completed_at = now(), updated_at = now()
        from (
          select count(*) filter (where result = 'APPLIED')::int as applied,
                 count(*) filter (where result like 'SKIPPED_%')::int as skipped,
                 count(*) filter (where result = 'FAILED')::int as failed
          from reclassification_results
          where store_id = $1 and reclass_job_id = $2
        ) counts
        where j.store_id = $1 and j.reclass_job_id = $2
        """,
        store_id,
        job_id,
    )


async def _finish_stale(conn, store_id: int, job_id: int) -> None:
    await conn.execute(
        """
        update reclassification_jobs
        set status = 'STALE', completed_at = now(), updated_at = now()
        where store_id = $1 and reclass_job_id = $2
        """,
        store_id,
        job_id,
    )
