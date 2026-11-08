from dataclasses import replace
from unittest.mock import AsyncMock
import pytest

from app.contracts.common import Quantity
from app.contracts.hashing import snapshot_digest
from app.learn.answer_validation import AnswerReferenceError,validate_answer_for_question
from app.learn.general_semantics import general_decision
from app.learn.grounded_calculations import calculable_unit
from app.learn.planner import decide
from app.learn.approved_renderer import render
from tests.test_r_general_semantics import setup
from tests import test_r_planner as fixtures

def unitless_search():
    search=fixtures.PlannerTest().search()
    old=search.snapshot.fact_revisions[0]
    fact=old.model_copy(update={'quantity':Quantity(value='225',unit=None)})
    snapshot=search.snapshot.model_copy(update={'fact_revisions':(fact,)})
    snapshot=snapshot.model_copy(update={'snapshot_hash':snapshot_digest(snapshot)})
    return replace(search,snapshot=snapshot)

@pytest.mark.asyncio
async def test_unitless_candidate_does_not_block_provider_dispatch(tmp_path,monkeypatch):
    search=unitless_search(); _,__,kwargs,release=setup(tmp_path)
    from app.learn.general_semantics import Release
    monkeypatch.setattr('app.learn.general_semantics.load_release',lambda *_:Release(**release))
    class ProviderReached(Exception):pass
    provider=AsyncMock(side_effect=ProviderReached())
    from app.errors import ApiError
    with pytest.raises(ApiError) as caught:await general_decision(search,**kwargs,provider=provider)
    provider.assert_awaited_once()
    assert provider.await_args.kwargs['calculation_fact_ids']==()
    assert caught.value.details==dict(phase='proposal_provider',error_type='ProviderReached')

def test_unitless_fact_can_be_read_verbatim_but_not_invented_as_operand():
    search=unitless_search()
    decision=decide(search,store_id=1,question='라테 카드 원문 보여줘.')
    assert decision.plan.action=='ANSWER' and not calculable_unit(None)
    response=render(decision.plan,search.snapshot,store_id=1,request_id='literal-regression',resolved=decision.resolved)
    assert search.snapshot.fact_revisions[0].assertion in response.message
    assert response.citations[0].fact_revision_id=='1'
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(decision.plan,search.snapshot,replace(decision.resolved,question='라테를 3배로 계산해줘'),store_id=1)

def test_unknown_menu_or_unretrieved_block_does_not_get_a_whole_card_answer():
    search=unitless_search()
    assert decide(search,store_id=1,question='말차라테 카드 원문 보여줘.').plan.action!='ANSWER'
    assert decide(replace(search,candidates=()),store_id=1,question='라테 카드 원문 보여줘.').plan.action!='ANSWER'
