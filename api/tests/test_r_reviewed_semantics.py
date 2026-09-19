from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid4
import json
import pytest

from app.contracts.hashing import digest
from app.errors import ApiError
from app.learn.planner import decide
from app.learn.reviewed_semantics import ReviewedCatalog, apply_reviewed, product_decision
from app.learn.semantic_proposals import proposal_input
from tests.test_r_raw_original import search


def fixture():
    result = search()
    original = decide(result,store_id=1,question=result.snapshot.cards[0].title+' 승인 원문 보여줘')
    question = '이 매장의 해당 준비 절차를 설명해주세요'
    baseline = decide(result,store_id=1,question=question)
    assert baseline.plan.action == 'ESCALATE'
    payload = proposal_input(result,store_id=1,question=question)
    interpretation = asdict(original.resolved.assessment)
    interpretation = {key: interpretation[key] for key in ('entity_id','predicate','variants','target_fact_ids','facts','raw_blocks')}
    entry = dict(approval_id='synthetic-review-1',store_id='1',question=question,user_turns=[],confirmed_slots={},
        proposal=dict(input_hash=payload['input_hash'],snapshot_hash=result.snapshot.snapshot_hash,
            plan=original.plan.model_dump(mode='json')),interpretation=interpretation,
        reviewer='synthetic-human',review_reference='synthetic contract test only')
    catalog = ReviewedCatalog(acceptance_reference='synthetic acceptance only',entries=(entry,))
    return result,question,baseline,catalog


def apply(result,question,baseline,catalog,**kwargs):
    return apply_reviewed(result,store_id=1,question=question,user_turns=(),baseline=baseline,catalog=catalog,**kwargs)


def test_reviewed_raw_reaches_server_assessment_without_confirming_model_slots():
    result,q,baseline,catalog=fixture()
    chosen,key=apply(result,q,baseline,catalog)
    assert chosen.plan.action=='ANSWER' and chosen.resolved.question==q and key=='synthetic-review-1'
    assert chosen.confirmed_slots=={} and chosen.semantic_context is None
    from app.learn.answer_validation import validate_answer_for_question
    validate_answer_for_question(chosen.plan,result.snapshot,chosen.resolved,store_id=1)


@pytest.mark.parametrize('change',['question','candidates','slots','context','policy','store'])
def test_nonmatching_or_unsafe_input_keeps_baseline(change):
    result,q,baseline,catalog=fixture()
    kwargs={}
    if change=='question':q+=' 단, 조건을 바꿔서'
    if change=='candidates':result=replace(result,candidates=())
    if change=='slots':baseline=replace(baseline,confirmed_slots={'temperature':'ICE'})
    if change=='context':kwargs['context_id']=uuid4()
    if change=='policy':q='알레르기 있어도 먹어도 돼?'
    if change=='store':
        raw=catalog.model_dump();raw['entries'][0]['store_id']='2';catalog=ReviewedCatalog.model_validate(raw)
    chosen,key=apply(result,q,baseline,catalog,**kwargs)
    assert chosen is baseline and key is None


def test_approval_cannot_omit_raw_or_install_grouping():
    result,q,baseline,catalog=fixture()
    raw=catalog.model_dump()
    raw['entries'][0]['interpretation']['raw_blocks']=()
    with pytest.raises(ValueError):apply(result,q,baseline,ReviewedCatalog.model_validate(raw))
    raw=catalog.model_dump();raw['entries'][0]['proposal']['equivalent_question_ids']=['1']
    with pytest.raises(ValueError):ReviewedCatalog.model_validate(raw)


def test_catalog_disabled_default_and_hash_fail_closed(tmp_path):
    result,q,baseline,catalog=fixture()
    values=dict(store_id=1,question=q,user_turns=(),baseline=baseline)
    assert product_decision(result,settings=SimpleNamespace(),**values)==(baseline,None)
    path=tmp_path/'catalog.json';raw=catalog.model_dump(mode='json');path.write_text(json.dumps(raw),encoding='utf-8')
    settings=SimpleNamespace(r_reviewed_semantics_enabled=True,r_reviewed_semantics_path=path,r_reviewed_semantics_hash=digest(raw))
    assert product_decision(result,settings=settings,**values)[0].plan.action=='ANSWER'
    path.write_text('{}',encoding='utf-8')
    with pytest.raises(ApiError):product_decision(result,settings=settings,**values)
