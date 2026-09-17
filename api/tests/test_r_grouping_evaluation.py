import copy
import pytest
from app.team.grouping_evaluation import evaluate_grouping,pair_hash


def cases():
    return [dict(question_id=str(i),store_id='1',snapshot_hash='sha256:'+'0'*64,
        question=question,confirmed_context={}) for i,question in enumerate(
            ('ICE 라테 우유 얼마나?','라테 ICE 우유 양?','ICE 라테 가격 얼마야?'))]


def labels(rows):
    return [dict(left=str(a),right=str(b),pair_hash=pair_hash(rows[a],rows[b]),
        should_share_pending=(a,b)==(0,1),reviewer='fixture',reason='합성 의미 판정')
        for a,b in ((0,1),(0,2),(1,2))]


def test_precise_groups_and_false_merges_are_distinct():
    rows=cases()
    good=evaluate_grouping(rows,{'0':'milk','1':'milk','2':'price'},labels(rows))
    assert good['precision']==good['recall']==1
    assert good['pair_count']==3 and good['false_merge']==0
    bad=evaluate_grouping(rows,{'0':'all','1':'all','2':'all'},labels(rows))
    assert bad['false_merge']==2 and bad['precision']==1/3 and bad['recall']==1
    assert not bad['production_promotion']


def test_abstention_does_not_disappear_from_recall():
    rows=cases()
    report=evaluate_grouping(rows,{'0':'first','1':None,'2':'price'},labels(rows))
    assert report['pair_count']==3 and report['abstained_pair_count']==2
    assert report['recall']==0 and report['false_split_or_abstention']==1
    assert report['precision'] is None


def test_unreviewed_pairs_are_not_assumed_negative():
    rows=cases()
    report=evaluate_grouping(rows,{'0':'all','1':'all','2':'all'},labels(rows)[:1])
    assert report['precision'] is None and report['recall'] is None
    assert report['unjudged_pair_count']==2 and report['unjudged_merged_pairs']==2


@pytest.mark.parametrize('fault',['missing_output','foreign_output','duplicate_case','duplicate_label','stale_context','stale_question'])
def test_fixed_denominator_and_review_binding(fault):
    rows=cases();truth=labels(rows);assignments={'0':'a','1':'a','2':'b'}
    if fault=='missing_output': assignments.pop('2')
    if fault=='foreign_output': assignments['3']='c'
    if fault=='duplicate_case': rows.append(copy.deepcopy(rows[0]))
    if fault=='duplicate_label': truth.append(truth[0])
    if fault=='stale_context': rows[0]['confirmed_context']={'size':'L'}
    if fault=='stale_question': rows[0]['question']='다른 질문'
    with pytest.raises(ValueError): evaluate_grouping(rows,assignments,truth)


@pytest.mark.parametrize('field,value',[('store_id','2'),('snapshot_hash','sha256:'+'1'*64)])
def test_structural_scope_violation_is_reported_without_semantic_truth(field,value):
    rows=cases();rows[1][field]=value
    report=evaluate_grouping(rows,{'0':'all','1':'all','2':'all'},[])
    assert report['scope_violations']==2
    with pytest.raises(ValueError): evaluate_grouping(rows,{'0':'a','1':'a','2':'b'},labels(rows))
