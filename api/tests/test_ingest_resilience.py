"""재시도 과금 경계·동시 실행 제한·조립 분할 회귀."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from app.config import Settings
from app.contracts.usage import UsageContext
from app.ingest import resilience
from app.ingest.providers import measured, budget
from app.ingest.providers.types import CallResult
from app.ingest.raw_responses import RawResponseWriteError
from app.usage.repository import UsageWriteError


@pytest.fixture(autouse=True)
def config(monkeypatch):
    s = Settings(_env_file=None, ingest_retry_base_seconds=0)
    monkeypatch.setattr(resilience, 'get_settings', lambda: s)
    monkeypatch.setattr('app.config.get_settings', lambda: s)
    budget.set_limit(None)
    yield s
    budget.set_limit(None)


@pytest.mark.asyncio
async def test_four_attempts_then_failure():
    op = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        await resilience.retry_io(op, stage='test')
    assert op.await_count == 4


@pytest.mark.asyncio
async def test_permanent_errors_and_cancellation_are_not_retried():
    for exc in (ValueError(), asyncio.CancelledError()):
        op = AsyncMock(side_effect=exc)
        with pytest.raises(type(exc)):
            await resilience.retry_io(op, stage='test')
        assert op.await_count == 1


async def run(caller, sink=None, raw_sink=None):
    return await measured.measured_call(settings=NS(ingest_mode='real'), model='synthetic',
        caller=caller, prompt='test', media=[], schema=None, sink=sink,
        context=UsageContext(store_id='5', cost_phase='REGISTRATION', stage='EXTRACT',
                             logical_call_id='test'),
        prompt_hash=None, raw_sink=raw_sink, max_output_tokens=None)


@pytest.mark.asyncio
async def test_provider_retries_have_separate_receipts():
    caller = AsyncMock(side_effect=[TimeoutError(), TimeoutError(), TimeoutError(), CallResult('{}', {}, 'STOP')])
    sink = NS(start=AsyncMock(return_value=1), finalize=AsyncMock())
    await run(caller, sink)
    assert [c.args[0].context.attempt_no for c in sink.start.call_args_list] == [1, 2, 3, 4]
    assert [c.args[1].status for c in sink.finalize.call_args_list] == ['FAILED'] * 3 + ['SUCCEEDED']


@pytest.mark.asyncio
async def test_start_failure_does_not_call_provider():
    caller = AsyncMock()
    sink = NS(start=AsyncMock(side_effect=UsageWriteError('failed')), finalize=AsyncMock())
    with pytest.raises(UsageWriteError):
        await run(caller, sink)
    caller.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_save_retries_do_not_repeat_paid_call():
    from app.ingest import raw_responses
    caller = AsyncMock(return_value=CallResult('{}', {}, 'STOP'))
    sink = NS(save=AsyncMock(side_effect=[TimeoutError()] * 3 + [12]))
    # 재사용 키와 조회 대신 저장 경계에 집중한다.
    with patch('app.ingest.reuse.key_for', AsyncMock(return_value='key')), \
         patch('app.ingest.reuse.lookup_allowed', return_value=False):
        result = await run(caller, raw_sink=sink)
    assert result.raw_response_id == 12
    assert caller.await_count == 1 and sink.save.await_count == 4


@pytest.mark.asyncio
async def test_global_limit_under_400_requests():
    active = peak = 0
    @resilience.limited('ingest_model_concurrency')
    async def one():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.001)
        finally:
            active -= 1
    await asyncio.gather(*(one() for _ in range(400)))
    assert peak == 4 and active == 0
    await one()  # 종료 뒤 permit 회수


@pytest.mark.asyncio
async def test_assembly_batches_keep_subject_variants_together(config):
    from app.ingest import pipeline
    from app.ingest.schemas import ExtractedAssertion, ExtractionResult
    config.assemble_batch_facts = 3
    facts = [ExtractedAssertion(local_ref=f'f{i}', original_assertion='합성', subject=subject,
        variant=str(i), attribute='양', value=str(i), confidence=.9)
        for i, subject in enumerate(['A','B','A','B','C','C'])]
    call = AsyncMock(return_value=ExtractionResult(cards=[], unresolved=[]))
    with patch.object(pipeline, 'get_settings', return_value=config), patch('app.ingest.extract.assemble_cards', call):
        await pipeline.assemble_assertions(source_id=1, assertions=facts, categories=[], glossary=[],
                                          usage_base=(5, None, 'REGISTRATION', 'EVALUATION', 1, None))
    assert [len(c.kwargs['facts']) for c in call.call_args_list] == [2, 2, 2]
    assert len({c.kwargs['usage_context'].logical_call_id for c in call.call_args_list}) == 3
    assert [{f['대상'] for f in c.kwargs['facts']} for c in call.call_args_list] == [{'A'}, {'B'}, {'C'}]


@pytest.mark.asyncio
async def test_db_start_retries_without_spending_and_stops_on_duplicate():
    from app.usage.recorder import DbUsageSink
    for errors, expected in (([TimeoutError()] * 3 + [7], 4),
                             ([TimeoutError(), UsageWriteError('duplicate')], 2)):
        start = AsyncMock(side_effect=errors)
        # 추출 파이프라인이 쓰는 resilient sink 만 시작 receipt 를 재시도한다
        sink = DbUsageSink(object(), resilient=True)
        caller = AsyncMock(return_value=CallResult('{}', {}, 'STOP'))
        with patch('app.usage.repository.start_attempt', start), \
             patch('app.usage.repository.finalize_attempt', AsyncMock()):
            if expected == 4:
                await run(caller, sink)
                assert caller.await_count == 1
            else:
                with pytest.raises(UsageWriteError):
                    await run(caller, sink)
                caller.assert_not_awaited()
        assert start.await_count == expected


@pytest.mark.asyncio
async def test_gate_returns_permit_after_cancellation(config):
    config.ingest_model_concurrency = 1
    entered = asyncio.Event()
    @resilience.limited('ingest_model_concurrency')
    async def wait():
        entered.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(wait())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(1):
        async with resilience.gate('ingest_model_concurrency', 1):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize('code, attempts', [(402, 1), (401, 1), (400, 1), (429, 4), (503, 4)])
async def test_http_retry_classification(code, attempts):
    from google.genai.errors import ClientError, ServerError
    error_type = ServerError if code >= 500 else ClientError
    error = error_type(code, {'error': {'code': code, 'message': 'synthetic'}})
    caller = AsyncMock(side_effect=error)
    with pytest.raises(error_type):
        await run(caller)
    assert caller.await_count == attempts
