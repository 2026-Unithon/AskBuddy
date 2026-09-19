"""Server-only diagnostics cleanup, including stores without new questions."""
import asyncio
import logging

logger = logging.getLogger(__name__)
SWEEP_SECONDS = 3600


async def purge_expired_metadata(pool) -> int:
    removed = 0
    last_store = 0
    while True:
        async with pool.acquire() as conn:
            stores = await conn.fetch("""select distinct store_id from r_answer_receipts
                where store_id>$1 and created_at<=clock_timestamp()-interval '30 days'
                  and (execution_metadata-'policy_receipt_id')<>'{}'::jsonb
                order by store_id limit 100""", last_store)
        if not stores:
            return removed
        for row in stores:
            last_store = row['store_id']
            async with pool.acquire() as conn:
                removed += await conn.fetchval('select purge_r_execution_metadata($1)', last_store)


async def retention_loop(pool):
    while True:
        try:
            count = await purge_expired_metadata(pool)
            logger.info('R diagnostics retention sweep removed=%d', count)
        except Exception as exc:
            # Error type only: driver messages can contain query/body fragments.
            logger.error('R diagnostics retention failed type=%s', type(exc).__name__)
        await asyncio.sleep(SWEEP_SECONDS)
