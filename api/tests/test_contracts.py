"""C0 공통 계약 테스트 — W 생산자와 R 소비자가 같은 계약을 쓰는지 고정한다.

계약이 깨지면 여기서 걸려야 한다. 런타임까지 가면 그 실행이 통째로 못 쓰게 된다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.contracts import (
    Assertion,
    AnswerPlan,
    CardBlock,
    CardPlan,
    EvidenceLocator,
    ExtractionEnvelope,
    FactRevision,
    OccurrenceDisposition,
    PublishedCard,
    PublishedKnowledgeSnapshot,
    Quantity,
    SelectedBlock,
    Variant,
    as_id,
)


class IdTest(unittest.TestCase):
    def test_bigint_becomes_decimal_string(self):
        """JS Number 는 2^53 을 넘으면 정밀도를 잃는다. 경계에서 문자열로 넘긴다."""
        self.assertEqual(as_id(9007199254740993), "9007199254740993")

    def test_non_numeric_id_rejected(self):
        with self.assertRaises(ValueError):
            as_id("abc")


class VariantTest(unittest.TestCase):
    def test_null_variant_means_unspecified_not_wildcard(self):
        """미확정은 '모든 규격에 통용' 이 아니다. 여러 규격이 가능하면 되물어야 한다."""
        self.assertTrue(Variant().is_unspecified())
        self.assertFalse(Variant(temperature="ICE").is_unspecified())


class QuantityTest(unittest.TestCase):
    def test_value_is_decimal_string_with_unit(self):
        q = Quantity(value="225", unit="ml")
        self.assertEqual(q.value, "225")

    def test_non_numeric_value_rejected(self):
        with self.assertRaises(ValidationError):
            Quantity(value="가득", unit="ml")


class ExtractionTest(unittest.TestCase):
    def _a(self, ref="a1", **kw):
        return Assertion(local_ref=ref, original_assertion="ICE 라떼 우유 225ml", **kw)

    def test_timestamp_locator_requires_a_timestamp(self):
        with self.assertRaises(ValidationError):
            EvidenceLocator(type="TIMESTAMP")

    def test_quantity_and_text_value_are_exclusive(self):
        with self.assertRaises(ValidationError):
            self._a(quantity=Quantity(value="225", unit="ml"), value_text="가득")

    def test_duplicate_local_ref_rejected(self):
        with self.assertRaises(ValidationError):
            ExtractionEnvelope(source_id="1",
                               assertions=[self._a("a"), self._a("a")])

    def test_requires_must_point_inside_the_segment(self):
        with self.assertRaises(ValidationError):
            ExtractionEnvelope(source_id="1",
                               assertions=[self._a("a", requires=["없는것"])])

    def test_unknown_field_is_rejected_not_ignored(self):
        """모델이 스키마 밖 필드를 보내면 조용히 무시되지 않고 걸린다."""
        with self.assertRaises(ValidationError):
            Assertion(local_ref="a", original_assertion="t", 지어낸필드="x")


class CardTest(unittest.TestCase):
    def test_block_needs_at_least_one_fact(self):
        """사실이 없으면 블록을 만들지 않는다. 빈 블록은 지어낼 자리다."""
        with self.assertRaises(ValidationError):
            CardBlock(block_id="b1", kind="QUANTITIES", fact_revision_ids=[])

    def test_fact_ids_collects_across_blocks(self):
        plan = CardPlan(entity_id="3001", title="카페라떼", blocks=[
            CardBlock(block_id="b1", kind="QUANTITIES", fact_revision_ids=["1", "2"]),
            CardBlock(block_id="b2", kind="STEPS", fact_revision_ids=["3"]),
        ])
        self.assertEqual(plan.fact_ids(), {"1", "2", "3"})

    def test_non_linked_disposition_requires_reason(self):
        """이유 없는 보류·제외를 남기지 않는다. 지표를 부풀리는 자리가 된다."""
        with self.assertRaises(ValidationError):
            OccurrenceDisposition(fact_revision_id="1", disposition="EXCLUDED")
        ok = OccurrenceDisposition(fact_revision_id="1", disposition="EXCLUDED",
                                   reason="업무와 무관")
        self.assertEqual(ok.disposition, "EXCLUDED")


class SnapshotTest(unittest.TestCase):
    def _snapshot(self, **kw):
        base = dict(
            store_id="5", knowledge_revision=1, snapshot_id="9001",
            snapshot_hash="abc12345", created_at=datetime.now(timezone.utc),
            glossary_version="g1", renderer_version="r1",
        )
        base.update(kw)
        return PublishedKnowledgeSnapshot(**base)

    def test_block_cannot_reference_a_fact_outside_the_snapshot(self):
        """없는 사실을 가리키면 R 이 인용할 수 없는 카드를 받는다."""
        with self.assertRaises(ValidationError):
            self._snapshot(
                cards=[PublishedCard(card_id="1", card_version_id="2", entity_id="3",
                                     title="t", blocks=[CardBlock(
                                         block_id="b", kind="RAW",
                                         fact_revision_ids=["9999"])])],
                fact_revisions=[])

    def test_required_prerequisite_must_ship_together(self):
        """선행 사실이 빠지면 위험한 절반만 전달된다."""
        with self.assertRaises(ValidationError):
            self._snapshot(fact_revisions=[
                FactRevision(fact_revision_id="1", assertion="약품을 넣는다",
                             requires=["2"])])

    def test_valid_snapshot_passes(self):
        snap = self._snapshot(
            cards=[PublishedCard(card_id="1001", card_version_id="2003",
                                 entity_id="3001", variant=Variant(temperature="ICE"),
                                 title="카페라떼", blocks=[CardBlock(
                                     block_id="b1", kind="QUANTITIES",
                                     fact_revision_ids=["4002"])])],
            fact_revisions=[FactRevision(
                fact_revision_id="4002", assertion="ICE 라떼 우유 225ml",
                quantity=Quantity(value="225", unit="ml"),
                conditions=["temperature=ICE"])])
        self.assertEqual(snap.schema_version, "published_knowledge/v1")


class AnswerPlanTest(unittest.TestCase):
    def _block(self):
        return SelectedBlock(card_id="1001", card_version_id="2003",
                             block_id="b1", fact_revision_ids=["4002"])

    def _plan(self, **kw):
        return AnswerPlan(snapshot_id="9001", knowledge_revision=1, **kw)

    def test_answer_requires_citation(self):
        """불변식 3·6 — 근거 없는 ANSWER 는 존재할 수 없다."""
        with self.assertRaises(ValidationError):
            self._plan(action="ANSWER")

    def test_answer_with_citation_passes(self):
        plan = self._plan(action="ANSWER", selected_blocks=[self._block()])
        self.assertEqual(plan.citation_count(), 1)

    def test_clarify_needs_slot_options_and_context(self):
        with self.assertRaises(ValidationError):
            self._plan(action="CLARIFY", clarification_slot="temperature")
        with self.assertRaises(ValidationError):
            self._plan(action="CLARIFY", clarification_slot="temperature",
                       allowed_options=["HOT", "ICE"])
        ok = self._plan(action="CLARIFY", clarification_slot="temperature",
                        allowed_options=["HOT", "ICE"], context_id="ctx-1")
        self.assertEqual(ok.action, "CLARIFY")

    def test_clarify_does_not_cite(self):
        """되묻는 중에는 아직 답하지 않는다."""
        with self.assertRaises(ValidationError):
            self._plan(action="CLARIFY", clarification_slot="temperature",
                       allowed_options=["HOT"], context_id="c",
                       selected_blocks=[self._block()])

    def test_escalate_needs_reason_and_does_not_cite(self):
        with self.assertRaises(ValidationError):
            self._plan(action="ESCALATE")
        with self.assertRaises(ValidationError):
            self._plan(action="ESCALATE", escalation_reason="지식 없음",
                       selected_blocks=[self._block()])

    def test_policy_actions_never_cite_store_knowledge(self):
        for action in ("REFUSE", "SAFE_ROUTE"):
            with self.assertRaises(ValidationError):
                self._plan(action=action, selected_blocks=[self._block()])
            self.assertEqual(self._plan(action=action).action, action)


if __name__ == "__main__":
    unittest.main()
