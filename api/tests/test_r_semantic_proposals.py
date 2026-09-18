import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.contracts.usage import UsageContext
from app.learn.semantic_proposals import (
    ComparisonQuestion, compare_proposal, proposal_input, propose, validate_proposal,
)
from app.learn.planner import decide
from app.usage.recorder import NullSink
from app.usage.repository import UsageWriteError
from tests.test_r_raw_original import search


def case():
    result = search()
    question = result.snapshot.cards[0].title + ' 승인 원문 보여줘'
    payload = proposal_input(result, store_id=1, question=question,
        comparisons=(ComparisonQuestion(question_id='1', question='다른 질문'),))
    raw = dict(snapshot_hash=result.snapshot.snapshot_hash, input_hash=payload['input_hash'],
        plan=decide(result, store_id=1, question=question).plan.model_dump(mode='json'))
    return result, payload, raw


def test_valid_references_still_require_human_semantic_review():
    result, payload, raw = case()
    comparison = compare_proposal(result, payload=payload, raw=raw)
    assert comparison.status == 'REVIEW_REQUIRED'
    assert comparison.production_eligible is False
    assert not hasattr(comparison, 'resolved')
    assert not hasattr(comparison, 'semantic_context')


@pytest.mark.parametrize('change', ['hash', 'input', 'revision', 'candidate', 'quote', 'group', 'assessment'])
def test_untrusted_model_cannot_cross_boundaries(change):
    result, payload, raw = case()
    if change == 'hash': raw['snapshot_hash'] = 'sha256:' + '0' * 64
    if change == 'input': raw['input_hash'] = 'sha256:' + '0' * 64
    if change == 'revision': raw['plan']['knowledge_revision'] = '999'
    if change == 'candidate': result = replace(result, candidates=())
    if change == 'quote': raw['slots'] = [dict(slot='condition', value='주말', question_quote='없는 조건')]
    if change == 'group': raw['equivalent_question_ids'] = ['999']
    if change == 'assessment': raw['assessment'] = dict(approved=True)
    with pytest.raises(ValueError): validate_proposal(raw, result, payload)


def test_same_text_in_different_user_context_has_different_binding():
    result, _, _ = case()
    a = proposal_input(result, store_id=1, question='그럼 따뜻한 건?', user_turns=('음료 A',))
    b = proposal_input(result, store_id=1, question='그럼 따뜻한 건?', user_turns=('음료 B',))
    assert a['input_hash'] != b['input_hash']


def test_quote_does_not_confirm_model_interpretation_or_grouping():
    result, payload, raw = case()
    raw['slots'] = [dict(slot='condition', value='모델의 잘못된 해석', question_quote=payload['question'])]
    raw['equivalent_question_ids'] = ['1']
    outcome = compare_proposal(result, payload=payload, raw=raw)
    assert outcome.status == 'REVIEW_REQUIRED' and outcome.production_eligible is False


def kwargs():
    return dict(store_id=1, question='제목 없이 적힌 업무는 어떻게 하나요?', sink=object(),
        context=UsageContext(store_id='1', stage='ANSWER', cost_phase='OPERATING',
            cost_purpose='EVALUATION', evaluation_run_id='1', logical_call_id='proposal-test'))


@pytest.mark.asyncio
async def test_bad_json_and_timeout_never_fall_back_to_model_answer():
    async def invalid(*args, **kw): return {'answer': '새 사실'}
    async def slow(*args, **kw): await asyncio.sleep(1)
    assert (await propose(search(), provider=invalid, **kwargs())).status == 'FAILED'
    assert (await propose(search(), provider=slow, timeout=.01, **kwargs())).status == 'TIMEOUT'


@pytest.mark.asyncio
async def test_usage_failure_is_not_knowledge_miss():
    async def failed(*args, **kw): raise UsageWriteError('unavailable')
    with pytest.raises(UsageWriteError): await propose(search(), provider=failed, **kwargs())


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('store_id', 2), ('sink', NullSink())])
async def test_authority_checked_before_provider(field, value):
    values = kwargs()
    values[field] = value
    async def forbidden(*args, **kw): pytest.fail('provider called')
    with pytest.raises(ValueError): await propose(search(), provider=forbidden, **values)


@pytest.mark.asyncio
async def test_product_usage_cannot_enable_experimental_provider():
    values = kwargs()
    values['context'] = values['context'].model_copy(update={'cost_purpose': 'PRODUCT'})
    with pytest.raises(ValueError): await propose(search(), **values)


@pytest.mark.asyncio
@pytest.mark.parametrize('start_fails', [False, True])
async def test_sdk_call_follows_durable_usage_start(monkeypatch, start_fails):
    from app.learn.semantic_proposals import _generate
    from google import genai
    events = []
    async def response(**kw):
        events.append('provider')
        return SimpleNamespace(text=json.dumps({'synthetic': True}), usage_metadata=SimpleNamespace(
            prompt_token_count=12, candidates_token_count=3, cached_content_token_count=0,
            thoughts_token_count=0))
    class Sink:
        async def start(self, receipt):
            events.append('start')
            if start_fails:
                raise RuntimeError('database unavailable')
            assert receipt.context.cost_purpose == 'EVALUATION'
            return 1
        async def finalize(self, receipt_id, receipt, *args):
            events.append('finalize')
            assert receipt.usage.prompt_tokens == 12
            assert receipt.context.evaluation_run_id == '1'
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=response), aclose=AsyncMock()))
    client.aio.models.count_tokens=AsyncMock(return_value=SimpleNamespace(total_tokens=12))
    budget=SimpleNamespace(policy=SimpleNamespace(max_prompt_bytes=200000,max_input_tokens=1000,max_output_tokens=100),
        reserve=AsyncMock(return_value='reservation'),finish=AsyncMock())
    monkeypatch.setattr('app.learn.semantic_proposals.current_budget',lambda *args:budget)
    monkeypatch.setattr(genai, 'Client', lambda **kw: client)
    monkeypatch.setattr('app.learn.semantic_proposals.get_settings', lambda: SimpleNamespace(gemini_api_key='synthetic', gemini_model='synthetic'))
    if start_fails:
        with pytest.raises(UsageWriteError):
            await _generate('synthetic', context=kwargs()['context'], sink=Sink(), cleanup_budget=.2)
        assert events == ['start']
    else:
        assert await _generate('synthetic', context=kwargs()['context'], sink=Sink(), cleanup_budget=.2) == {'synthetic': True}
        assert events == ['start', 'provider', 'finalize']
    client.aio.aclose.assert_awaited_once()
