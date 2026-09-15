"""DB 원자 유입 제한. 모델 호출 중 lock/connection을 유지하지 않는다."""
from contextlib import asynccontextmanager
from uuid import uuid4
import asyncio
from app.config import get_settings
from app.errors import ApiError


@asynccontextmanager
async def request_lease(pool, store_id: int, user_id: int):
    settings = get_settings()
    request_id = uuid4()
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute("select pg_advisory_xact_lock(hashtextextended($1,0))", f"r-request:{store_id}")
            await db.execute("delete from r_request_leases where store_id=$1 and started_at<clock_timestamp()-interval '30 days'", store_id)
            counts = await db.fetchrow("""
                select count(*) as store_count,
                  count(*) filter(where user_id=$2) as member_count,
                  count(*) filter(where finished_at is null and expires_at>clock_timestamp()) as store_active,
                  count(*) filter(where user_id=$2 and finished_at is null and expires_at>clock_timestamp()) as member_active
                from r_request_leases where store_id=$1 and started_at>clock_timestamp()-interval '1 minute'
            """, store_id, user_id)
            limits = (settings.request_store_per_minute, settings.request_member_per_minute,
                      settings.request_store_concurrency, settings.request_member_concurrency)
            if any(counts[key] >= limit for key, limit in zip(
                    ("store_count", "member_count", "store_active", "member_active"), limits)):
                raise ApiError(429, "RATE_LIMITED", "잠시 후 다시 질문해 주세요.", retryable=True,
                               details={"retry_after_ms": 60000})
            await db.execute("""
                insert into r_request_leases(request_id,store_id,user_id,expires_at)
                values($1,$2,$3,clock_timestamp()+$4*interval '1 second')
            """, request_id, store_id, user_id, settings.chat_deadline_seconds)
    try:
        yield str(request_id)
    finally:
        # 프로세스 종료/DB 장애에도 expires_at이 동시 실행 슬롯을 회수한다.
        try:
            async with asyncio.timeout(.2), pool.acquire() as db:
                await db.execute("""update r_request_leases set finished_at=clock_timestamp()
                    where request_id=$1 and store_id=$2 and user_id=$3 and finished_at is null""",
                    request_id, store_id, user_id)
        except Exception:
            pass
