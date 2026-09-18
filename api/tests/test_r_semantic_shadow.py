from unittest.mock import AsyncMock, patch
import pytest
from app.learn.planner import decide
from app.team.evaluation_usage import evaluation_usage_scope
from app.team.semantic_shadow import observe_decision, semantic_shadow_scope
from app.team.semantic_review import semantic_report
from tests.test_r_semantic_proposals import case


@pytest.mark.asyncio
async def test_shadow_is_inert_in_product_and_resets_after_scope():
    with patch('app.team.semantic_shadow.propose', AsyncMock()) as provider:
        await observe_decision(pool=None, store_id=1, search=None, question='', user_turns=(),
            baseline=None, request_id='x', timeout=1)
        provider.assert_not_awaited()
    with pytest.raises(ValueError):
        with semantic_shadow_scope(store_id=1, record=AsyncMock()):
            pass


@pytest.mark.asyncio
async def test_shadow_binds_real_baseline_and_preserves_no_promotion():
    search, payload, raw = case()
    baseline = decide(search, store_id=1, question=payload['question'])
    rows = []
    async def record(row): rows.append(row)
    # No comparisons in this scope: regenerate matching input binding.
    from app.learn.semantic_proposals import proposal_input
    raw['input_hash'] = proposal_input(search, store_id=1, question=payload['question'])['input_hash']
    with evaluation_usage_scope(store_id=1, evaluation_run_id='1'):
        with semantic_shadow_scope(store_id=1, record=record, provider=AsyncMock(return_value=raw)):
            await observe_decision(pool=None, store_id=1, search=search, question=payload['question'],
                user_turns=(), baseline=baseline, request_id='x', timeout=1)
            with pytest.raises(ValueError):
                await observe_decision(pool=None, store_id=2, search=search, question='', user_turns=(),
                    baseline=baseline, request_id='x', timeout=1)
    assert rows[0]['baseline_plan'] == baseline.plan.model_dump(mode='json')
    report = semantic_report(rows)
    assert report['unreviewed'] == 1 and not report['production_eligible'] and report['cost'] is None
    with pytest.raises(ValueError): semantic_report(rows * 2)
    from copy import deepcopy
    from app.contracts.hashing import digest
    changed = deepcopy(rows[0])
    changed['input']['question'] = '바뀐 질문'
    changed['row_hash'] = digest({k: v for k, v in changed.items() if k != 'row_hash'})
    with pytest.raises(ValueError): semantic_report([changed])
    labels = [dict(row_hash=rows[0]['row_hash'], reviewer='human', reason='synthetic contract only',
        expected_action=baseline.plan.action, semantic_correct=False, false_block=False,
        false_merge=True, citation_error=False)]
    assert semantic_report(rows, labels)['false_merges'] == 1
    labels[0]['row_hash'] = 'sha256:' + '0'*64
    with pytest.raises(ValueError): semantic_report(rows, labels)
