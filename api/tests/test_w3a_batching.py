"""W3-1b — 배치 동시 실행기·설정 키·옛 조립의 동시화 (합성 대역만 쓴다)."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ingest import pipeline
from app.ingest.batching import gather_in_order
from app.ingest.schemas import ExtractedAssertion, ExtractedCard, ExtractionResult

USAGE_BASE = (3, None, "REGISTRATION", "PRODUCT", None, None)


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


def test_settings_fact_assembly_requires_entity_revision():
    base = Settings(_env_file=None)
    assert base.w_fact_assembly_enabled is False and base.assemble_concurrency == 1
    with pytest.raises(ValidationError, match="w_fact_assembly_enabled requires w_entity_revision_enabled"):
        Settings(_env_file=None, w_fact_assembly_enabled=True)
    ok = Settings(_env_file=None, w_fact_assembly_enabled=True, w_entity_revision_enabled=True)
    assert ok.w_fact_assembly_enabled is True
    with pytest.raises(ValidationError):
        Settings(_env_file=None, assemble_concurrency=0)


def _facts():
    return [ExtractedAssertion(local_ref=f"f{i}", original_assertion="합성", subject=s,
                               variant=str(i), attribute="양", value=str(i), confidence=.9)
            for i, s in enumerate(["A", "B", "C"])]


def _recorder(delays=None, fail_on=None):
    calls, state = [], {"running": 0, "peak": 0}

    async def fake(**kwargs):
        index = len(calls)
        calls.append(kwargs)
        state["running"] += 1
        state["peak"] = max(state["peak"], state["running"])
        try:
            await asyncio.sleep((delays or [0, 0, 0])[index])
            if fail_on is not None and kwargs["usage_context"].segment_id == f"batch{fail_on}":
                raise ValueError(f"실패{fail_on}")
            return ExtractionResult(cards=[ExtractedCard(
                category_name="합성", title=kwargs["facts"][0]["대상"], content="합성", confidence=.9)],
                unresolved=[])
        finally:
            state["running"] -= 1
    return fake, calls, state


async def _run(settings, fake, strict=True):
    with patch.object(pipeline, "get_settings", return_value=settings), \
            patch("app.ingest.extract.assemble_cards", fake):
        return await pipeline.assemble_assertions(
            source_id=1, assertions=_facts(), categories=[], glossary=[],
            usage_base=USAGE_BASE, strict=strict)


def _segments(calls):
    return [c["usage_context"].segment_id for c in calls]


@pytest.mark.asyncio
async def test_assemble_assertions_serial_default_unchanged():
    fake, calls, state = _recorder()
    result = await _run(NS(assemble_batch_facts=1), fake)
    assert _segments(calls) == ["batch0", "batch1", "batch2"]
    assert [c.title for c in result.cards] == ["A", "B", "C"] and state["peak"] == 1

    fake, calls, _ = _recorder(fail_on=1)
    with pytest.raises(RuntimeError, match="카드 조립 실패"):
        await _run(NS(assemble_batch_facts=1), fake)
    assert _segments(calls) == ["batch0", "batch1"]  # 세 번째는 부르지 않는다


@pytest.mark.asyncio
async def test_assemble_assertions_concurrent_same_result():
    serial_fake, serial_calls, _ = _recorder()
    serial = await _run(NS(assemble_batch_facts=1), serial_fake)
    fake, calls, state = _recorder(delays=[.03, .02, .01])
    result = await _run(NS(assemble_batch_facts=1, assemble_concurrency=3), fake)
    assert [c.title for c in result.cards] == [c.title for c in serial.cards] == ["A", "B", "C"]
    assert state["peak"] == 3
    by_segment = {c["usage_context"].segment_id: c for c in calls}
    for call in serial_calls:
        other = by_segment[call["usage_context"].segment_id]
        assert other["facts"] == call["facts"]
        assert other["usage_context"] == call["usage_context"]
        assert other["source_id"] == call["source_id"]


@pytest.mark.asyncio
async def test_assemble_assertions_concurrent_failure_same_meaning():
    settings = NS(assemble_batch_facts=1, assemble_concurrency=3)
    fake, calls, _ = _recorder(fail_on=1)
    with pytest.raises(RuntimeError, match="카드 조립 실패") as info:
        await _run(settings, fake)
    assert isinstance(info.value.__cause__, ValueError) and str(info.value.__cause__) == "실패1"
    assert len(calls) == 3

    fake, _, _ = _recorder(fail_on=1)
    result = await _run(settings, fake, strict=False)
    assert result.cards == []
    assert result.unresolved == [f"조립 실패: {ValueError('실패1')}"]
