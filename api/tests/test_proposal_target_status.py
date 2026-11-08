"""제안 목록에 대상 카드 상태(2026-11-08). 삭제된 카드에 걸린 제안을 화면이 검수 필요 수에서 뺀다."""
import unittest
from datetime import datetime, timezone

from app.learn import router as learn_router


class Db:
    def __init__(self):
        self.query = ""

    async def fetch(self, query, *args):
        self.query = query
        return [dict(proposal_id=9, relation_type="CONFLICT", status="PENDING_REVIEW", question_text="질문", answer_text="답",
                     target_card_id=3, target_version_id=30, current_title="카드", current_content="본문",
                     proposed_title=None, proposed_content=None, reason=None, answer_source_id=1, affected_cards="[]",
                     category_id=10, created_at=datetime(2026, 11, 8, tzinfo=timezone.utc), target_review_status="EXCLUDED")]


class ProposalTargetStatusTest(unittest.IsolatedAsyncioTestCase):
    async def test_items_carry_target_status(self):
        db = Db()
        result = await learn_router.list_knowledge_proposals(db, {"role": "OWNER"}, 1, "PENDING_REVIEW")
        self.assertEqual(result["items"][0]["target_review_status"], "EXCLUDED")
        self.assertIn("target.review_status as target_review_status", db.query)
        self.assertIn("target.store_id = p.store_id", db.query)
