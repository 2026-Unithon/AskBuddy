from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.contracts.hashing import snapshot_digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.answer_validation import AnswerReferenceError, validate_answer_for_question
from app.learn.approved_renderer import render
from app.learn.operating_guidance import CHANNEL_QUESTION, resolve_guidance
from app.learn.planner import decide, operating_decision
from app.reg.hybrid import SearchResult

OPENING = '혼자 오픈하는 첫 근무예요. 문 열기 전에 시재와 비품 중 무엇을 먼저 확인하나요?'
REFUND = '카페모카랑 카라멜마끼아또 주문이 하나씩 있어. 한 건을 환불하려면 어떻게 처리해?'
DETAIL = '배달앱으로 결제한 주문이고 영수증은 없어.'


def publication(change=None):
    cards, facts = [], []

    def card(title, steps):
        cid = str(len(cards) + 1)
        ids = []
        for order, predicate, text, conditions, requires in steps:
            fid = str(len(facts) + 1)
            ids.append(fid)
            facts.append(dict(entity_id=cid, fact_id=fid, fact_revision_id=fid, subject=title,
                              predicate=predicate, order=order, assertion=text, original_assertion=text,
                              conditions=conditions, requires=requires,
                              provenance=[dict(source_id='52', occurrence_id=fid)]))
        cards.append(dict(card_id=cid, card_version_id=cid, entity_id=cid, title=title,
                          blocks=[dict(block_id='steps', kind='STEPS', order=1, fact_revision_ids=ids)]))

    card('오픈 준비', [(1, '첫 단계', '시재 확인이 먼저입니다.', [], []),
                    (2, '다음 단계', '비품 점검이 다음입니다.', [], ['1'])])
    card('오픈 준비 순서', [(None, '적용 범위', '혼자 오픈하는 첫 근무도 같은 순서입니다.',
                        ['혼자 오픈하는 첫 근무인 경우'], [])])
    card('주문 환불', [(1, '사전 확인', '결제 경로와 원거래를 확인합니다.', [], []),
                    (2, '조회', '배달앱 결제는 앱 주문번호로 조회합니다.', ['종이 영수증이 없는 경우'], ['4']),
                    (2, 'POS', '매장 직접 결제는 POS에서 원거래를 확인하고 원결제 수단으로 환불합니다.', [], ['4'])])
    for title in ('카페모카', '카라멜마끼아또'):
        card(title, [(None, '재료', '샷', [], [])])
    if change:
        change(facts, cards)
    snap = PublishedKnowledgeSnapshot.model_validate(dict(store_id='9', snapshot_id='1', knowledge_revision='2',
        snapshot_hash='sha256:'+'0'*64, created_at=datetime.now(timezone.utc), glossary_version='v1',
        renderer_version='r-approved/v2', cards=cards, fact_revisions=facts))
    return snap.model_copy(update={'snapshot_hash': snapshot_digest(snap)})


def answer(snap, question, prev=None):
    baseline = decide(SearchResult(snap, 0, (), question), store_id=9, question=question)
    result = operating_decision(snap, question, prev, baseline)
    return render(result.plan, snap, store_id=9, request_id='verify', resolved=result.resolved,
                  owner_sources={'52': '20'})


def test_opening_first_reply_quotes_order_and_owner_including_after_menu_topic():
    snap = publication()
    reply = answer(snap, OPENING, 'ICE')
    assert reply.action == 'ANSWER' and reply.message.startswith('시재 확인이 먼저')
    assert [c.fact_revision_id for c in reply.citations] == ['1', '2', '3']
    assert '[점주 답변 20 · 출처 1]' in reply.message
    changed = publication(lambda fs, _: fs[0].update(assertion='비품과 시재를 함께 확인합니다.'))
    assert answer(changed, OPENING).message.startswith('비품과 시재를 함께 확인합니다.')


def test_refund_common_before_channel_and_followup_uses_channel_only_in_context():
    snap = publication()
    common = answer(snap, REFUND)
    assert common.message.startswith('결제 경로와 원거래') and common.message.endswith(CHANNEL_QUESTION)
    assert [c.fact_revision_id for c in common.citations] == ['4']
    for detail, ids in [(DETAIL, ['4', '5']), ('배달앱', ['4', '5']), ('매장 직접 결제', ['4', '6'])]:
        reply = answer(snap, detail, REFUND)
        assert reply.action == 'ANSWER' and CHANNEL_QUESTION not in reply.message
        assert [c.fact_revision_id for c in reply.citations] == ids
    assert resolve_guidance(snap, DETAIL, '카페모카') is None
    assert CHANNEL_QUESTION not in answer(snap, '환불 공통 절차만 알려줘').message
    assert CHANNEL_QUESTION not in answer(snap, '매장 직접 결제인데 환불하려면 어떻게 처리해?').message


@pytest.mark.parametrize('question', [OPENING+' 알레르기가 있어요.', REFUND+' 어제 주문도 돼?',
                                     '모르는 메뉴랑 카페모카 주문이 하나씩 있어. 한 건을 환불하려면 어떻게 처리해?',
                                     '지난달 환불하려면 어떻게 처리해?', '오픈 준비 카드 원문 보여줘.'])
def test_unrecognized_scope_never_gets_operating_answer(question):
    assert resolve_guidance(publication(), question) is None


@pytest.mark.parametrize('patch', [dict(order=1), dict(exceptions=['야간 제외']), dict(polarity='NEGATE'),
                                  dict(variant={'temperature':'ICE'})])
def test_conflict_or_conditional_step_falls_back(patch):
    assert resolve_guidance(publication(lambda fs, _: fs[1].update(patch)), OPENING) is None


def test_forged_question_and_missing_refs_are_rejected():
    snap = publication()
    result = operating_decision(snap, OPENING, None, None)
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(result.plan, snap, replace(result.resolved, question=REFUND), store_id=9)
    with pytest.raises(AnswerReferenceError):
        validate_answer_for_question(result.plan.model_copy(update={'selected_blocks':result.plan.selected_blocks[:1]}),
                                     snap, result.resolved, store_id=9)
