import pytest

from tests import test_r_planner as planner_fixture
from app.contracts.answer import AnswerPlan, SelectedBlock
from app.learn.answer_validation import ResolvedSelection
from app.team.retrieval_pool import build_retrieval_pool
from app.team.evidence_truth import evidence_recall
from app.team.oracle_diagnostics import diagnose_oracle, diagnose_validator


def inputs():
    snapshot=planner_fixture.PlannerTest().search().snapshot
    pool=build_retrieval_pool(snapshot=snapshot,question_id='q1',question='HOT 라테 우유 얼마나?',
        channels=dict(lexical=[],vector=[],oracle=[['1','1','b']]),sample_size=10,seed='fixed')
    truth=dict(pool_hash=pool['pool_hash'],truth_version='synthetic/v1',reviewer='fixture',reason='합성 사실',
        required=[dict(meaning_id='latte.hot.milk',fact_id='1',fact_revision_id='1')])
    return snapshot,pool,truth


def test_missed_retrieval_vs_oracle_answer():
    _,pool,truth=inputs()
    report=diagnose_oracle(pool,truth,[])
    assert not report['retrieval_only']['complete_evidence_at_k']
    assert report['retrieved']['action']=='ESCALATE'
    assert report['oracle_injected']['action']=='ANSWER'
    assert report['oracle_injected']['semantic_correct'] is None
    assert evidence_recall(pool,truth,[['1','1','b']])['fact_recall_at_k']==1


@pytest.mark.parametrize('fault',['pool','fact','meaning_duplicate','foreign_rank'])
def test_truth_is_not_silently_remapped(fault):
    _,pool,truth=inputs()
    rank=[['1','1','b']]
    if fault=='pool': truth['pool_hash']='other'
    elif fault=='fact': truth['required'][0]['fact_id']='2'
    elif fault=='meaning_duplicate': truth['required']*=2
    else: rank=[['1','2','b']]
    with pytest.raises(ValueError): evidence_recall(pool,truth,rank)


def test_validator_diagnostic_keeps_false_candidate_off_runtime():
    snapshot,_,_=inputs()
    plan=AnswerPlan(snapshot_id='1',knowledge_revision='1',action='ANSWER',selected_blocks=(
        SelectedBlock(card_id='1',card_version_id='1',block_id='b',fact_revision_ids=('1',)),))
    result=diagnose_validator(plan,snapshot,ResolvedSelection('1','location',(('HOT',None),)),store_id=1)
    assert not result['validator_passed']
    assert result['semantic_correct'] is None
