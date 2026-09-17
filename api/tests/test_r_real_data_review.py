import json
import pytest

from app.team.real_data_review import prepare_dev_review
from app.team.v2_evaluation import EvaluationManifest


def seed(root, *, split='dev', confirmation='TEST', variant=None):
    directory=root/'store-a'
    (directory/'truth').mkdir(parents=True)
    (directory/'source.txt').write_text('합성 근거', encoding='utf-8')
    manifest=dict(store_slug='eval-a',split=split,sources=[dict(source_key='s1',type='KAKAO',file='source.txt')])
    truth=dict(store_slug='eval-a',owner_confirmed=confirmation,judged_by='synthetic reviewer',judged_at='2026-09-16',
        facts=[dict(fact_id='f1',subject='합성 음료',attribute='우유 양',value='225ml',variant=variant,
                    source_key='s1',must_have=True,locator=dict(type='LINE',line=1))])
    (directory/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (directory/'truth/facts.json').write_text(json.dumps(truth), encoding='utf-8')
    return directory, manifest, truth


def test_test_labels_and_null_variant_do_not_become_approved_truth(tmp_path):
    seed(tmp_path)
    report=prepare_dev_review(tmp_path,store='store-a')
    assert report['source_label_status']=='TEAM_TEST'
    assert not report['evaluation_ready'] and not report['production_promotion']
    row=report['cases'][0]
    assert row['expected_action'] is None and row['question'] is None and row['snapshot_mapping'] is None
    assert row['applicability']['status']=='UNREVIEWED'
    assert row['applicability']['conditions'] is None
    with pytest.raises(ValueError): EvaluationManifest.model_validate(report)
    assert prepare_dev_review(tmp_path,store='store-a')['review_hash']==report['review_hash']


def test_holdout_refused_before_truth_read(tmp_path):
    directory,_,_=seed(tmp_path,split='holdout')
    (directory/'truth/facts.json').unlink()
    with pytest.raises(ValueError,match='sealed'): prepare_dev_review(tmp_path,store='store-a')
    with pytest.raises(ValueError,match='dev stores'): prepare_dev_review(tmp_path,store='store-c')


@pytest.mark.parametrize('fault',['duplicate','foreign_source','wrong_store','escape','absolute_escape','bool_as_int'])
def test_bad_labels_or_paths_fail_without_printing_private_values(tmp_path,fault):
    directory,manifest,truth=seed(tmp_path)
    if fault=='duplicate': truth['facts']*=2
    if fault=='foreign_source': truth['facts'][0]['source_key']='secret-foreign'
    if fault=='wrong_store': truth['store_slug']='eval-b'
    if fault in ('escape','absolute_escape'):
        (tmp_path/'secret.txt').write_text('private',encoding='utf-8')
        manifest['sources'][0]['file']='../secret.txt' if fault=='escape' else str(tmp_path/'secret.txt')
    if fault=='bool_as_int': truth['facts'][0]['must_have']=1
    (directory/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    (directory/'truth/facts.json').write_text(json.dumps(truth),encoding='utf-8')
    with pytest.raises(ValueError) as exc: prepare_dev_review(tmp_path,store='store-a')
    assert 'secret' not in str(exc.value)


def test_changes_in_truth_or_source_change_hash_but_not_meaning_id(tmp_path):
    directory,_,truth=seed(tmp_path)
    before=prepare_dev_review(tmp_path,store='store-a')
    truth['facts'][0]['value']='250ml'
    (directory/'truth/facts.json').write_text(json.dumps(truth),encoding='utf-8')
    after=prepare_dev_review(tmp_path,store='store-a')
    assert before['review_hash']!=after['review_hash']
    assert before['cases'][0]['meaning_id']==after['cases'][0]['meaning_id']
    (directory/'source.txt').write_text('새 합성 근거',encoding='utf-8')
    assert prepare_dev_review(tmp_path,store='store-a')['review_hash']!=after['review_hash']
