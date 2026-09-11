from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.learn.faq import cluster_faq_rows
from app.learn.knowledge_loop import (
    KnowledgeRelationPayload,
    _obvious_conflict,
    validate_knowledge_plan,
)


CATEGORIES = [
    {"category_id": 1, "category_name": "재고", "is_system": False},
    {"category_id": 9, "category_name": "기타", "is_system": True},
]
CANDIDATE = {
    "id": 10,
    "version_id": 20,
    "title": "우유 보관",
    "content": "우유는 냉장고 2단에 보관합니다.",
    "category_id": 1,
    "category_name": "재고",
    "assignment_type": "MANUAL",
    "score": 0.8,
}


class KnowledgeLoopTest(unittest.TestCase):
    def test_only_strict_same_content_is_identical(self):
        plan = validate_knowledge_plan(
            KnowledgeRelationPayload(
                relation_type="IDENTICAL",
                target_card_id=10,
                category_name="재고",
                reason="같은 내용",
            ),
            "우유는 어디에 둬요?",
            "우유는 냉장고 2단에 보관합니다.",
            CATEGORIES,
            [CANDIDATE],
        )
        self.assertEqual(plan.relation_type, "IDENTICAL")
        self.assertEqual(plan.target_card_id, 10)

    def test_loose_identical_claim_is_downgraded_to_review(self):
        plan = validate_knowledge_plan(
            KnowledgeRelationPayload(
                relation_type="IDENTICAL",
                target_card_id=10,
                category_name="재고",
                reason="비슷함",
            ),
            "우유는 어디에 둬요?",
            "우유는 냉장고에 둡니다.",
            CATEGORIES,
            [CANDIDATE],
        )
        self.assertEqual(plan.relation_type, "SUPPLEMENT")
        self.assertFalse(plan.auto_publish)

    def test_changed_number_forces_conflict(self):
        plan = validate_knowledge_plan(
            KnowledgeRelationPayload(
                relation_type="SUPPLEMENT",
                target_card_id=10,
                category_name="재고",
                reason="보완",
            ),
            "우유는 어디에 둬요?",
            "우유는 냉장고 3단에 보관합니다.",
            CATEGORIES,
            [CANDIDATE],
        )
        self.assertEqual(plan.relation_type, "CONFLICT")
        self.assertFalse(plan.auto_publish)

    def test_changed_negation_is_conflict(self):
        self.assertTrue(
            _obvious_conflict(
                "마감 후 문을 잠그세요.", "마감 후 문을 잠그지 마세요."
            )
        )

    def test_unknown_category_falls_back_to_other(self):
        plan = validate_knowledge_plan(
            KnowledgeRelationPayload(
                relation_type="NEW",
                target_card_id=None,
                category_name="Q&A",
                reason="신규",
            ),
            "와이파이 비밀번호는?",
            "카운터 안내판을 확인하세요.",
            CATEGORIES,
            [],
        )
        self.assertEqual(plan.category_name, "기타")
        self.assertEqual(plan.category_id, 9)

    def test_existing_target_keeps_manual_category(self):
        plan = validate_knowledge_plan(
            KnowledgeRelationPayload(
                relation_type="SUPPLEMENT",
                target_card_id=10,
                category_name="기타",
                reason="보완",
            ),
            "우유는 어디에 둬요?",
            "유통기한도 확인합니다.",
            CATEGORIES,
            [CANDIDATE],
        )
        self.assertEqual(plan.category_id, 1)
        self.assertEqual(plan.category_name, "재고")

    def test_faq_clusters_similar_questions_but_not_different_intents(self):
        now = datetime.now(timezone.utc)

        def row(question: str, member: int, seconds: int) -> dict:
            return {
                "question_text": question,
                "question_key": " ".join(question.lower().split()),
                "member_id": member,
                "created_at": now + timedelta(seconds=seconds),
                "card_id": 10,
                "published_version_id": 20,
                "card_title": "우유 안내",
                "card_content": "우유 안내 본문",
                "category_id": 1,
                "category_name": "재고",
            }

        clusters = cluster_faq_rows(
            [
                row("우유는 어디에 보관해요?", 1, 1),
                row("우유 보관 위치는 어디예요?", 2, 2),
                row("우유 유통기한은 언제까지예요?", 1, 3),
            ]
        )
        counts = sorted(cluster["question_count"] for cluster in clusters)
        self.assertEqual(counts, [1, 2])
        popular = next(cluster for cluster in clusters if cluster["question_count"] == 2)
        self.assertEqual(popular["distinct_questioners"], 2)


if __name__ == "__main__":
    unittest.main()
