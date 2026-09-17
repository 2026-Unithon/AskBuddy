import copy
import json
from pathlib import Path

import pytest

from app.team.retrieval_pool import build_retrieval_pool


@pytest.fixture
def request_data():
    snapshot = json.loads((Path(__file__).parent / 'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    refs = [[c['card_id'], c['card_version_id'], b['block_id']]
            for c in snapshot['cards'] for b in c['blocks']]
    assert len(refs) >= 3
    return dict(snapshot=snapshot, question_id='q1', question='우유는 얼마나 넣나요?',
        channels=dict(lexical=[refs[0]], vector=[refs[0], refs[1]], oracle=[refs[2]]),
        sample_size=1, seed='fixed-before-review')


def test_union_keeps_ranks_and_does_not_label_oracle(request_data):
    result = build_retrieval_pool(**request_data)
    assert result['pooled_size'] == 3
    row = next(r for r in result['entries'] if r['reference'] == request_data['channels']['lexical'][0])
    assert row['channel_ranks'] == {'lexical': 1, 'vector': 1}
    assert all(r['relevance'] is None for r in result['entries'])
    assert result['truth_status'] == 'UNREVIEWED'
    assert result['production_promotion'] is False


def test_unretrieved_sampling_is_reproducible_and_disjoint(request_data):
    request_data['channels'] = dict(lexical=[], vector=[], oracle=[])
    a = build_retrieval_pool(**request_data)
    assert a == build_retrieval_pool(**request_data)
    assert len(a['entries']) == 1
    assert a['entries'][0]['unpooled_sample']
    assert not a['entries'][0]['channel_ranks']
    assert a['unreviewed_outside_pool'] == a['universe_size'] - 1
    request_data['sample_size'] = 1000
    b = build_retrieval_pool(**request_data)
    assert b['unreviewed_outside_pool'] == 0
    assert len(b['entries']) == b['universe_size']


def test_current_eligibility_limits_samples_and_oracle(request_data):
    ref = request_data['channels']['lexical'][0]
    request_data['eligible_references'] = [ref]
    request_data['channels'] = dict(lexical=[], vector=[], oracle=[])
    result = build_retrieval_pool(**request_data)
    assert result['universe_size'] == 1
    assert result['entries'][0]['reference'] == ref
    request_data['eligible_references'] = []
    assert build_retrieval_pool(**request_data)['entries'] == []
    request_data['channels']['oracle'] = [ref]
    with pytest.raises(ValueError,match='foreign'):
        build_retrieval_pool(**request_data)


@pytest.mark.parametrize('change', ['duplicate', 'foreign_version', 'missing_channel', 'bool_sample', 'hash'])
def test_rejects_invalid_inputs(request_data, change):
    data = copy.deepcopy(request_data)
    if change == 'duplicate':
        data['channels']['lexical'] *= 2
    elif change == 'foreign_version':
        data['channels']['lexical'][0][1] = '999999'
    elif change == 'missing_channel':
        del data['channels']['oracle']
    elif change == 'bool_sample':
        data['sample_size'] = True
    else:
        data['snapshot']['snapshot_hash'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError):
        build_retrieval_pool(**data)
