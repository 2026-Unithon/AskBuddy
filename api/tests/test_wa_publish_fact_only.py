"""Phase A Task 2 — 공개판은 사실 블록 카드만 싣는다."""
from __future__ import annotations

import inspect
import unittest
from decimal import Decimal

from app import config
from app.publish import approval, content
from app.publish.content import InvalidContent, NoProvenance, build_knowledge_content

HEX = "ab" * 32


class _Conn:
    """판 하나. blocks·facts·provenance 를 주어진 대로 돌려준다."""

    def __init__(self, *, blocks, facts, provenance=()):
        self.blocks, self.facts, self.provenance = blocks, facts, list(provenance)

    async def fetchrow(self, query, *args):
        if "from card_versions" in query:
            return {"title": "음료Z"}
        raise AssertionError(query)

    async def fetch(self, query, *args):
        if "from card_version_blocks" in query:
            return self.blocks
        if "from card_block_facts" in query:
            return self.facts
        if "from fact_revisions" in query:
            return [{"fact_revision_id": 10, "fact_id": 3, "entity_id": 4,
                     "original_assertion": "음료Z 물 225ml", "assertion": "음료Z 물 225ml",
                     "subject": "음료Z", "predicate": "물", "variant_temperature": None,
                     "variant_size": None, "quantity_value": Decimal("225"),
                     "quantity_unit": "ml", "value_text": None, "polarity": "AFFIRM",
                     "step_order": None, "conditions": "[]", "exceptions": "[]"}]
        if "from fact_revision_requires" in query:
            return []
        if "from card_version_fact_provenance" in query:
            return self.provenance
        raise AssertionError(query)


_FACT_BLOCK = [{"block_id": "b1", "kind": "QUANTITIES", "block_order": 1, "raw_span_id": None}]
_FACT_ROW = [{"block_id": "b1", "fact_revision_id": 10, "position": 1}]


def _occ_row():
    return {"provenance_id": 1, "fact_revision_id": 10, "occurrence_id": 5, "owner_answer_id": None,
            "source_id": 9, "source_content_hash": HEX, "locator_type": "LINE",
            "locator": '{"line": 1}'}


def _owner_row():
    return {"provenance_id": 2, "fact_revision_id": 10, "occurrence_id": None,
            "owner_answer_id": 7, "source_id": None, "source_content_hash": None,
            "locator_type": None, "locator": None}


class FactOnlyContentTest(unittest.IsolatedAsyncioTestCase):
    async def test_blockless_version_is_invalid(self):
        with self.assertRaises(InvalidContent):
            await build_knowledge_content(_Conn(blocks=[], facts=[]), store_id=7,
                                          manifest={1: 10}, glossary_version="glossary/v1")

    async def test_raw_block_version_is_invalid(self):
        raw = [{"block_id": "raw1", "kind": "RAW", "block_order": 1, "raw_span_id": 500}]
        with self.assertRaises(InvalidContent):
            await build_knowledge_content(_Conn(blocks=raw, facts=[]), store_id=7,
                                          manifest={1: 10}, glossary_version="glossary/v1")

    async def test_owner_answer_only_provenance_is_not_published(self):
        with self.assertRaises(NoProvenance):
            await build_knowledge_content(
                _Conn(blocks=_FACT_BLOCK, facts=_FACT_ROW, provenance=[_owner_row()]),
                store_id=7, manifest={1: 10}, glossary_version="glossary/v1")

    async def test_fact_card_publishes_without_raw_spans(self):
        result = await build_knowledge_content(
            _Conn(blocks=_FACT_BLOCK, facts=_FACT_ROW, provenance=[_occ_row(), _owner_row()]),
            store_id=7, manifest={1: 10}, glossary_version="glossary/v1")
        self.assertEqual(result.raw_spans, ())
        (fact,) = result.fact_revisions
        self.assertEqual([p.occurrence_id for p in fact.provenance], ["5"])


def test_raw_helpers_and_flag_are_gone():
    for name in ("ensure_raw_blocks", "_resolve_provenance", "_raw_block", "_split_raw_spans"):
        assert not hasattr(content, name), name
    assert not hasattr(approval, "_fix_blocks")
    assert "allow_owner_answer" not in inspect.signature(build_knowledge_content).parameters
    assert "w_owner_answer_raw_publish" not in config.Settings.model_fields
