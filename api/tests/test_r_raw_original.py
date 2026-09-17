from dataclasses import replace
from pathlib import Path

import pytest

from app.contracts.hashing import snapshot_digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.approved_renderer import render,RENDERER_VERSION
from app.learn.planner import decide
from app.learn.answer_validation import validate_answer_for_question,AnswerReferenceError
from app.reg.hybrid import Candidate,SearchResult


def search():
    snapshot=PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).parent/'fixtures/contracts/v1/snapshot.json').read_text(encoding='utf-8'))
    snapshot=snapshot.model_copy(update={'renderer_version':RENDERER_VERSION})
    snapshot=snapshot.model_copy(update={'snapshot_hash':snapshot_digest(snapshot)})
    return SearchResult(snapshot,1,tuple(Candidate(c.card_id,c.card_version_id,b.block_id,None,None,0)
        for c in snapshot.cards for b in c.blocks),'')


def test_exact_original_request_preserves_raw_and_citation():
    result=search()
    question=result.snapshot.cards[0].title+' 승인 원문 보여줘'
    decision=decide(result,store_id=1,question=question)
    assert decision.plan.action=='ANSWER'
    response=render(decision.plan,result.snapshot,store_id=1,request_id='raw-original-test')
    assert response.message==result.snapshot.raw_spans[0].text
    assert response.citations[0].raw_span_id==result.snapshot.raw_spans[0].raw_span_id
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(decision.plan,result.snapshot,replace(decision.resolved,question='다른 질문'),store_id=1)


@pytest.mark.parametrize('suffix',['어떻게 만들어?','승인 원문 보여줘 그리고 수량 바꿔줘','승인 원문 보여줘 알레르기 있어도 먹어도 돼?'])
def test_free_questions_do_not_gain_raw_authorization(suffix):
    result=search()
    assert decide(result,store_id=1,question=result.snapshot.cards[0].title+' '+suffix).plan.action!='ANSWER'


def test_missing_raw_candidate_does_not_expand_from_snapshot():
    result=search()
    result=replace(result,candidates=tuple(c for c in result.candidates if c.block_id!='b4'))
    assert decide(result,store_id=1,question=result.snapshot.cards[0].title+' 승인 원문 보여줘').plan.action=='ESCALATE'
