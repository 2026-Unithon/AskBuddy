from copy import deepcopy
import pytest

from app.contracts.hashing import digest
from app.team.external_review import build_package, import_result, confirmed_decision
from app.team.review_intake import start_intake, record_decision


def fixture():
    cases = [dict(meaning_id=i, source_label=dict(source_key='s'), question_draft='합성 질문')
             for i in ('one', 'two')]
    review = dict(schema_version='r_dev_review/v1', split='dev', store='store-a', cases=cases,
        source_label_status='TEAM_TEST', sources={'s': dict(type='KAKAO', sha256='synthetic', bytes=10)})
    review['review_hash'] = digest(review)
    queue = dict(schema_version='r_review_queue/v1', review_hash=review['review_hash'],
        selected_meaning_ids=['one', 'two'], source_rows=deepcopy(cases))
    queue['queue_hash'] = digest(queue)
    package = build_package(review, queue)
    decision = dict(meaning_id='one', question='합성 질문', expected_action='ANSWER', must_have=True,
        applicability='SPECIFIC', conditions=[], exceptions=[], scope_reason='명시 범위',
        forbidden_claims=[], reason='합성 근거')
    result = dict(schema_version='r_external_review_result/v1', package_hash=package['package_hash'],
        store='store-a', model='synthetic-model', session_reference='synthetic-session', proposals=[
            dict(meaning_id='one', status='PROPOSED', source_check='LABEL_ONLY', source_keys=list(package['sources']),
                reason='원본 확인 필요', decision=decision),
            dict(meaning_id='two', status='UNRESOLVED', source_check='NOT_CHECKED', source_keys=[],
                reason='판정 근거 부족', decision=None)])
    return review, queue, package, result


def test_pseudonyms_are_reversible_only_with_same_private_map():
    import json
    review,queue,_,result=fixture()
    mapping={'합성 질문':'[[R_001]]'}
    package=build_package(review,queue,redactions=mapping)
    assert '합성 질문' not in json.dumps(package,ensure_ascii=False)
    assert package['external_transfer_approved'] is False
    result['package_hash']=package['package_hash']
    result['proposals'][0]['decision']['question']='[[R_001]]'
    imported=import_result(review,queue,package,result,redactions=mapping)
    with pytest.raises(ValueError):import_result(review,queue,package,result)
    restored=confirmed_decision(review,queue,package,imported,meaning_id='one',reviewer='synthetic human',redactions=mapping)
    assert restored['question']=='합성 질문'
    from app.team.review_redaction import checked_redactions
    with pytest.raises(ValueError):checked_redactions({'가나다':'[[R_001]]','라마바':'[[R_001]]'})


def test_ai_import_is_not_human_truth_and_preserves_unresolved_denominator():
    review, queue, package, result = fixture()
    initial = start_intake(queue)
    imported = import_result(review, queue, package, result)
    assert imported['human_reviewed_count'] == 0 and not imported['evaluation_ready']
    assert imported['proposed_count'] == imported['unresolved_count'] == 1
    decision = confirmed_decision(review, queue, package, imported, meaning_id='one', reviewer='human-test')
    state = record_decision(queue, initial, expected_hash=initial['intake_hash'], request_id='confirm-01', decision=decision)
    assert len(state['decisions']) == 1 and not state['evaluation_ready']
    assert imported['import_hash'] in state['decisions']['one']['reason']
    assert not initial['decisions']
    with pytest.raises(ValueError):
        confirmed_decision(review, queue, package, imported, meaning_id='two', reviewer='human-test')


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'foreign_store', 'foreign_source', 'human_attribution', 'unresolved_answer', 'hash'])
def test_untrusted_result_rejections(change):
    review, queue, package, result = fixture()
    if change == 'missing': result['proposals'].pop()
    if change == 'duplicate': result['proposals'][1] = deepcopy(result['proposals'][0])
    if change == 'foreign_store': result['store'] = 'store-b'
    if change == 'foreign_source': result['proposals'][0]['source_keys'] = ['unknown']
    if change == 'human_attribution': result['proposals'][0]['decision']['reviewer'] = 'invented-human'
    if change == 'unresolved_answer': result['proposals'][1]['decision'] = result['proposals'][0]['decision']
    if change == 'hash': result['package_hash'] = 'wrong'
    with pytest.raises(ValueError): import_result(review, queue, package, result)


def test_holdout_drift_and_forged_import_are_rejected():
    review, queue, package, result = fixture()
    altered = deepcopy(review); altered['split'] = 'holdout'; altered['review_hash'] = digest({k:v for k,v in altered.items() if k!='review_hash'})
    with pytest.raises(ValueError): build_package(altered, queue)
    changed = deepcopy(queue); changed['source_rows'][0]['question_draft'] = 'changed'
    changed['queue_hash'] = digest({k:v for k,v in changed.items() if k!='queue_hash'})
    with pytest.raises(ValueError): build_package(review, changed)
    imported = import_result(review, queue, package, result)
    imported['human_reviewed_count'] = 1
    with pytest.raises(ValueError): confirmed_decision(review, queue, package, imported, meaning_id='one', reviewer='human')
