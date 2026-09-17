import pytest
from tests import test_r_planner as fixture
from tests.test_r_real_data_review import seed
from app.team.real_data_review import prepare_dev_review
from app.team.reviewed_manifest import finalize_review


def inputs(tmp_path):
    seed(tmp_path)
    review=prepare_dev_review(tmp_path,store='store-a')
    judgment=dict(meaning_id=review['cases'][0]['meaning_id'],question='HOT 라테 우유 얼마나?',
        expected_action='ANSWER', must_have=True, applicability='SPECIFIC',conditions=[],exceptions=[],
        scope_reason='합성 HOT 범위 확인',forbidden_claims=[],required_fact_revisions=['1'],
        reviewer='synthetic reviewer',reason='합성 승인 근거와 대조')
    return review, dict(review_hash=review['review_hash'], judgments=[judgment],
        snapshot=fixture.PlannerTest().search().snapshot,store_id=1,truth_version='synthetic-review/v1')


def test_complete_review_preserves_truth_provenance_and_snapshot(tmp_path):
    review,args=inputs(tmp_path)
    result=finalize_review(review,**args)
    assert result['manifest']['cases'][0]['required_facts']==['1']
    assert result['manifest']['cases'][0]['must_have'] is True
    assert result['mappings'][0]['required']==[dict(fact_id='1',fact_revision_id='1')]
    assert result['source_label_status']=='TEAM_TEST'
    assert result['semantic_accuracy'] is None and not result['production_promotion']


@pytest.mark.parametrize('fault',['missing','duplicate','foreign_question','foreign_revision','wrong_store',
                                 'stale','altered','unknown_scope','no_evidence','no_reviewer','null_conditions'])
def test_invalid_or_partial_reviews_cannot_start_evaluation(tmp_path,fault):
    review,args=inputs(tmp_path)
    row=args['judgments'][0]
    if fault=='missing': args['judgments']=[]
    if fault=='duplicate': args['judgments']*=2
    if fault=='foreign_question': row['meaning_id']='foreign'
    if fault=='foreign_revision': row['required_fact_revisions']=['999']
    if fault=='wrong_store': args['store_id']=2
    if fault=='stale': args['review_hash']='sha256:'+'0'*64
    if fault=='altered': review['cases'][0]['source_label']['value']='wrong'
    if fault=='unknown_scope': row['applicability']='UNDETERMINED'
    if fault=='no_evidence': row['required_fact_revisions']=[]
    if fault=='no_reviewer': row['reviewer']='  '
    if fault=='null_conditions': row['conditions']=None
    with pytest.raises(ValueError): finalize_review(review,**args)


def test_explicit_nonanswer_review_can_preserve_unresolved_scope(tmp_path):
    review,args=inputs(tmp_path)
    args['judgments'][0].update(expected_action='ESCALATE',applicability='UNDETERMINED',required_fact_revisions=[])
    result=finalize_review(review,**args)
    assert result['manifest']['cases'][0]['expected_action']=='ESCALATE'


def test_w_fact_priority_does_not_override_reviewed_r_question_priority(tmp_path):
    review,args=inputs(tmp_path)
    args['judgments'][0]['must_have']=False
    assert finalize_review(review,**args)['manifest']['cases'][0]['must_have'] is False


def test_question_suite_selection_is_explicit_and_omissions_recorded(tmp_path):
    import json
    directory,_,truth=seed(tmp_path)
    truth['facts'].append(dict(truth['facts'][0],fact_id='f2'))
    (directory/'truth/facts.json').write_text(json.dumps(truth),encoding='utf-8')
    review=prepare_dev_review(tmp_path,store='store-a')
    row=dict(meaning_id=review['cases'][0]['meaning_id'],question='합성 질문',expected_action='ESCALATE',
        must_have=False,applicability='UNDETERMINED',conditions=[],exceptions=[],scope_reason='합성 미확정',
        forbidden_claims=[],required_fact_revisions=[],reviewer='fixture',reason='합성 선택')
    args=dict(review_hash=review['review_hash'],judgments=[row],snapshot=fixture.PlannerTest().search().snapshot,
        store_id=1,truth_version='v1',selected_meaning_ids=[row['meaning_id']])
    with pytest.raises(ValueError,match='selection'): finalize_review(review,**args)
    result=finalize_review(review,**args,selection_reason='사전 고정한 합성 대표 질문')
    assert result['source_fact_count']==2 and len(result['manifest']['cases'])==1
    assert result['omitted_meaning_ids']==[review['cases'][1]['meaning_id']]


def test_raw_only_human_truth_keeps_exact_raw_mapping_without_fabricated_fact(tmp_path):
    from tests import test_r_raw_quantity as raw_fixture
    review,args=inputs(tmp_path)
    args['snapshot']=raw_fixture.search().snapshot
    args['judgments'][0].update(required_fact_revisions=[],required_raw_blocks=[dict(
        card_id='1',card_version_id='1',block_id='b',raw_span_id='1')])
    result=finalize_review(review,**args)
    assert result['manifest']['cases'][0]['required_facts']==[]
    assert result['manifest']['cases'][0]['required_raw_blocks']==args['judgments'][0]['required_raw_blocks']
    assert result['mappings'][0]['required']==[]
    assert result['mappings'][0]['required_raw_blocks']==args['judgments'][0]['required_raw_blocks']


@pytest.mark.parametrize('fault',['card_id','card_version_id','block_id','raw_span_id','duplicate'])
def test_raw_truth_rejects_stale_or_foreign_references(tmp_path,fault):
    from tests import test_r_raw_quantity as raw_fixture
    review,args=inputs(tmp_path)
    args['snapshot']=raw_fixture.search().snapshot
    raw=dict(card_id='1',card_version_id='1',block_id='b',raw_span_id='1')
    if fault!='duplicate':raw[fault]='999'
    args['judgments'][0].update(required_fact_revisions=[],required_raw_blocks=[raw,raw] if fault=='duplicate' else [raw])
    with pytest.raises(ValueError): finalize_review(review,**args)
