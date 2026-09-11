from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.learn.answering import (
    GroundedAnswerPayload,
    compose_grounded_answer,
    validate_grounded_payload,
)
from app.learn.router import _question_key
from app.reg.retrieve import retrieve_question


def _card(
    card_id: int = 10,
    *,
    content: str = "우유는 냉장고 둘째 선반에 보관하세요.",
) -> dict:
    return {
        "id": card_id,
        "version_id": 20,
        "title": "우유 보관 위치",
        "content": content,
        "category": "재료 관리",
        "score": 0.8,
    }


class GroundedAnswerValidationTest(unittest.IsolatedAsyncioTestCase):
    def test_accepts_answer_using_only_selected_card_facts(self):
        valid, reason, selected = validate_grounded_payload(
            GroundedAnswerPayload(
                answer="우유는 냉장고 둘째 선반에 보관하세요.", card_ids=[10]
            ),
            [_card()],
        )
        self.assertTrue(valid)
        self.assertIsNone(reason)
        self.assertEqual([card["id"] for card in selected], [10])

    def test_rejects_unknown_citation(self):
        valid, reason, _ = validate_grounded_payload(
            GroundedAnswerPayload(answer="우유를 보관하세요.", card_ids=[999]),
            [_card()],
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "unknown_citation")

    def test_rejects_number_not_present_in_card(self):
        valid, reason, _ = validate_grounded_payload(
            GroundedAnswerPayload(answer="우유는 냉장고 3층에 보관하세요.", card_ids=[10]),
            [_card()],
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "unsupported_number")

    def test_rejects_attached_number_not_present_in_card(self):
        valid, reason, _ = validate_grounded_payload(
            GroundedAnswerPayload(answer="우유는 냉장고 3층에 보관하세요.", card_ids=[10]),
            [_card(content="우유는 냉장고 2층에 보관하세요.")],
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "unsupported_number")

    def test_rejects_new_location_or_entity_term(self):
        valid, reason, _ = validate_grounded_payload(
            GroundedAnswerPayload(
                answer="우유는 창고 둘째 선반에 보관하세요.", card_ids=[10]
            ),
            [_card()],
        )
        self.assertFalse(valid)
        self.assertEqual(reason, "unsupported_terms")

    async def test_extractive_mode_returns_only_top_card(self):
        settings = SimpleNamespace(answer_mode="extractive", gemini_api_key="")
        with patch("app.learn.answering.get_settings", return_value=settings):
            result = await compose_grounded_answer("우유는 어디에 둬요?", [_card()])
        self.assertEqual(result.source, "CARD_ORIGINAL")
        self.assertEqual(result.grounding_status, "FALLBACK")
        self.assertEqual(result.content, _card()["content"])
        self.assertEqual(result.fallback_reason, "extractive_mode")

    async def test_missing_llm_key_falls_back_to_card_original(self):
        settings = SimpleNamespace(answer_mode="grounded_llm", gemini_api_key="")
        with patch("app.learn.answering.get_settings", return_value=settings):
            result = await compose_grounded_answer("우유는 어디에 둬요?", [_card()])
        self.assertEqual(result.source, "CARD_ORIGINAL")
        self.assertEqual(result.fallback_reason, "missing_api_key")

    def test_question_key_collapses_case_and_spaces(self):
        self.assertEqual(_question_key("  WiFi   비밀번호  "), "wifi 비밀번호")

    async def test_question_without_subject_does_not_embed_or_call_llm(self):
        with patch("app.reg.retrieve.embed_text", side_effect=AssertionError):
            result = await retrieve_question(None, 1, "어떻게 해요?")
        self.assertEqual(result["kind"], "miss")
        self.assertEqual(result["reason"], "no_anchor")

    async def test_high_vector_score_cannot_bypass_subject_mismatch(self):
        class FakeDb:
            async def fetch(self, *_args):
                return [
                    {
                        "id": 10,
                        "version_id": 20,
                        "title": "우유 보관 위치",
                        "content": "우유는 냉장고에 보관하세요.",
                        "category": "재료 관리",
                        "score": 0.99,
                    }
                ]

        settings = SimpleNamespace(retrieval_threshold=0.35)
        with (
            patch("app.reg.retrieve.embed_text", return_value=[0.0]),
            patch("app.reg.retrieve.vector_literal", return_value="[0]"),
            patch("app.reg.retrieve.get_settings", return_value=settings),
        ):
            result = await retrieve_question(FakeDb(), 1, "주차장은 어디예요?")
        self.assertEqual(result["kind"], "miss")
        self.assertEqual(result["reason"], "intent_mismatch")


if __name__ == "__main__":
    unittest.main()
