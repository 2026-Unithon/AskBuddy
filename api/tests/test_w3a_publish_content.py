"""W3a 공개판 사실 싣기 — 순수 도우미와 근거 순서 규칙.

실제 DB 경로(사실 카드 공개·R 소비)는 scripts/verify_w3a_fact_assembly.py 의 B 시나리오가 돈다.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.contracts.common import Variant
from app.contracts.extraction import EvidenceLocator
from app.contracts.snapshot import FactProvenance, FactRevision
from app.publish.content import (
    InvalidContent,
    _evidence_locator,
    _hash_ref,
    _merge_fact,
    _quantity_text,
    build_knowledge_content,
)

HEX = "ab" * 32


class EvidenceLocatorTest(unittest.TestCase):
    def test_evidence_locator_mapping(self):
        self.assertEqual(
            _evidence_locator("PAGE", {"page": 3, "region": "r1", "bbox": [0, 0, 1, 1]}),
            EvidenceLocator(type="PAGE", page=3))
        self.assertEqual(_evidence_locator("TIMESTAMP", {"timestamp_sec": 12}),
                         EvidenceLocator(type="TIMESTAMP", timestamp_sec=12))
        self.assertEqual(_evidence_locator("LINE", {"line": 4}),
                         EvidenceLocator(type="LINE", line=4))
        self.assertEqual(_evidence_locator("BBOX", {"bbox": [0.1, 0.2, 0.3, 0.4], "page": 2}),
                         EvidenceLocator(type="BBOX", bbox=(0.1, 0.2, 0.3, 0.4)))
        # 종류에 맞는 값이 없거나 계약 검증에 실패하면 자료 전체로 낮춘다
        self.assertEqual(_evidence_locator("PAGE", {"region": "r1"}), EvidenceLocator())
        self.assertEqual(_evidence_locator("PAGE", {"page": 0}), EvidenceLocator())
        self.assertEqual(_evidence_locator("BBOX", {"bbox": [1, 2]}), EvidenceLocator())
        self.assertEqual(_evidence_locator("WHOLE_SOURCE", {"page": 3}), EvidenceLocator())
        self.assertEqual(_evidence_locator(None, None), EvidenceLocator())
        # jsonb 가 문자열로 올 때
        self.assertEqual(_evidence_locator("LINE", '{"line": 7}'),
                         EvidenceLocator(type="LINE", line=7))
        self.assertEqual(_evidence_locator("LINE", "not json"), EvidenceLocator())


class HashRefTest(unittest.TestCase):
    def test_hash_ref_mapping(self):
        self.assertEqual(_hash_ref(HEX), "sha256:" + HEX)
        self.assertEqual(_hash_ref("sha256:" + HEX), "sha256:" + HEX)
        self.assertIsNone(_hash_ref(HEX.upper()))
        self.assertIsNone(_hash_ref("abc"))
        self.assertIsNone(_hash_ref(None))


class QuantityTextTest(unittest.TestCase):
    def test_quantity_text(self):
        self.assertEqual(_quantity_text(Decimal("225.00")), "225")
        self.assertEqual(_quantity_text(Decimal("0.50")), "0.5")
        self.assertEqual(_quantity_text(Decimal("100")), "100")
        self.assertEqual(_quantity_text(Decimal("-1.5")), "-1.5")


def _occ(n: int) -> FactProvenance:
    return FactProvenance(occurrence_id=str(n), source_id="9",
                          source_content_hash="sha256:" + HEX)


def _fact(provenance, requires=(), **over) -> FactRevision:
    fields = dict(fact_revision_id="10", fact_id="3", entity_id="4",
                  original_assertion="음료Z 물 225ml", assertion="음료Z 물 225ml",
                  subject="음료Z", predicate="물", variant=Variant(temperature="ICE"),
                  quantity={"value": "225", "unit": "ml"}, requires=tuple(requires),
                  provenance=tuple(provenance))
    fields.update(over)
    return FactRevision(**fields)


class MergeFactTest(unittest.TestCase):
    def test_merge_fact_unions_provenance_and_requires(self):
        owner = FactProvenance(owner_answer_id="2")
        a = _fact([_occ(30), owner, _occ(5)], requires=("8",))
        b = _fact([_occ(5), _occ(12)], requires=("7", "8"))
        merged = _merge_fact(a, b)
        self.assertEqual(merged.provenance, (_occ(5), _occ(12), _occ(30), owner))
        self.assertEqual(merged.requires, ("7", "8"))
        self.assertEqual(merged.model_dump(exclude={"provenance", "requires"}),
                         a.model_dump(exclude={"provenance", "requires"}))

        # 근거 합집합은 50 개까지 — 정렬 앞쪽을 남긴다
        big_a = _fact([_occ(n) for n in range(1, 41)])
        big_b = _fact([_occ(n) for n in range(31, 71)])
        big = _merge_fact(big_a, big_b)
        self.assertEqual([p.occurrence_id for p in big.provenance],
                         [str(n) for n in range(1, 51)])

        with self.assertRaises(InvalidContent):
            _merge_fact(a, _fact([_occ(5)], assertion="음료Z 물 275ml"))
        with self.assertRaises(InvalidContent):
            _merge_fact(a, _fact([_occ(5)], variant=Variant(temperature="HOT")))


class _FactConn:
    """사실 카드 판 하나(블록 b1·사실 판 10)를 돌려준다. 근거 행은 주어진 순서 그대로."""

    def __init__(self, provenance_rows):
        self.provenance_rows = provenance_rows

    async def fetchrow(self, query, *args):
        if "from card_versions" in query:
            return {"title": "음료Z"}
        raise AssertionError(f"받지 않는 조회: {query}")

    async def fetch(self, query, *args):
        if "from card_version_blocks" in query:
            return [{"block_id": "b1", "kind": "QUANTITIES", "block_order": 1,
                     "raw_span_id": None}]
        if "from card_block_facts" in query:
            return [{"block_id": "b1", "fact_revision_id": 10, "position": 1}]
        if "from fact_revisions" in query:
            return [{"fact_revision_id": 10, "fact_id": 3, "entity_id": 4,
                     "original_assertion": "음료Z 물 225ml", "assertion": "음료Z 물 225ml",
                     "subject": "음료Z", "predicate": "물", "variant_temperature": "ICE",
                     "variant_size": None, "quantity_value": Decimal("225.00"),
                     "quantity_unit": "ml", "value_text": None, "polarity": "AFFIRM",
                     "step_order": None, "conditions": "[]", "exceptions": "[]"}]
        if "from fact_revision_requires" in query:
            return []
        if "from card_version_fact_provenance" in query:
            return self.provenance_rows
        raise AssertionError(f"받지 않는 조회: {query}")


def _prov_row(provenance_id, *, occurrence=None, owner=None, source=9):
    return {"provenance_id": provenance_id, "fact_revision_id": 10,
            "occurrence_id": occurrence, "owner_answer_id": owner,
            "source_id": source if occurrence is not None else None,
            "source_content_hash": HEX if occurrence is not None else None,
            "locator_type": "LINE" if occurrence is not None else None,
            "locator": '{"line": 2}' if occurrence is not None else None}


class FactCardProvenanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_single_card_provenance_order_matches_merge_rule(self):
        # SQL 순서(provenance_id)와 다르게 섞인 근거 55 + 점주 답변 1
        rows = [_prov_row(1, owner=2)]
        rows += [_prov_row(100 + n, occurrence=occ) for n, occ in enumerate(range(60, 5, -1))]
        content = await build_knowledge_content(
            _FactConn(rows), store_id=7, manifest={1: 10}, glossary_version="glossary/v1")
        (fact,) = content.fact_revisions
        self.assertEqual([p.occurrence_id for p in fact.provenance],
                         [str(n) for n in range(6, 56)])
        # 같은 근거를 두 카드에서 합친 결과와 순서가 같다
        self.assertEqual(_merge_fact(fact, fact).provenance, fact.provenance)

        # 점주 답변 출처(파일 없음)는 싣지 않는다 — 파일 근거만 occurrence 순서로
        content = await build_knowledge_content(
            _FactConn([_prov_row(1, owner=2), _prov_row(2, occurrence=30),
                       _prov_row(3, occurrence=5)]),
            store_id=7, manifest={1: 10}, glossary_version="glossary/v1")
        self.assertEqual(content.fact_revisions[0].provenance,
                         (FactProvenance(occurrence_id="5", source_id="9",
                                         source_content_hash="sha256:" + HEX,
                                         locator=EvidenceLocator(type="LINE", line=2)),
                          FactProvenance(occurrence_id="30", source_id="9",
                                         source_content_hash="sha256:" + HEX,
                                         locator=EvidenceLocator(type="LINE", line=2))))

    async def test_missing_occurrence_row_is_invalid_not_none_source(self):
        row = _prov_row(1, occurrence=5)
        row["source_id"] = None  # left join 이 빈 경우
        with self.assertRaises(InvalidContent):
            await build_knowledge_content(
                _FactConn([row]), store_id=7, manifest={1: 10},
                glossary_version="glossary/v1")


if __name__ == "__main__":
    unittest.main()
