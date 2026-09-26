"""DB 지연과 분리해 실제 reranker adapter의 단계별 기한을 검사한다."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.usage import UsageContext
from app.reg.hybrid import Candidate, SearchResult
from app.reg.reranker import candidate_id, rerank
from app.usage.repository import UsageWriteError


@pytest.fixture
def lifecycle(monkeypatch):
    snapshot = PublishedKnowledgeSnapshot.model_validate_json(
        (Path(__file__).parent / 'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    candidates = tuple(Candidate(c.card_id, c.card_version_id, b.block_id, .3, .4, .05)
                       for c in snapshot.cards for b in c.blocks)
    search = SearchResult(snapshot, 1, candidates, '합성 질문')
    ids = [candidate_id(c) for c in reversed(candidates)]
    state = NS(receipt=None, entered=asyncio.Event(), cancelled=asyncio.Event())

    async def start(receipt):
        state.receipt = receipt
        return 1

    async def finalize(attempt_id, receipt, *args):
        assert attempt_id == 1
        state.receipt = receipt

    async def generate(**kwargs):
        assert state.receipt.status == 'STARTED'
        return NS(text=json.dumps(dict(ids=ids)),
                  usage_metadata=NS(prompt_token_count=12, candidates_token_count=3, total_token_count=15))

    async def hang(*args, **kwargs):
        state.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            state.cancelled.set()

    sink = NS(start=AsyncMock(side_effect=start), finalize=AsyncMock(side_effect=finalize))
    sdk = NS(generate_content=AsyncMock(side_effect=generate))
    close = AsyncMock()
    monkeypatch.setattr('google.genai.Client', lambda **kw: NS(aio=NS(models=sdk, aclose=close)))
    monkeypatch.setattr('app.reg.reranker.get_settings',
                        lambda: NS(gemini_model='synthetic', gemini_api_key='synthetic'))
    monkeypatch.setattr('app.reg.reranker.provider_budget', lambda context, model: (context, None))
    context = UsageContext(store_id=snapshot.store_id, stage='RERANK', cost_phase='OPERATING',
                           logical_call_id='synthetic-reranker-lifecycle')

    async def run():
        # 실제 운영의 총 1초/정리 200ms 계산을 사용한다. 외부 5초는 테스트 교착 방지다.
        return await asyncio.wait_for(rerank(search, store_id=int(snapshot.store_id), question='합성 질문',
                                            context=context, sink=sink, timeout=1), 5)

    return NS(run=run, sink=sink, sdk=sdk, close=close, state=state, hang=hang, search=search)


async def assert_start_blocked(case):
    with pytest.raises(UsageWriteError):
        await case.run()
    case.sdk.generate_content.assert_not_awaited()
    case.sink.finalize.assert_not_awaited()
    case.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stalled_start_blocks_sdk_and_cancels_storage(lifecycle):
    lifecycle.sink.start.side_effect = lifecycle.hang
    await assert_start_blocked(lifecycle)
    assert lifecycle.state.cancelled.is_set()


@pytest.mark.asyncio
async def test_failed_start_blocks_sdk(lifecycle):
    lifecycle.sink.start.side_effect = OSError('synthetic DB failure')
    await assert_start_blocked(lifecycle)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['finalize', 'close'])
async def test_stalled_cleanup_preserves_ranking_without_rebilling(lifecycle, stage):
    target = lifecycle.sink.finalize if stage == 'finalize' else lifecycle.close
    target.side_effect = lifecycle.hang
    result = await lifecycle.run()
    assert result.rerank_status == 'APPLIED'
    assert result.candidates == tuple(reversed(lifecycle.search.candidates))
    assert lifecycle.state.cancelled.is_set()
    assert lifecycle.state.receipt.status == ('STARTED' if stage == 'finalize' else 'SUCCEEDED')
    lifecycle.sink.start.assert_awaited_once()
    lifecycle.sdk.generate_content.assert_awaited_once()
    lifecycle.sink.finalize.assert_awaited_once()
    lifecycle.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stalled_sdk_times_out_and_records_unknown_usage(lifecycle):
    lifecycle.sdk.generate_content.side_effect = lifecycle.hang
    result = await lifecycle.run()
    assert result.rerank_status == 'TIMEOUT'
    assert result.candidates == lifecycle.search.candidates
    assert lifecycle.state.cancelled.is_set()
    assert lifecycle.state.receipt.status == 'FAILED'
    assert lifecycle.state.receipt.usage.prompt_tokens is None
    lifecycle.sdk.generate_content.assert_awaited_once()
    lifecycle.sink.finalize.assert_awaited_once()
    lifecycle.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['start', 'sdk'])
async def test_caller_cancellation_propagates_and_stops_pending_work(lifecycle, stage):
    target = lifecycle.sink.start if stage == 'start' else lifecycle.sdk.generate_content
    target.side_effect = lifecycle.hang
    task = asyncio.create_task(lifecycle.run())
    try:
        await asyncio.wait_for(lifecycle.state.entered.wait(), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert lifecycle.state.cancelled.is_set()
    if stage == 'start':
        lifecycle.sdk.generate_content.assert_not_awaited()
        lifecycle.sink.finalize.assert_not_awaited()
    else:
        assert lifecycle.state.receipt.status == 'FAILED'
        lifecycle.sink.finalize.assert_awaited_once()
    lifecycle.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', ['{', '{"ids":["invented"]}'])
async def test_invalid_sdk_ranking_keeps_candidates_and_incurred_usage(lifecycle, payload):
    lifecycle.sdk.generate_content.side_effect = None
    lifecycle.sdk.generate_content.return_value = NS(text=payload,
        usage_metadata=NS(prompt_token_count=12, candidates_token_count=3, total_token_count=15))
    result = await lifecycle.run()
    assert result.rerank_status == 'FAILED'
    assert result.candidates == lifecycle.search.candidates
    assert lifecycle.state.receipt.status == 'FAILED'
    assert lifecycle.state.receipt.usage.prompt_tokens == 12
    lifecycle.sdk.generate_content.assert_awaited_once()
    lifecycle.close.assert_awaited_once()
