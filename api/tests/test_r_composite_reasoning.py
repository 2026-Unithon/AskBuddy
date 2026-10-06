"""합성 제안의 구조 경계 테스트. 모델 정답률 측정이 아니다."""
from dataclasses import replace
import pytest
from app.contracts.hashing import snapshot_digest
from app.contracts.answer import AnswerPlan
from app.learn.planner import decide
from app.learn.answer_validation import validate_answer_for_question, AnswerReferenceError
from app.learn.general_semantics import validate_interpretation
from app.learn.semantic_proposals import proposal_input
from app.learn.approved_renderer import render
from app.reg.hybrid import Candidate
from tests.test_r_planner import PlannerTest


def fixture():
    search = PlannerTest().search(temperature=None)
    source = search.snapshot.fact_revisions[0]
    facts = tuple(source.model_copy(update=dict(fact_revision_id=str(i), fact_id=str(i),
        entity_id=str(i), predicate='price', assertion=f'{name} 가격 {value}원',
        original_assertion=f'{name} 가격 {value}원',
        quantity=source.quantity.model_copy(update=dict(value=value, unit='원'))))
        for i, name, value in ((1, '포장재', '120'), (2, '봉투', '30')))
    first = search.snapshot.cards[0]
    cards = tuple(first.model_copy(update=dict(card_id=str(i), card_version_id=str(i),
        entity_id=str(i), title=name, blocks=(first.blocks[0].model_copy(update=dict(fact_revision_ids=(str(i),))),)))
        for i, name in ((1, '포장재'), (2, '봉투')))
    snap = search.snapshot.model_copy(update=dict(cards=cards, fact_revisions=facts))
    search = replace(search, snapshot=snap.model_copy(update=dict(snapshot_hash=snapshot_digest(snap))),
        candidates=tuple(Candidate(str(i), str(i), 'b', 1, 0, .02) for i in (1, 2)))
    q = '포장재와 봉투의 가격을 합쳐줘'
    baseline = decide(search, store_id=1, question=q)
    payload = proposal_input(search, store_id=1, question=q)
    parts = []
    for i in ('1', '2'):
        parts.append(dict(plan=dict(snapshot_id='1', knowledge_revision='1', action='ANSWER',
            selected_blocks=[dict(card_id=i, card_version_id=i, block_id='b', fact_revision_ids=[i])]),
            interpretation=dict(entity_id=i, predicate='price', variants=[], target_fact_ids=[i],
                                not_applicable_fact_ids=[i]),
            slots=[dict(slot=k, value=v, question_quote=q) for k,v in [('entity',i),('predicate','price')]]))
    raw = dict(input_hash=payload['input_hash'], snapshot_hash=snap.snapshot_hash,
        plan=dict(snapshot_id='1', knowledge_revision='1', action='ANSWER',
            selected_blocks=[part['plan']['selected_blocks'][0] for part in parts]), parts=parts,
        calculations=[dict(operator='ADD', fact_ids=['1','2'])])
    raw['snapshot_hash'] = search.snapshot.snapshot_hash
    return search, payload, raw, baseline


def test_two_entities_render_all_sources_and_server_calculation():
    search, payload, raw, baseline = fixture()
    assert baseline.plan.action == 'CLARIFY'
    decision = validate_interpretation(search, payload=payload, proposal=raw, baseline=baseline)
    assert len(decision.resolved.parts) == 2
    result = render(decision.plan, search.snapshot, store_id=1, request_id='synthetic-composite', resolved=decision.resolved)
    assert {c.fact_revision_id for c in result.citations} == {'1','2'}
    assert '포장재 가격 120원' in result.message and '봉투 가격 30원' in result.message
    assert '계산: 120원 + 30원 = 150원' in result.message
    assert decision.confirmed_slots == baseline.confirmed_slots


@pytest.mark.parametrize('change', ['missing_part', 'missing_outer', 'wrong_entity', 'wrong_quote',
                                  'foreign_store', 'stale_part', 'unknown_operand', 'nested_part'])
def test_composite_fails_closed(change):
    search, payload, raw, baseline = fixture()
    if change == 'missing_part': raw['parts'].pop()
    if change == 'missing_outer': raw['plan']['selected_blocks'].pop()
    if change == 'wrong_entity': raw['parts'][1]['interpretation']['entity_id'] = '1'
    if change == 'wrong_quote': raw['parts'][1]['slots'][0]['question_quote'] = '없는 발화'
    if change == 'foreign_store': payload['store_id'] = '2'
    if change == 'stale_part': raw['parts'][1]['plan']['knowledge_revision'] = '2'
    if change == 'unknown_operand': raw['calculations'][0]['fact_ids'] = ['1','99']
    if change == 'nested_part': raw['parts'][1]['parts'] = []
    with pytest.raises(ValueError):
        validate_interpretation(search, payload=payload, proposal=raw, baseline=baseline)


def test_commit_validation_rejects_parts_bound_to_another_question_or_removed_reference():
    search, payload, raw, baseline = fixture()
    decision = validate_interpretation(search, payload=payload, proposal=raw, baseline=baseline)
    bad = replace(decision.resolved, question='다른 조건의 질문')
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(decision.plan, search.snapshot, bad, store_id=1)
    bad_plan = decision.plan.model_copy(update=dict(selected_blocks=decision.plan.selected_blocks[:1]))
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(bad_plan, search.snapshot, decision.resolved, store_id=1)


@pytest.mark.parametrize('change', ['omitted_condition', 'omitted_exception'])
def test_each_part_keeps_all_condition_and_exception_obligations(change):
    search, payload, raw, baseline = fixture()
    fact = search.snapshot.fact_revisions[1].model_copy(update=dict(
        conditions=('포장 주문에만 적용',), exceptions=('단, 예약 주문은 제외',)))
    snap = search.snapshot.model_copy(update=dict(fact_revisions=(search.snapshot.fact_revisions[0],fact)))
    search = replace(search,snapshot=snap.model_copy(update=dict(snapshot_hash=snapshot_digest(snap))))
    payload = proposal_input(search,store_id=1,question=payload['question'])
    raw.update(input_hash=payload['input_hash'],snapshot_hash=search.snapshot.snapshot_hash)
    kind = 'exception' if change == 'omitted_condition' else 'condition'
    raw['parts'][1]['obligations']=[dict(fact_revision_id='2',kind=kind,
        statement=fact.exceptions[0] if kind == 'exception' else fact.conditions[0],question_quote=payload['question'])]
    with pytest.raises(ValueError,match='omitted or invented'):
        validate_interpretation(search,payload=payload,proposal=raw,baseline=baseline)
