"""30-day diagnostics maintenance. Dry run by default; no answer deletion."""
import argparse
import asyncio
import json
import os

import asyncpg


async def run(args):
    # Explicit maintenance environment, never silently load production .env.
    dsn = os.environ.get('R_MAINTENANCE_DSN')
    if not dsn:
        raise SystemExit('R_MAINTENANCE_DSN is required')
    conn = await asyncpg.connect(dsn)
    try:
        if args.apply:
            count = await conn.fetchval('select purge_r_execution_metadata($1)', args.store_id)
        else:
            count = await conn.fetchval("""select count(*) from r_answer_receipts where store_id=$1
                and created_at<=clock_timestamp()-interval '30 days'
                and (execution_metadata-'policy_receipt_id')<>'{}'::jsonb""", args.store_id)
        print(json.dumps(dict(store_id=args.store_id, applied=args.apply, metadata_rows=count)))
    finally:
        await conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--store-id', type=int, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.store_id <= 0:
        parser.error('positive store id required')
    asyncio.run(run(args))
