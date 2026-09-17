import pytest
from tests import test_r_raw_quantity as fixture
from app.team.retrieval_pool import build_retrieval_pool
from app.team.evidence_truth import evidence_recall
from app.team.oracle_diagnostics import diagnose_oracle


def inputs():
    snapshot=fixture.search().snapshot
    pool=build_retrieval_pool(snapshot=snapshot,question_id='raw-q',question='HOT 라테 우유 얼마나?',
        channels=dict(lexical=[],vector=[],oracle=[['1','1','b']]),sample_size=0,seed='synthetic')
    truth=dict(pool_hash=pool['pool_hash'],truth_version='synthetic/v1',reviewer='fixture',reason='합성 RAW 근거',
        required_raw=[dict(meaning_id='raw-milk',card_id='1',card_version_id='1',block_id='b',raw_span_id='1')])
    return pool,truth


def test_raw_recall_and_oracle_do_not_create_typed_fact_denominator():
    pool,truth=inputs()
    miss=evidence_recall(pool,truth,[])
    assert miss['fact_recall_at_k'] is None and miss['raw_recall_at_k']==0
    assert not miss['complete_evidence_at_k']
    found=evidence_recall(pool,truth,[['1','1','b']])
    assert found['raw_recall_at_k']==1 and found['complete_evidence_at_k']
    assert found['meaning_coverage']=={'raw-milk':True}
    assert found['required_fact_details']==[]
    report=diagnose_oracle(pool,truth,[])
    assert report['retrieved']['action']=='ESCALATE'
    assert report['oracle_injected']['action']=='ANSWER'
    assert report['oracle_injected']['semantic_correct'] is None
    assert report['oracle_references']==[['1','1','b']]


@pytest.mark.parametrize('fault',['card_version_id','raw_span_id','block_id','duplicate','empty'])
def test_raw_evidence_rejects_stale_refs_and_empty_or_duplicate_truth(fault):
    pool,truth=inputs()
    if fault=='duplicate':truth['required_raw']*=2
    elif fault=='empty':truth['required_raw']=[]
    else:truth['required_raw'][0][fault]='999'
    with pytest.raises(ValueError):evidence_recall(pool,truth,[['1','1','b']])


def test_raw_excluded_from_current_eligible_universe_is_not_valid_truth():
    original,truth=inputs()
    from app.contracts.snapshot import PublishedKnowledgeSnapshot
    snapshot=PublishedKnowledgeSnapshot.model_validate(original['snapshot'])
    pool=build_retrieval_pool(snapshot=snapshot,question_id='raw-q',question='HOT 라테 우유 얼마나?',
        channels=dict(lexical=[],vector=[],oracle=[]),sample_size=0,seed='synthetic',eligible_references=[])
    truth['pool_hash']=pool['pool_hash']
    with pytest.raises(ValueError,match='eligible'):evidence_recall(pool,truth,[])


def test_mixed_raw_and_typed_truth_requires_both_kinds():
    from tests import test_r_planner as typed_fixture
    from app.contracts.snapshot import PublishedKnowledgeSnapshot
    from app.contracts.hashing import snapshot_digest
    payload=fixture.search().snapshot.model_dump(mode='json')
    payload['fact_revisions']=[typed_fixture.PlannerTest().search().snapshot.fact_revisions[0].model_dump(mode='json')]
    payload['cards'][0]['blocks'].append(dict(block_id='typed',kind='QUANTITIES',order=2,fact_revision_ids=['1']))
    snapshot=PublishedKnowledgeSnapshot.model_validate(payload)
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    pool=build_retrieval_pool(snapshot=snapshot,question_id='mixed',question='합성 질문',
        channels=dict(lexical=[],vector=[],oracle=[['1','1','b'],['1','1','typed']]),sample_size=0,seed='synthetic')
    _,truth=inputs()
    truth.update(pool_hash=pool['pool_hash'],required=[dict(meaning_id='typed-milk',fact_id='1',fact_revision_id='1')])
    partial=evidence_recall(pool,truth,[['1','1','b']])
    assert partial['raw_recall_at_k']==1 and partial['fact_recall_at_k']==0
    assert not partial['complete_evidence_at_k']
    assert evidence_recall(pool,truth,[['1','1','b'],['1','1','typed']])['complete_evidence_at_k']
    truth['required'][0]['meaning_id']='raw-milk'
    with pytest.raises(ValueError):evidence_recall(pool,truth,[])
