from copy import deepcopy
import pytest
from app.contracts.hashing import digest
from app.team.review_intake import start_intake, record_decision, pending_questions, mapped_judgments, checked_intake


def queue():
    data = dict(schema_version='r_review_queue/v1', review_hash='synthetic-review',
        selected_meaning_ids=['one', 'two'], source_rows=[dict(meaning_id=i) for i in ('one', 'two')],
        selection_reason='synthetic fixed sample')
    return dict(data, queue_hash=digest(data))


def decision(meaning_id='one'):
    return dict(meaning_id=meaning_id, question='합성 질문', expected_action='ANSWER', must_have=True,
        applicability='SPECIFIC', conditions=[], exceptions=[], scope_reason='명시 규격',
        forbidden_claims=['다른 규격의 값'], reviewer='synthetic-reviewer', reason='합성 계약 검증')


def test_incremental_review_preserves_missing_and_idempotency():
    q = queue(); initial = start_intake(q)
    updated = record_decision(q, initial, expected_hash=initial['intake_hash'], request_id='review-01', decision=decision())
    assert len(pending_questions(q, updated)) == 1
    assert not updated['evaluation_ready'] and not updated['production_promotion']
    assert record_decision(q, updated, expected_hash=initial['intake_hash'], request_id='review-01', decision=decision()) == updated
    with pytest.raises(ValueError):
        record_decision(q, updated, expected_hash=initial['intake_hash'], request_id='review-02', decision=decision('two'))
    with pytest.raises(ValueError):
        record_decision(q, updated, expected_hash=updated['intake_hash'], request_id='review-01', decision=decision('two'))


def test_corrections_append_and_do_not_override_evidence_authority():
    q = queue(); state = start_intake(q)
    for key in ('one', 'two'):
        state = record_decision(q, state, expected_hash=state['intake_hash'], request_id='review-'+key, decision=decision(key))
    revised = dict(decision(), expected_action='ESCALATE', applicability='UNDETERMINED', reason='정답 불확실')
    state = record_decision(q, state, expected_hash=state['intake_hash'], request_id='review-correction', decision=revised)
    assert len(state['events']) == 3 and state['events'][0]['decision']['expected_action'] == 'ANSWER'
    mappings = {key: dict(required_fact_revisions=[], required_raw_blocks=[]) for key in ('one', 'two')}
    with pytest.raises(ValueError): mapped_judgments(q, state, mappings=mappings)
    mappings['two']['required_fact_revisions'] = ['1']
    assert len(mapped_judgments(q, state, mappings=mappings)['judgments']) == 2
    mappings['one']['expected_action'] = 'ANSWER'
    with pytest.raises(ValueError): mapped_judgments(q, state, mappings=mappings)


def test_changed_queue_invalidates_intake():
    q = queue(); state = start_intake(q)
    changed = deepcopy(q); changed['source_rows'][0]['question'] = '다른 질문'
    with pytest.raises(ValueError): pending_questions(changed, state)


def test_projection_cannot_silently_replace_human_decision():
    q = queue(); initial = start_intake(q)
    state = record_decision(q, initial, expected_hash=initial['intake_hash'], request_id='review-01', decision=decision())
    state['decisions']['one']['expected_action'] = 'ESCALATE'
    state['intake_hash'] = digest({k: v for k, v in state.items() if k != 'intake_hash'})
    with pytest.raises(ValueError): checked_intake(q, state)


def test_revision_file_is_exclusive_and_complete(tmp_path):
    from scripts.record_r_review import save_revision
    state = start_intake(queue())
    save_revision(tmp_path, state)
    save_revision(tmp_path, state)
    assert len(list(tmp_path.iterdir())) == 1
    changed = dict(state, decisions={'one': decision()})
    with pytest.raises(ValueError): save_revision(tmp_path, changed)
    assert len(list(tmp_path.iterdir())) == 1
