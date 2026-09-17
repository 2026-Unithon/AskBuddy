import unittest
from uuid import uuid4

from pydantic import ValidationError
from app.learn.v2_router import ChatRequest
from app.learn.answer_storage import request_body_hash
from app.contracts.hashing import digest


class PolicyConfirmationTest(unittest.TestCase):
    def test_confirmation_cannot_also_choose_clarification(self):
        with self.assertRaises(ValidationError):
            ChatRequest(request_id='test-policy',session_id='1',question='HOT',policy_receipt_id='2',
                        context_id=uuid4(),context_revision=1,option='HOT')

    def test_existing_request_hash_preserved(self):
        self.assertEqual(request_body_hash(session_id=1,question='질문',choice=None),
                         digest(dict(session_id=1,question='질문',choice=None)))

    def test_confirmation_source_changes_hash(self):
        hashes={request_body_hash(session_id=1,question='질문',choice=None,policy_receipt_id=source)
                for source in (None,'1','2')}
        self.assertEqual(len(hashes),3)
