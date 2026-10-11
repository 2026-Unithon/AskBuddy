"""Phase A Task 6 — 점주 답변 결과 판정(순수)."""
from __future__ import annotations

from app.cards.owner_answer_worker import decide_outcome
from app.ingest.owner_text import AnswerCard


def card(cid, *, draft, published=None, status="PENDING", reason=None):
    return AnswerCard(card_id=cid, draft_version_id=draft, published_version_id=published,
                      review_status=status, needs_review_reason=reason)


def test_no_facts_reports_review_without_card():
    out = decide_outcome(0, [])
    assert (out.kind, out.relation, out.cards, out.target) == ("NO_FACTS", "NEW", (), None)


def test_facts_without_cards_is_pending():
    assert decide_outcome(2, []).kind == "FACTS_PENDING"


def test_new_cards_publish():
    out = decide_outcome(2, [card(5, draft=50), card(6, draft=60)])
    assert (out.kind, out.relation) == ("PUBLISH", "NEW")
    assert [c.card_id for c in out.cards] == [5, 6]


def test_new_card_needing_review_blocks_publish():
    out = decide_outcome(1, [card(5, draft=50, status="NEEDS_REVIEW", reason="NO_PROVENANCE")])
    assert (out.kind, out.relation) == ("REVIEW", "NEW")


def test_published_card_with_new_draft_is_supplement():
    changed = card(7, draft=71, published=70, status="APPROVED", reason="NEW_FACTS")
    out = decide_outcome(2, [changed, card(8, draft=80)])
    assert (out.kind, out.relation) == ("REVIEW", "SUPPLEMENT")
    assert out.target == changed
    assert [c.card_id for c in out.cards] == [7, 8]


def test_identical_facts_link():
    linked = card(9, draft=90, published=90, status="APPROVED")
    out = decide_outcome(1, [linked])
    assert (out.kind, out.relation, out.target) == ("LINKED", "IDENTICAL", linked)


def test_linked_and_new_publishes_new_only():
    out = decide_outcome(2, [card(9, draft=90, published=90, status="APPROVED"), card(10, draft=100)])
    assert out.kind == "PUBLISH"
    assert [c.card_id for c in out.cards] == [10]


def test_legacy_owner_answer_functions_are_gone():
    from app.learn import knowledge_apply as ka
    for name in ("prepare_proposal", "publish_new_proposal", "publish_existing_proposal",
                 "create_owner_answer_card"):
        assert not hasattr(ka, name), name
