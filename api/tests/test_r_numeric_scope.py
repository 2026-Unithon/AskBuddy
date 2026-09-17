from decimal import Decimal

import pytest

from app.learn.numeric_scope import NumericScope,parse_numeric_scope,matching_numeric_prefix
from app.learn.planner import decide
from app.learn.approved_renderer import render
from app.learn.answer_storage import pending_key
from tests.test_r_conditional_scope import search


@pytest.mark.parametrize('supplied,approved,expected',[
    ('온도 70도인 경우','온도 60도 이상',True),
    ('온도 60도인 경우','온도 60도 이상',True),
    ('온도 60도인 경우','온도 60도 초과',False),
    ('온도 59.999도인 경우','온도 60도 이상',False),
    ('온도 65도 이상 75도 미만','온도 60도 이상 80도 미만',True),
    ('온도 65도 이상','온도 60도 이상 80도 미만',False),
    ('온도 65도 이상 80도 이하','온도 60도 이상 80도 미만',False),
    ('온도 60도 초과','온도 60도 이상',True),
    ('온도 60도 이상','온도 60도 초과',False),
    ('용량 1000ml인 경우','용량 1l 이상',False),
    ('수량 70개인 경우','온도 60도 이상',False),
])
def test_numeric_entailment_preserves_axis_unit_and_open_endpoints(supplied,approved,expected):
    assert parse_numeric_scope(supplied).entails(parse_numeric_scope(approved)) is expected


@pytest.mark.parametrize('text',[
    '온도 80도 이상 60도 미만','온도 60도 초과 60도 이하',
    '온도 60도 이상 70도 이상','용량 1l 이상 2000ml 미만',
    '온도 NaN도인 경우','온도 -1도인 경우','온도 1e3도인 경우',
])
def test_unsupported_or_empty_numeric_constraint_is_not_parsed(text):
    assert parse_numeric_scope(text) is None


def test_actual_hypothetical_point_answers_with_original_approved_condition():
    result=search(conditions=('온도 60도 이상 80도 미만','점주 확인 후'))
    decision=decide(result,store_id=1,question='온도 70도인 경우 그리고 점주 확인 후 HOT 라테 우유 얼마나?')
    assert decision.plan.action=='ANSWER'
    text=render(decision.plan,result.snapshot,store_id=1,request_id='numeric-scope').message
    assert '온도 60도 이상 80도 미만' in text and '점주 확인 후' in text
    assert decision.resolved.assessment.facts[0].conditions==result.snapshot.fact_revisions[0].conditions


@pytest.mark.parametrize('prefix',[
    '온도 80도인 경우','온도 59.9도일 때','온도 70g인 경우','온도 70도인 경우가 아니라',
    '온도 70도인 경우 또는','온도 65도 이상',
])
def test_outside_ambiguous_or_wrong_unit_does_not_answer(prefix):
    result=search(conditions=('온도 60도 이상 80도 미만',))
    assert decide(result,store_id=1,question=prefix+' HOT 라테 우유 얼마나?').plan.action!='ANSWER'


@pytest.mark.parametrize('conditions',[
    ('온도 80도 이상 60도 미만',),
    ('온도 70도 이상','온도 60도 이하'),
    ('단체 주문인 경우','단체 주문이 아닌 경우'),
])
def test_self_contradictory_question_and_approved_scope_never_answers(conditions):
    result=search(conditions=conditions)
    assert decide(result,store_id=1,question=' '.join(conditions)+' HOT 라테 우유 얼마나?').plan.action!='ANSWER'


def test_different_measurements_are_not_collapsed_into_one_pending_scope():
    result=search(conditions=('온도 60도 이상',))
    decisions=[decide(result,store_id=1,question=f'온도 {value}도인 경우 ICE 라테 우유 얼마나?') for value in (70,71)]
    assert all(d.plan.action=='ESCALATE' and d.semantic_context for d in decisions)
    assert len({pending_key(store_id=1,semantic_context=d.semantic_context) for d in decisions})==2


def test_interval_algebra_exhaustive_small_domain():
    # Independent finite-grid oracle including every bound and half-step.
    scopes=[NumericScope('x','g',Decimal(lo),Decimal(hi),lc,uc)
        for lo in range(3) for hi in range(lo,3) for lc in (False,True) for uc in (False,True)]
    points=[Decimal(i)/2 for i in range(-1,6)]
    def members(scope):
        return {x for x in points if (x>scope.lower or x==scope.lower and scope.lower_closed)
            and (x<scope.upper or x==scope.upper and scope.upper_closed)}
    for left in scopes:
        for right in scopes:
            assert members(left.intersect(right))==members(left)&members(right)
            assert left.entails(right)==(bool(members(left)) and bool(members(right)) and members(left)<=members(right))
