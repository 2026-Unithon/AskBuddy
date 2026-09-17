from dataclasses import replace
from uuid import uuid4
import pytest
from tests import test_r_planner as fixture
from app.contracts.hashing import snapshot_digest
from app.learn.planner import decide
from app.learn.approved_renderer import render
from app.learn.answer_validation import validate_answer_for_question, AnswerReferenceError


def search(conditions=('점주 확인 후','장비 세척 후'),exceptions=()):
    result=fixture.PlannerTest().search(conditions=conditions)
    fact=result.snapshot.fact_revisions[0].model_copy(update=dict(exceptions=exceptions))
    snapshot=result.snapshot.model_copy(update=dict(fact_revisions=(fact,)))
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    return replace(result,snapshot=snapshot)


@pytest.mark.parametrize('prefix',['점주 확인 후 장비 세척 후','장비 세척 후 그리고 점주 확인 후'])
def test_all_explicit_conditions_preserved(prefix):
    result=search()
    decision=decide(result,store_id=1,question=prefix+' HOT 라테 우유 얼마나?')
    assert decision.plan.action=='ANSWER'
    assert decision.resolved.assessment is not None
    response=render(decision.plan,result.snapshot,store_id=1,request_id='conditional-test')
    assert all(condition in response.message for condition in result.snapshot.fact_revisions[0].conditions)
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(decision.plan,result.snapshot,
            replace(decision.resolved,question='HOT 라테 우유 얼마나?'),store_id=1)


@pytest.mark.parametrize('prefix',['','점주 확인 후','점주 확인 전 장비 세척 후',
    '점주 확인 후 또는 장비 세척 후','점주 확인 후 장비 세척 후가 아니라',
    '점주 확인 후 장비 세척 후 두 배로'])
def test_partial_negated_disjunctive_or_extra_conditions_do_not_answer(prefix):
    assert decide(search(),store_id=1,question=prefix+' HOT 라테 우유 얼마나?').plan.action!='ANSWER'


def test_unresolved_exception_and_context_do_not_inherit_approval():
    question='점주 확인 후 장비 세척 후 HOT 라테 우유 얼마나?'
    assert decide(search(exceptions=('단체 주문 제외',)),store_id=1,question=question).plan.action!='ANSWER'
    assert decide(search(),store_id=1,question=question,context_id=uuid4()).plan.action=='ESCALATE'


def test_dependency_condition_also_required():
    result=search(conditions=('점주 확인 후',))
    first=result.snapshot.fact_revisions[0]
    dep=first.model_copy(update=dict(fact_revision_id='2',fact_id='2',predicate='preparation',
        conditions=('장비 세척 후',),quantity=None,assertion='장비를 준비한다',original_assertion='장비를 준비한다'))
    first=first.model_copy(update=dict(requires=('2',)))
    card=result.snapshot.cards[0]
    block=card.blocks[0].model_copy(update=dict(fact_revision_ids=('2','1')))
    snapshot=result.snapshot.model_copy(update=dict(fact_revisions=(first,dep),cards=(card.model_copy(update=dict(blocks=(block,))),)))
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    result=replace(result,snapshot=snapshot)
    assert decide(result,store_id=1,question='점주 확인 후 HOT 라테 우유 얼마나?').plan.action!='ANSWER'
    good=decide(result,store_id=1,question='점주 확인 후 장비 세척 후 HOT 라테 우유 얼마나?')
    assert good.plan.action=='ANSWER'
    assert set(good.plan.selected_blocks[0].fact_revision_ids)=={'1','2'}


def test_condition_match_cannot_resolve_competing_approved_values():
    result=search(conditions=('점주 확인 후',))
    first=result.snapshot.fact_revisions[0]
    other=first.model_copy(update=dict(fact_revision_id='2',fact_id='2',conditions=()))
    card=result.snapshot.cards[0]
    block=card.blocks[0].model_copy(update=dict(fact_revision_ids=('1','2')))
    snapshot=result.snapshot.model_copy(update=dict(fact_revisions=(first,other),
        cards=(card.model_copy(update=dict(blocks=(block,))),)))
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    result=replace(result,snapshot=snapshot)
    for question in ('점주 확인 후 HOT 라테 우유 얼마나?','HOT 라테 우유 얼마나?'):
        assert decide(result,store_id=1,question=question).plan.escalation_reason=='CONFLICTING_FACTS'
