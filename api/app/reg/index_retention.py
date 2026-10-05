"""Opt-in vector cleanup; snapshot/provenance and preparation headers survive."""
from app.config import get_settings


async def purge_expired_index_documents(pool) -> int:
    settings = get_settings()
    if not settings.r_index_gc_enabled:
        return 0
    keep, days = settings.r_index_gc_keep_previous, settings.r_index_gc_min_age_days
    if keep is None or days is None:
        raise ValueError('index retention requires agreed keep_previous and min_age_days')
    removed, last_store = 0, 0
    while True:
        async with pool.acquire() as conn:
            # store-isolation-ok: maintenance enumerates stores, deletion below is scoped.
            rows = await conn.fetch('''select distinct store_id from r_index_documents
                where store_id>$1 order by store_id limit 100''', last_store)
        if not rows:
            return removed
        for row in rows:
            last_store = row['store_id']
            async with pool.acquire() as conn:
                async with conn.transaction():
                    removed += await conn.fetchval('select purge_r_index_documents($1,$2,$3)',
                        last_store, keep, days)
