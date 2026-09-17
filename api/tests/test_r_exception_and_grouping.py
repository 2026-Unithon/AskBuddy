from dataclasses import replace
import pytest
from tests import test_r_conditional_scope as fixture
from app.contracts.hashing import snapshot_digest
from app.learn.planner import decide
from app.learn.approved_renderer import render
from app.learn.answer_storage import pending_key


def test_explicitly_absent_exclusion_preserves_approved_exception():
    result=fixture.search(conditions=('점주 확인 후',),exceptions=('단체 주문 제외',))
    decision=decide(result,store_id=1,question='점주 확인 후 단체 주문이 아닌 경우 HOT 라테 우유 얼마나?')
    assert decision.plan.action=='ANSWER'
    response=render(decision.plan,result.snapshot,store_id=1,request_id='exception-test')
    assert '단체 주문 제외' in response.message and '점주 확인 후' in response.message
    assert decision.resolved.assessment.facts[0].exceptions==('단체 주문 제외',)


@pytest.mark.parametrize('prefix',['점주 확인 후','점주 확인 후 단체 주문인 경우',
    '점주 확인 후 단체 주문이 아닌 경우가 아니라','점주 확인 후 단체 주문이 아닌 경우 또는'])
def test_unknown_active_or_negated_exception_never_answers(prefix):
    result=fixture.search(conditions=('점주 확인 후',),exceptions=('단체 주문 제외',))
    assert decide(result,store_id=1,question=prefix+' HOT 라테 우유 얼마나?').plan.action!='ANSWER'


@pytest.mark.parametrize('exception',['단체 주문이면 100ml','알레르기 주의','단체 주문 아닌 경우 제외'])
def test_arbitrary_exception_cannot_be_rewritten_as_absent(exception):
    result=fixture.search(conditions=(),exceptions=(exception,))
    assert decide(result,store_id=1,question='단체 주문이 아닌 경우 HOT 라테 우유 얼마나?').plan.action!='ANSWER'


def test_condition_order_and_question_phrasing_group_but_scope_does_not_disappear():
    result=fixture.search(conditions=('점주 확인 후','장비 세척 후'),exceptions=('단체 주문 제외',))
    questions=('점주 확인 후 장비 세척 후 단체 주문이 아닌 경우 ICE 라테 우유 얼마나?',
               '단체 주문이 아닌 경우 그리고 장비 세척 후 그리고 점주 확인 후 라테 ICE 우유 양?')
    decisions=[decide(result,store_id=1,question=q) for q in questions]
    assert all(d.plan.action=='ESCALATE' and d.semantic_context for d in decisions)
    assert decisions[0].semantic_context==decisions[1].semantic_context
    key=pending_key(store_id=1,semantic_context=decisions[0].semantic_context)
    altered=dict(decisions[0].semantic_context,exceptions=[])
    assert pending_key(store_id=1,semantic_context=altered)!=key


@pytest.mark.parametrize('predicate,one,two',[
    ('price','ICE 라테 가격 얼마야?','라테 ICE 가격은?'),
    ('location','ICE 라테 위치는?','라테 ICE 어디 있어?'),
    ('quantity','ICE 라테 수량은?','라테 ICE 몇 개?'),
])
def test_grouping_extends_to_other_explicit_predicates(predicate,one,two):
    result=fixture.search(conditions=())
    fact=result.snapshot.fact_revisions[0].model_copy(update=dict(predicate=predicate))
    snapshot=result.snapshot.model_copy(update=dict(fact_revisions=(fact,)))
    snapshot=snapshot.model_copy(update=dict(snapshot_hash=snapshot_digest(snapshot)))
    result=replace(result,snapshot=snapshot)
    a,b=[decide(result,store_id=1,question=q) for q in (one,two)]
    assert a.semantic_context is not None and a.semantic_context==b.semantic_context
