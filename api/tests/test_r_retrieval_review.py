import copy
import json
from pathlib import Path

import pytest

from app.contracts.hashing import digest
from app.team.retrieval_pool import build_retrieval_pool
from app.team.retrieval_review import review_retrieval


@pytest.fixture
def reviewed():
    snapshot=json.loads((Path(__file__).parent/'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    pool=build_retrieval_pool(snapshot=snapshot,question_id='q1',question='합성 질문',
        channels=dict(lexical=[],vector=[],oracle=[]),sample_size=100,seed='fixed')
    refs=[row['reference'] for row in pool['entries']]
    judgments=[dict(pool_hash=pool['pool_hash'],reference=ref,relevance='RELEVANT' if i==0 else 'IRRELEVANT',
        reviewer='synthetic',reason='synthetic fixture') for i,ref in enumerate(refs)]
    return dict(pool=pool,judgments=judgments,rankings=dict(test=[refs[1],refs[0]]),k=2)


def test_complete_binary_metrics(reviewed):
    report=review_retrieval(**reviewed)
    assert report['relevance_complete']
    score=report['metrics']['test']
    assert score['recall_at_k']==1
    assert score['precision_at_k']==.5
    assert score['mrr']==.5
    assert score['ndcg_at_k']==pytest.approx(.6309297536)


def test_unjudged_outside_top_keeps_recall_unknown(reviewed):
    reviewed['judgments']=reviewed['judgments'][:2]
    report=review_retrieval(**reviewed)
    assert report['metrics']['test']['precision_at_k']==.5
    assert report['metrics']['test']['recall_at_k'] is None
    assert report['metrics']['test']['mrr'] is None


def test_no_relevant_denominator_is_not_perfect_score(reviewed):
    for row in reviewed['judgments']: row['relevance']='IRRELEVANT'
    report=review_retrieval(**reviewed)
    assert report['relevance_complete']
    assert report['metrics']['test']['recall_at_k'] is None


@pytest.mark.parametrize('fault',['foreign','duplicate','tamper','forged','rank_duplicate','unknown'])
def test_bad_review_never_silently_passes(reviewed,fault):
    args=copy.deepcopy(reviewed)
    if fault=='foreign': args['judgments'][0]['pool_hash']='other'
    elif fault=='duplicate': args['judgments'].append(args['judgments'][0])
    elif fault in ('tamper','forged'):
        args['pool']['entries'][0]['relevance']=True
        if fault=='forged': args['pool']['pool_hash']=digest({k:v for k,v in args['pool'].items() if k!='pool_hash'})
    elif fault=='rank_duplicate': args['rankings']['test']*=2
    else: args['judgments'][0]['relevance']=True
    with pytest.raises(ValueError): review_retrieval(**args)
