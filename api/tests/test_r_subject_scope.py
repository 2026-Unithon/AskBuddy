"""질문이 가리키는 대상·속성을 찾는 범위. 추정이 아니라 글자 일치만 넓힌다."""
from datetime import datetime, timezone

import pytest

from app.contracts.hashing import snapshot_digest
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.card_read import requested_card
from app.learn.planner import decide, shared_terms
from app.learn.semantic_grouping import supported_question
from app.reg.hybrid import Candidate, SearchResult

MENU = [("1", "아이스아메리카노", "제조 순서"), ("2", "카라멜마끼아또", "제조 순서"),
        ("3", "카페모카", "제조 순서"), ("4", "환불 규정", "환불"),
        ("5", "오픈 준비", "영업 시작"), ("6", "쓰레기 배출", "폐기물 분리")]


def search():
    cards = [dict(card_id=i, card_version_id=i, entity_id=i, title=t,
                  blocks=[dict(block_id="b", kind="STEPS", order=1, fact_revision_ids=[i])])
             for i, t, _ in MENU]
    facts = [dict(fact_revision_id=i, fact_id=i, entity_id=i, subject=t, predicate=p,
                  assertion=f"{t} 내용", original_assertion=f"{t} 내용", variant=dict(),
                  provenance=[dict(occurrence_id=i, source_id="1")]) for i, t, p in MENU]
    snapshot = PublishedKnowledgeSnapshot.model_validate(dict(
        store_id="9", snapshot_id="1", knowledge_revision="1", snapshot_hash="sha256:" + "0" * 64,
        created_at=datetime.now(timezone.utc), glossary_version="t/v1",
        renderer_version="r-approved/v2", cards=cards, fact_revisions=facts))
    snapshot = snapshot.model_copy(update={"snapshot_hash": snapshot_digest(snapshot)})
    return SearchResult(snapshot, 0, tuple(Candidate(i, i, "b", 1, 0, .02) for i, _, _ in MENU), "")


@pytest.mark.parametrize("question,expected", [
    ("환불", ("환불 규정",)), ("환불 어떻게 해", ("환불 규정",)),
    ("오픈시간", ("오픈 준비",)), ("쓰레기 어디에 버려", ("쓰레기 배출",))])
def test_partial_name_narrows_the_offer_instead_of_listing_every_card(question, expected):
    """제목 일부만 말해도 후보 전체를 고르라고 하지 않는다."""
    plan = decide(search(), store_id=9, question=question).plan
    assert plan.action == "CLARIFY" and plan.clarification_slot == "entity"
    assert plan.allowed_options == expected


@pytest.mark.parametrize("question", ["아아", "아아 만드는 법", "ㅡ", "주차는 어디에 해요?"])
def test_question_sharing_no_term_with_any_card_escalates(question):
    """글자가 하나도 겹치지 않으면 되묻지 않고 넘긴다. 추측을 직원에게 떠넘기지 않는다."""
    plan = decide(search(), store_id=9, question=question).plan
    assert plan.action == "ESCALATE" and plan.escalation_reason == "INSUFFICIENT_KNOWLEDGE"
    assert plan.allowed_options == ()


def test_shared_terms_ignores_single_character_overlap():
    assert shared_terms("환불 어떻게 해", ("환불 규정",))
    assert not shared_terms("아아", ("아이스아메리카노",))


@pytest.mark.parametrize("task",["한 건을 환불하려면 어떻게 처리해?", "오픈 전에 어떤 비품부터 확인해야 해?"])
def test_operating_question_does_not_offer_incidental_menu_names(task):
    result=decide(search(),store_id=9,question="카페모카랑 카라멜마끼아또 주문이 있어. "+task)
    assert result.plan.action=="ESCALATE" and result.plan.escalation_reason=="NO_RELEVANT_TASK_OPTION"
    assert result.plan.allowed_options==()


def test_recipe_question_after_refund_background_keeps_recipe_options():
    result=decide(search(),store_id=9,question="환불은 끝났어. 카페모카랑 카라멜마끼아또 제조 방법 알려줘.")
    assert set(result.plan.allowed_options)=={"카페모카","카라멜마끼아또"}


def test_positive_task_option_can_be_supported_by_block_text_with_neutral_title():
    from dataclasses import replace
    base=search()
    facts=tuple(f.model_copy(update={"assertion":"이 상품은 영수증으로 환불한다."}) if f.fact_id=="2" else f
                for f in base.snapshot.fact_revisions)
    snap=base.snapshot.model_copy(update={"fact_revisions":facts})
    snap=snap.model_copy(update={"snapshot_hash":snapshot_digest(snap)})
    result=decide(replace(base,snapshot=snap),store_id=9,question="카페모카랑 카라멜마끼아또 환불 기준은?")
    assert result.plan.allowed_options==("카라멜마끼아또",)


@pytest.mark.parametrize("question", [
    "아이스아메리카노 만드는 법", "아이스아메리카노 만드는 방법", "아이스아메리카노 만드는법 좀",
    "아이스아메리카노 레시피", "아이스아메리카노 순서", "아이스아메리카노 제조법"])
def test_recipe_request_names_are_accepted_as_one_card_read(question):
    card = requested_card(search().snapshot, question)
    assert card is not None and card.title == "아이스아메리카노"


@pytest.mark.parametrize("question", [
    "아이스아메리카노 어떻게 만들어?", "아이스아메리카노 맛있게 만드는 법", "만드는 법"])
def test_free_or_modified_requests_are_not_card_reads(question):
    """서술형 자유 질문과 모르는 수식어는 원문 전체 열람을 승인하지 않는다."""
    assert requested_card(search().snapshot, question) is None


def test_named_attribute_is_supported_only_when_nothing_else_is_left():
    """승인 속성 이름을 그대로 말한 요청만 지원한다. 남는 낱말이 있으면 아니다."""
    assert supported_question("환불 규정 환불", titles=("환불 규정",), predicate="환불")
    assert supported_question("환불 규정의 환불 알려줘", titles=("환불 규정",), predicate="환불")
    assert not supported_question("환불 규정 환불 언제까지", titles=("환불 규정",), predicate="환불")
    assert not supported_question("환불 규정 알려줘", titles=("환불 규정",), predicate="환불")


def test_missing_predicate_name_is_not_supported():
    """predicate 는 계약상 None 일 수 있다. 이름이 없으면 지원하지 않는다."""
    assert not supported_question("환불 규정", titles=("환불 규정",), predicate=None)
    assert not supported_question("환불 규정 X", titles=("환불 규정",), predicate="X")
