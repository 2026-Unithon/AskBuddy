"""원가 영수증 저장 — 답변 경로는 빠르게 포기, 추출 경로만 오래 버틴다.

R 답변(p95 5초, D21)이 같은 DbUsageSink 를 쓰므로 기본은 종전 동작(완료 0.2초×2회)이어야 한다.
추출 파이프라인만 resilient=True 로 긴 시간 제한·재시도를 쓴다.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.contracts.usage import UsageAttempt, UsageContext
from app.usage import recorder, repository


def _attempt():
    ctx = UsageContext(store_id="1", cost_phase="REGISTRATION", stage="EXTRACT",
                       logical_call_id="c1", attempt_no=1)
    return UsageAttempt(context=ctx, requested_model="m")


class _HangingPool:
    """acquire 가 끝나지 않는 풀(행 잠금·연결 정체 대역)."""

    def __init__(self):
        self.acquires = 0

    @asynccontextmanager
    async def acquire(self):
        self.acquires += 1
        await asyncio.sleep(3600)
        yield NS()


@pytest.mark.asyncio
async def test_default_finalize_gives_up_fast():
    pool = _HangingPool()
    started = time.monotonic()
    await repository.finalize_attempt(pool, 1, _attempt(), known_cost=None, cost=None,
                                      price_status="NO_RATE")
    assert time.monotonic() - started < 1.0          # 0.2초 × 2회
    assert pool.acquires == 2


@pytest.mark.asyncio
async def test_resilient_finalize_uses_ingest_timeout_and_retries():
    pool = _HangingPool()
    st = NS(ingest_db_timeout_seconds=0.05, ingest_stage_retries=2)
    with patch("app.config.get_settings", return_value=st), \
         patch("app.ingest.resilience.setting", side_effect=lambda k: getattr(st, k)), \
         patch("app.ingest.resilience.backoff", AsyncMock()):
        await repository.finalize_attempt(pool, 1, _attempt(), known_cost=None, cost=None,
                                          price_status="NO_RATE", resilient=True)
    assert pool.acquires == 3                          # 최초 + 재시도 2


@pytest.mark.asyncio
async def test_sink_default_start_does_not_retry():
    calls = []

    async def start(pool, attempt, **kw):
        calls.append(kw)
        raise asyncio.TimeoutError()
    with patch("app.usage.repository.start_attempt", start):
        with pytest.raises(asyncio.TimeoutError):
            await recorder.DbUsageSink(object()).start(_attempt())
    assert len(calls) == 1 and calls[0].get("timeout") is None


@pytest.mark.asyncio
async def test_sink_resilient_start_retries_with_timeout():
    calls = []

    async def start(pool, attempt, **kw):
        calls.append(kw)
        if len(calls) < 2:
            raise asyncio.TimeoutError()
        return 7
    st = NS(ingest_db_timeout_seconds=10.0, ingest_stage_retries=3)
    with patch("app.usage.repository.start_attempt", start), \
         patch("app.config.get_settings", return_value=st), \
         patch("app.ingest.resilience.setting", side_effect=lambda k: getattr(st, k)), \
         patch("app.ingest.resilience.backoff", AsyncMock()):
        got = await recorder.DbUsageSink(object(), resilient=True).start(_attempt())
    assert got == 7 and len(calls) == 2 and calls[0]["timeout"] == 10.0
