import json
import unittest
from pathlib import Path
from pydantic import ValidationError

from app.contracts.snapshot import KnowledgeContent, PublishedKnowledgeSnapshot
from app.contracts.hashing import digest, knowledge_content_payload, verify_snapshot_hash
from app.reg.index_preparation import documents


class IndexContentTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = PublishedKnowledgeSnapshot.model_validate_json((Path(__file__).parent/
            "fixtures/contracts/v1/snapshot.json").read_text(encoding="utf-8"))
        self.payload = {k:v for k,v in self.snapshot.model_dump().items()
                        if k in KnowledgeContent.model_fields}

    def test_content_does_not_allocate_publication_ids(self):
        content = KnowledgeContent(**self.payload)
        self.assertNotIn("snapshot_id",content.model_dump())
        self.assertNotIn("knowledge_revision",content.model_dump())
        self.assertTrue(documents(content))
        verify_snapshot_hash(self.snapshot)

    def test_content_reuses_snapshot_reference_validation(self):
        self.payload["fact_revisions"] = ()
        with self.assertRaises(ValidationError):
            KnowledgeContent(**self.payload)

    def test_content_hash_independent_of_card_container_order(self):
        a = KnowledgeContent(**self.payload)
        self.payload["cards"] = tuple(reversed(self.payload["cards"]))
        b = KnowledgeContent(**self.payload)
        self.assertEqual(digest(knowledge_content_payload(a)),digest(knowledge_content_payload(b)))

    def test_raw_is_preserved_and_derived_search_text_separate(self):
        content = KnowledgeContent(**self.payload)
        docs = documents(content)
        for card in content.cards:
            for block in card.blocks:
                if block.raw_span_id:
                    span = next(r for r in content.raw_spans if r.raw_span_id==block.raw_span_id)
                    doc = next(d for d in docs if d.card_id==card.card_id and d.block_id==block.block_id)
                    self.assertEqual(doc.approved_text,span.text)
                    self.assertTrue(doc.retrieval_text.startswith(card.title))
