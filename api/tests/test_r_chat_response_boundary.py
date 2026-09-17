import unittest
from uuid import uuid4

from pydantic import ValidationError
from app.contracts.chat import ChatResponse, Citation, POLICY_MESSAGES


class ChatResponseBoundaryTest(unittest.TestCase):
    def test_non_clarify_actions_reject_context_and_empty_slot(self):
        for action in ("REFUSE", "SAFE_ROUTE", "ESCALATE"):
            values = dict(request_id="synthetic", snapshot_id="1", knowledge_revision="1",
                          action=action, message=POLICY_MESSAGES.get(action, "확인 중"))
            if action == "ESCALATE":
                values["pending_id"] = "2"
            for extra in (dict(context_id=uuid4()), dict(clarification_slot="")):
                with self.subTest(action=action, extra=extra), self.assertRaises(ValidationError):
                    ChatResponse(**values, **extra)

    def test_duplicate_citation_does_not_inflate_count(self):
        citation = Citation(card_id="1",card_version_id="2",block_id="b",
                            fact_revision_id="3",source_id="4")
        with self.assertRaises(ValidationError):
            ChatResponse(request_id="synthetic",snapshot_id="1",knowledge_revision="1",
                         action="ANSWER",message="승인 원문",citations=(citation,citation))

    def test_duplicate_or_empty_clarification_options_rejected(self):
        for options in (("HOT", "HOT"), ("", "ICE")):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                ChatResponse(request_id="synthetic",snapshot_id="1",knowledge_revision="1",
                    action="CLARIFY",message="규격 확인",context_id=uuid4(),
                    clarification_slot="temperature",allowed_options=options)
