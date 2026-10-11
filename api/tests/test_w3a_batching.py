"""W3-1b — 배치 동시 실행기·설정 키 (합성 대역만 쓴다)."""
import asyncio

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ingest.batching import gather_in_order


@pytest.mark.asyncio
async def test_gather_in_order_keeps_input_order():
    def make(i, delay):
        async def call():
            await asyncio.sleep(delay)
            return i
        return call
    result = await gather_in_order([make(0, .03), make(1, .02), make(2, .01)], concurrency=3)
    assert result == [0, 1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency,expected", [(2, 2), (1, 1)])
async def test_gather_in_order_limits_concurrency(concurrency, expected):
    running, peak = 0, 0

    async def call():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(.01)
        running -= 1
    await gather_in_order([call] * 6, concurrency=concurrency)
    assert peak == expected


@pytest.mark.asyncio
async def test_gather_in_order_captures_exceptions_in_place():
    called = []

    def make(i):
        async def call():
            called.append(i)
            if i == 1:
                raise ValueError("boom")
            return i + 1
        return call
    for concurrency in (1, 3):
        called.clear()
        result = await gather_in_order([make(0), make(1), make(2)], concurrency=concurrency)
        assert result[0] == 1 and result[2] == 3
        assert isinstance(result[1], ValueError)
        assert sorted(called) == [0, 1, 2]
    assert await gather_in_order([], concurrency=3) == []


@pytest.mark.asyncio
async def test_gather_in_order_serial_when_one():
    order, running, overlap = [], 0, False

    def make(i):
        async def call():
            nonlocal running, overlap
            running += 1
            overlap = overlap or running > 1
            order.append(i)
            await asyncio.sleep(.005)
            running -= 1
        return call
    await gather_in_order([make(i) for i in range(3)], concurrency=1)
    assert order == [0, 1, 2] and not overlap


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 3])
async def test_gather_in_order_propagates_cancel(concurrency):
    async def ok():
        return 1

    async def cancelled():
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await gather_in_order([ok, cancelled, ok], concurrency=concurrency)


def test_settings_assemble_concurrency_bounds():
    assert Settings(_env_file=None).assemble_concurrency == 1
    with pytest.raises(ValidationError):
        Settings(_env_file=None, assemble_concurrency=0)
