import pytest
from app.team.real_data_review import prepare_dev_review
from app.team.review_queue import prepare_review_queue
from app.team.reviewed_manifest import ReviewedCase
from tests.test_r_real_data_review import seed


def test_queue_is_deterministic_and_cannot_be_imported_as_reviewed(tmp_path):
    seed(tmp_path)
    review=prepare_dev_review(tmp_path,store='store-a')
    a=prepare_review_queue(review)
    assert a==prepare_review_queue(review)
    assert not a['evaluation_ready'] and a['semantic_accuracy'] is None
    assert a['judgments'][0]['must_have'] is None
    assert a['judgments'][0]['required_raw_blocks'] is None
    assert a['requested_count']==40 and a['reviewed_question_count']==0
    assert not a['snapshot_coverage_verified'] and not a['minimum_draft_count_reached']
    with pytest.raises(ValueError): ReviewedCase.model_validate(a['judgments'][0])


def test_queue_rejects_tampering_and_bad_limit(tmp_path):
    seed(tmp_path)
    review=prepare_dev_review(tmp_path,store='store-a')
    with pytest.raises(ValueError): prepare_review_queue(review,limit=True)
    with pytest.raises(ValueError): prepare_review_queue(review,limit=201)
    review['cases'][0]['question_draft']='changed'
    with pytest.raises(ValueError): prepare_review_queue(review)


def test_repeated_draft_text_does_not_inflate_question_coverage(tmp_path):
    from app.contracts.hashing import digest
    seed(tmp_path)
    review=prepare_dev_review(tmp_path,store='store-a')
    template=review['cases'][0]
    review['cases']=[dict(template,meaning_id=f'synthetic-{i}') for i in range(40)]
    review['review_hash']=digest({k:v for k,v in review.items() if k!='review_hash'})
    queue=prepare_review_queue(review)
    assert queue['draft_count']==40 and queue['distinct_question_draft_count']==1
    assert not queue['minimum_draft_count_reached'] and not queue['evaluation_ready']
