import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from app.contracts.chat import QuestionContext
from app.errors import ApiError
from app.learn.question_contexts import (
    StoredContext, accept_selection, create_context, load_context,
)


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        self.stored = StoredContext(QuestionContext(context_id=uuid4(), store_id="1",
            member_id="2", chat_session_id="3", contract_version="v2",
            original_question="그럼 따뜻한 건?", expires_at=self.now+timedelta(minutes=5),
            confirmed_slots={"entity": "라테"},
            proposed_slots={"temperature": "ICE", "predicate": "수량"}, clarify_turns=1),
            1, 7, "temperature", ("HOT", "ICE"))

    def accept(self, **kwargs):
        args = dict(option="HOT", expected_state_revision=1, knowledge_revision=7, now=self.now)
        args.update(kwargs)
        return accept_selection(self.stored, **args)

    def test_explicit_choice_only_and_ttl(self):
        result = self.accept()
        self.assertEqual(result.context.confirmed_slots, {"entity": "라테", "temperature": "HOT"})
        self.assertEqual(result.context.proposed_slots, {"predicate": "수량"})
        self.assertEqual(result.context.expires_at, self.now+timedelta(minutes=10))
        self.assertIsNone(result.offered_slot)
        self.assertEqual(self.stored.context.confirmed_slots, {"entity": "라테"})

    def test_new_publication_keeps_only_confirmed_user_slots(self):
        result = self.accept(knowledge_revision=8)
        self.assertEqual(result.context.proposed_slots, {})
        self.assertEqual(result.context.confirmed_slots["entity"], "라테")

    def test_expiry_boundary_and_bad_choice_do_not_mutate(self):
        for kwargs, code in ((dict(now=self.stored.context.expires_at), "CONTEXT_EXPIRED"),
                             (dict(option="모델이 만든 값"), "INVALID_CONTRACT"),
                             (dict(expected_state_revision=0), "INVALID_CONTRACT"),
                             (dict(knowledge_revision=True), "INVALID_CONTRACT")):
            with self.subTest(kwargs=kwargs), self.assertRaises(ApiError) as caught:
                self.accept(**kwargs)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.stored.state_revision, 1)

    def test_same_offer_cannot_be_consumed_twice(self):
        self.stored = self.accept()
        with self.assertRaises(ApiError):
            self.accept(expected_state_revision=2)

    def test_old_publication_cannot_replace_current_context(self):
        with self.assertRaises(ApiError) as caught:
            self.accept(knowledge_revision=6)
        self.assertEqual(caught.exception.code, "STALE_KNOWLEDGE")

    def test_original_question_preserves_whitespace(self):
        values = self.stored.context.model_dump()
        values["original_question"] = "  합성 원문\n"
        self.assertEqual(QuestionContext(**values).original_question, "  합성 원문\n")


class ContextOwnershipTest(unittest.IsolatedAsyncioTestCase):
    async def test_caller_transaction_required(self):
        conn = AsyncMock()
        conn.is_in_transaction = lambda: False
        with self.assertRaises(RuntimeError):
            await load_context(conn, store_id=1, member_id=2, session_id=3, context_id=uuid4())
        conn.fetchrow.assert_not_called()

    async def test_cross_scope_returns_not_found_before_expiry(self):
        conn = AsyncMock()
        conn.is_in_transaction = lambda: True
        conn.fetchrow.side_effect = [{"session_id": 3}, None]
        context_id = uuid4()
        with self.assertRaises(ApiError) as caught:
            await load_context(conn, store_id=1, member_id=2, session_id=3, context_id=context_id)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(conn.fetchrow.call_args.args[1:], (1, 2, 3, context_id))
        conn.fetchval.assert_not_called()

    async def test_v1_session_cannot_create_v2_context(self):
        conn = AsyncMock()
        conn.is_in_transaction = lambda: True
        conn.fetchrow.return_value = None
        with self.assertRaises(ApiError) as caught:
            await create_context(conn, store_id=1, member_id=2, session_id=3,
                original_question="합성 질문", confirmed_slots={}, proposed_slots={},
                knowledge_revision=1, slot="temperature", options=("HOT", "ICE"))
        self.assertEqual(caught.exception.status_code, 404)
        self.assertIn("s.contract_version='v2'", conn.fetchrow.call_args.args[0])
        self.assertEqual(conn.fetchrow.await_count, 1)
