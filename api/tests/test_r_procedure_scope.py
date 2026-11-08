from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.contracts.hashing import snapshot_digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.answer_validation import AnswerReferenceError, validate_answer_for_question
from app.learn.approved_renderer import render
from app.learn.planner import decide, procedure_decision
from app.learn.procedure_scope import procedure_scope
from app.reg.hybrid import SearchResult

COMPARE='모카랑 라테를 둘 다 주문받았어. 승인된 카드 기준으로 제조할 때 헷갈리기 쉬운 차이 한 가지만 알려줘.'
FOLLOW='그럼 두 번째 음료만 만들 때는 뭘 먼저 해야 해?'


def publication(modify=None):
    cards=[]
    facts=[]
    for entity,title,cold in [('1','모카','추출'),('2','라테','거품 제조(250ml)')]:
        ids=[]
        for temp,first in [('HOT','추출'),('ICE',cold)]:
            fid=str(len(facts)+1)
            ids.append(fid)
            text=f'제조순서={first} → 컵 준비'
            facts.append(dict(fact_id=fid,fact_revision_id=fid,subject=title,entity_id=entity,
                predicate='제조순서',assertion=text,original_assertion=text,variant=dict(temperature=temp),
                provenance=[dict(source_id='1',occurrence_id=fid)]))
        cards.append(dict(card_id=entity,card_version_id=entity,entity_id=entity,title=title,
            blocks=[dict(block_id='steps',kind='STEPS',order=1,fact_revision_ids=ids)]))
    if modify:modify(facts)
    snap=PublishedKnowledgeSnapshot.model_validate(dict(store_id='9',snapshot_id='1',knowledge_revision='1',
        snapshot_hash='sha256:'+'0'*64,created_at=datetime.now(timezone.utc),glossary_version='v1',
        renderer_version='r-approved/v2',cards=cards,fact_revisions=facts))
    return snap.model_copy(update=dict(snapshot_hash=snapshot_digest(snap)))


def answer(snap,question,previous=None):
    scope=procedure_scope(snap,question,previous)
    baseline=decide(SearchResult(snap,0,(),question),store_id=9,question=question)
    return procedure_decision(snap,question,previous,scope,baseline)


def test_compare_then_ordinal_answers_from_current_cards_with_exact_citations():
    snap=publication()
    first=answer(snap,COMPARE)
    reply=render(first.plan,snap,store_id=9,request_id='compare',resolved=first.resolved)
    assert reply.action=='ANSWER' and 'ICE 기준' in reply.message
    assert '모카 · 첫 단계: 추출' in reply.message and '라테 · 첫 단계: 거품 제조(250ml)' in reply.message
    assert [c.fact_revision_id for c in reply.citations]==['2','4']
    next_turn=answer(snap,FOLLOW,COMPARE)
    reply=render(next_turn.plan,snap,store_id=9,request_id='second',resolved=next_turn.resolved)
    assert reply.action=='ANSWER' and '라테' in reply.message and '모카' not in reply.message
    assert 'HOT · 첫 단계: 추출' in reply.message and 'ICE · 첫 단계: 거품 제조(250ml)' in reply.message
    assert {c.fact_revision_id for c in reply.citations}=={'3','4'}
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(next_turn.plan,snap,replace(next_turn.resolved,
            procedure_previous=COMPARE.replace('모카랑 라테','라테랑 모카')),store_id=9)


@pytest.mark.parametrize('qualifier',[{'conditions':['점주 확인 후']},{'exceptions':['고장 시 제외']},
    {'polarity':'NEGATE'},{'variant':dict(temperature='ICE',size='large')},{'requires':['3']}])
def test_unmet_condition_conflict_or_prerequisite_never_becomes_first_step(qualifier):
    snap=publication(lambda facts:facts[-1].update(qualifier))
    assert answer(snap,COMPARE).plan.action!='ANSWER'


@pytest.mark.parametrize('question',[COMPARE+' 그리고 가격도',COMPARE.replace('제조할 때','알레르기가 있을 때'),
    '라테 대신 모카로 바꿔야 해?', '두 번째 단계는?', '아이스크림 원문 보여줘'])
def test_modifiers_and_new_topics_do_not_gain_approval(question):
    assert procedure_scope(publication(),question,COMPARE) is None


def test_conflicting_approved_steps_do_not_become_a_direct_answer():
    def conflict(facts):
        facts[2].update(variant=dict(temperature='ICE'))
    assert answer(publication(conflict),COMPARE).plan.action!='ANSWER'


@pytest.mark.parametrize('question',['모카와 라테의 제조 과정을 비교해 줘.','모카랑 라테는 제조 순서가 어떻게 달라?'])
def test_paraphrases_keep_subject_order_and_temperature_evidence(question):
    snap=publication()
    first=answer(snap,question)
    assert [s.title for s in first.resolved.procedure_steps]==['모카','라테']
    followup=answer(snap,'그럼 두 번째 메뉴는 뭐부터 시작해?',question)
    assert {s.title for s in followup.resolved.procedure_steps}=={'라테'}


def test_open_comparison_retains_both_subjects_without_inferring_procedure_intent():
    from app.learn.dialogue_history import DialogueHistory,scoped_fallback,requested_subjects,respects_subjects
    from app.reg.hybrid import Candidate
    snap=publication()
    q='모카랑 라테의 보관 위치 차이는?'
    candidates=tuple(Candidate(c.card_id,c.card_version_id,'steps',1,0,1) for c in snap.cards)
    baseline=decide(SearchResult(snap,0,candidates,q),store_id=9,question=q)
    history=DialogueHistory()
    assert procedure_scope(snap,q) is None
    subjects=requested_subjects(q,history,snap)
    assert subjects==('모카','라테') and not respects_subjects(baseline,subjects,snap)
    assert scoped_fallback(baseline,q,history,snap).plan.escalation_reason=='UNRESOLVED_COMPARISON'
