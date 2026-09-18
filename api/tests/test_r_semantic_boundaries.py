"""Synthetic boundary audit. Strict xfails are open defects, never quality passes."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.learn.answering import GroundedAnswerPayload, validate_grounded_payload
from app.learn.router import _question_key
from app.reg.retrieve import retrieve_question


def card(content="재료 A 100ml, 재료 B 200ml", title="합성 음료"):
    return dict(id=10, version_id=20, title=title, content=content,
                category="합성", score=0.99)


def accepted(answer, source):
    return validate_grounded_payload(
        GroundedAnswerPayload(answer=answer, card_ids=[10]), [card(source)]
    )[0]


def test_original_text_is_supported():
    assert accepted("재료 A 100ml", "재료 A 100ml")


def test_unknown_quantity_is_blocked():
    assert not accepted("재료 A 900ml", "재료 A 100ml")


def test_only_case_and_whitespace_grouping_is_supported():
    assert _question_key(" WiFi  비밀번호 ") == _question_key("wifi 비밀번호")
    assert _question_key("우유 어디?") != _question_key("우유 보관 위치?")


@pytest.mark.xfail(strict=True, reason="R-B02: quantity membership loses subject binding")
def test_swapped_quantities_must_be_blocked():
    assert not accepted("재료 A 200ml, 재료 B 100ml", "재료 A 100ml, 재료 B 200ml")


@pytest.mark.xfail(strict=True, reason="R-B03: word subset permits condition deletion")
def test_removed_condition_must_be_blocked():
    assert not accepted("재료 A 100ml", "주말에만 재료 A 100ml")


@pytest.mark.xfail(strict=True, reason="R-B04: textual key has no resolved context")
def test_unknown_followup_must_not_get_a_shared_semantic_key():
    # With no resolved entity, the same follow-up from two contexts cannot
    # safely be treated as a semantic duplicate. None means do not merge.
    assert _question_key("그럼 따뜻한 건?") is None


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="R-B01: common entity is not predicate sufficiency")
async def test_location_card_must_not_answer_price_question():
    class Db:
        async def fetch(self, *_args):
            return [card("우유는 냉장고에 보관", "우유 보관 위치")]

    with (
        patch("app.reg.retrieve.embed_text", return_value=[0.0]),
        patch("app.reg.retrieve.vector_literal", return_value="[0]"),
        patch("app.reg.retrieve.get_settings", return_value=SimpleNamespace(retrieval_threshold=0.35)),
    ):
        result = await retrieve_question(Db(), 1, "우유 가격 얼마?")
    assert result["kind"] == "miss"
