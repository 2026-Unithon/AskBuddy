#!/usr/bin/env python3
"""LLM 과금/데이터 변경 없이 동시 DB 호출 대기와 실패율을 측정한다.

이는 SELECT 1 부하이며 실제 모델 RPM/TPM/자료 처리 한계 측정이 아니다.
"""
import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg
from app.config import get_settings


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] * 1000, 2) if values else None


async def probe(pool, users, calls, timeout, hold_ms=0):
    latencies, acquires, errors = [], [], {}
    started = time.perf_counter()

    async def one():
        begin = time.perf_counter()
        try:
            async with asyncio.timeout(timeout), pool.acquire() as conn:
                acquires.append(time.perf_counter() - begin)
                if hold_ms:
                    await conn.execute('select pg_sleep($1)', hold_ms / 1000)
                else:
                    await conn.fetchval('select 1')
            latencies.append(time.perf_counter() - begin)
        except Exception as exc:
            name = type(exc).__name__
            errors[name] = errors.get(name, 0) + 1

    await asyncio.gather(*(one() for _ in range(users * calls)))
    elapsed = time.perf_counter() - started
    return dict(users=users, calls_per_user=calls, concurrent_requests=users * calls,
                success=len(latencies), errors=errors, elapsed_ms=round(elapsed * 1000, 2),
                latency_p50_ms=percentile(latencies, .5), latency_p95_ms=percentile(latencies, .95),
                acquire_p95_ms=percentile(acquires, .95), throughput_rps=round(len(latencies) / elapsed, 2))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--users', default='1,2,5,10,20,50')
    parser.add_argument('--calls', default='1,4,8')
    parser.add_argument('--hold-ms', type=float, default=0, help='통제 실험용 연결 점유 시간; 실제 작업 아님')
    args = parser.parse_args()
    if args.hold_ms < 0 or any(n <= 0 for n in map(int, (args.users + ',' + args.calls).split(','))):
        parser.error('users/calls는 양수, hold-ms는 0 이상이어야 합니다')
    s = get_settings()
    results = []
    pool = await asyncpg.create_pool(s.supabase_db_url, min_size=s.db_pool_min_size,
                                    max_size=s.db_pool_max_size, timeout=s.ingest_db_timeout_seconds)
    try:
        for users in map(int, args.users.split(',')):
            for calls in map(int, args.calls.split(',')):
                result = await probe(pool, users, calls, s.ingest_db_timeout_seconds, args.hold_ms)
                results.append(result)
                print(json.dumps(result), flush=True)
    finally:
        await pool.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(workload='SELECT pg_sleep; synthetic hold' if args.hold_ms else 'SELECT 1; no model calls',
        hold_ms=args.hold_ms,
        pool_min=s.db_pool_min_size, pool_max=s.db_pool_max_size,
        timeout_seconds=s.ingest_db_timeout_seconds, results=results), indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main())
