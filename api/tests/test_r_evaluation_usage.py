from unittest.mock import AsyncMock

import pytest

from app.contracts.usage import UsageAttempt,UsageContext
from app.team.evaluation_usage import EvaluationUsageSink


def attempt():
    return UsageAttempt(context=UsageContext(store_id='1',cost_phase='OPERATING',stage='QUERY',logical_call_id='call'),
        requested_model='synthetic',mode='mock')


@pytest.mark.asyncio
async def test_evaluation_is_explicit_and_preserves_product_context():
    original=attempt()
    sink=AsyncMock()
    sink.start.return_value=1
    wrapper=EvaluationUsageSink(sink,store_id=1,evaluation_run_id='10')
    await wrapper.start(original)
    await wrapper.finalize(1,original,None,None,'UNKNOWN_UNITS')
    assert original.context.cost_purpose=='PRODUCT'
    assert sink.start.call_args.args[0].context.cost_purpose=='EVALUATION'
    assert sink.finalize.call_args.args[1].context.evaluation_run_id=='10'
    assert sink.finalize.call_args.args[1].context.logical_call_id=='call'


@pytest.mark.asyncio
async def test_foreign_attempt_and_store_rejected():
    sink=AsyncMock()
    wrapper=EvaluationUsageSink(sink,store_id=2,evaluation_run_id='10')
    with pytest.raises(ValueError): await wrapper.start(attempt())
    sink.start.assert_not_called()
    wrapper=EvaluationUsageSink(sink,store_id=1,evaluation_run_id='10')
    with pytest.raises(ValueError): await wrapper.finalize(9,attempt(),None,None,'UNKNOWN_UNITS')
    sink.finalize.assert_not_called()
