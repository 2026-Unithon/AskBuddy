"""C0 공통 계약 테스트 — W 생산자와 R 소비자가 같은 계약을 쓰는지 고정한다.

계약이 깨지면 여기서 걸려야 한다. 런타임까지 가면 그 실행이 통째로 못 쓰게 된다.

CP-01 에서 추가한 검사들은 전부 **검토에서 실제로 뚫린 구멍**이다 (RV-01~10).
모양만 통과하고 의미가 어긋나는 입력이 어디까지 들어왔는지 여기에 남긴다.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.contracts import (
    Assertion,
    AnswerPlan,
    AnswerPlanViolation,
    CardBlock,
    CardPlan,
    EvidenceLocator,
    ExtractionEnvelope,
    FactProvenance,
    FactRevision,
    OccurrenceDisposition,
    PublishedCard,
    PublishedKnowledgeSnapshot,
    Quantity,
    SelectedBlock,
    Variant,
    as_id,
    validate_answer_plan,
)

HASH = "sha256:" + "a" * 64


def prov(occurrence_id="7001", source_id="8001"):
    return FactProvenance(occurrence_id=occurrence_id, source_id=source_id)


def fact(fact_revision_id="4002", *, assertion="ICE 라떼 우유 225ml", **kw):
    base = dict(fact_revision_id=fact_revision_id, fact_id="400",
                entity_id="3001", original_assertion=assertion,
                assertion=assertion, provenance=(prov(),))
    base.update(kw)
    return FactRevision(**base)


def block(block_id="b1", kind="QUANTITIES", order=1, **kw):
    kw.setdefault("fact_revision_ids", ("4002",))
    return CardBlock(block_id=block_id, kind=kind, order=order, **kw)


def card(**kw):
    base = dict(card_id="1001", card_version_id="2003", entity_id="3001",
                title="카페라떼", blocks=(block(),))
    base.update(kw)
    return PublishedCard(**base)


def snapshot(**kw):
    base = dict(store_id="5", knowledge_revision="1", snapshot_id="9001",
                snapshot_hash=HASH, created_at=datetime.now(timezone.utc),
                glossary_version="g1", renderer_version="r1",
                cards=(card(),), fact_revisions=(fact(),))
    base.update(kw)
    return PublishedKnowledgeSnapshot(**base)


class IdTest(unittest.TestCase):
    def test_bigint_becomes_decimal_string(self):
        """JS Number 는 2^53 을 넘으면 정밀도를 잃는다. 경계에서 문자열로 넘긴다."""
        self.assertEqual(as_id(9007199254740993), "9007199254740993")

    def test_non_numeric_id_rejected(self):
        with self.assertRaises(ValueError):
            as_id("abc")

    def test_leading_zero_id_rejected(self):
        """RV-09 — "012" 와 "12" 를 둘 다 받으면 같은 행의 두 표기가 생긴다.

        계약 전체가 set 으로 존재·중복을 검사하므로, 표기가 둘이면 중복 검사가
        조용히 뚫린다.
        """
        with self.assertRaises(ValueError):
            as_id("012")

    def test_id_beyond_bigint_rejected(self):
        with self.assertRaises(ValidationError):
            fact("9" * 19)


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

    def _env(self, **kw):
        base = dict(source_id="1", result_status="OK", assertions=[self._a()])
        base.update(kw)
        return ExtractionEnvelope(**base)

    def test_timestamp_locator_requires_a_timestamp(self):
        with self.assertRaises(ValidationError):
            EvidenceLocator(type="TIMESTAMP")

    def test_quantity_and_text_value_are_exclusive(self):
        with self.assertRaises(ValidationError):
            self._a(quantity=Quantity(value="225", unit="ml"), value_text="가득")

    def test_duplicate_local_ref_rejected(self):
        with self.assertRaises(ValidationError):
            self._env(assertions=[self._a("a"), self._a("a")])

    def test_requires_must_point_inside_the_segment(self):
        with self.assertRaises(ValidationError):
            self._env(assertions=[self._a("a", requires=["없는것"])])

    def test_requires_cycle_rejected(self):
        """RV-02 — 서로가 서로를 요구하면 무엇을 먼저 할지 정할 수 없다."""
        with self.assertRaises(ValidationError):
            self._env(assertions=[self._a("a", requires=["b"]),
                                  self._a("b", requires=["a"])])

    def test_self_requirement_rejected(self):
        with self.assertRaises(ValidationError):
            self._a("a", requires=["a"])

    def test_unknown_field_is_rejected_not_ignored(self):
        """모델이 스키마 밖 필드를 보내면 조용히 무시되지 않고 걸린다."""
        with self.assertRaises(ValidationError):
            Assertion(local_ref="a", original_assertion="t", 지어낸필드="x")

    def test_original_text_keeps_its_whitespace(self):
        """RV-07 — 원문의 들여쓰기·줄바꿈을 계약이 손대면 '원문이 권위' 가 깨진다."""
        a = self._a("a")
        self.assertEqual(
            Assertion(local_ref="b",
                      original_assertion="  1) 전원을 끈다\n  2) 약품을 넣는다\n"
                      ).original_assertion,
            "  1) 전원을 끈다\n  2) 약품을 넣는다\n")
        self.assertEqual(a.local_ref, "a")

    def test_non_numeric_source_id_rejected(self):
        """RV-10 — source_id 는 서버가 요청에 묶는 DB ID 다. 모델의 값을 믿지 않는다."""
        with self.assertRaises(ValidationError):
            self._env(source_id="src-1")

    def test_empty_result_must_say_why(self):
        """RV-10 — `assertions: []` 하나로 '내용이 없었다' 와 '깨졌다' 를 구분할 수 없다.

        구분하지 않으면 실패한 호출이 추출 성능으로 집계된다.
        """
        with self.assertRaises(ValidationError):
            self._env(result_status="OK", assertions=[])
        with self.assertRaises(ValidationError):
            self._env(result_status="NO_RESULT", assertions=[], unresolved=[])
        ok = self._env(result_status="NO_RESULT", assertions=[],
                       unresolved=["영상에 업무 내용이 없었다"])
        self.assertEqual(ok.result_status, "NO_RESULT")

    def test_failed_envelope_carries_error_and_no_facts(self):
        with self.assertRaises(ValidationError):
            self._env(result_status="FAILED", assertions=[],
                      raw_response_ref="r1")           # 오류 없음
        with self.assertRaises(ValidationError):
            self._env(result_status="FAILED", error="timeout")  # 원문 없음
        ok = self._env(result_status="FAILED", assertions=[],
                       error="timeout", raw_response_ref="r1")
        self.assertEqual(ok.result_status, "FAILED")

    def test_truncated_result_is_not_ok_and_keeps_raw(self):
        """잘린 결과를 온전한 결과로 세면 추출 손실이 실제보다 작아 보인다."""
        with self.assertRaises(ValidationError):
            self._env(truncated=True, raw_response_ref="r1")
        with self.assertRaises(ValidationError):
            self._env(result_status="PARTIAL", truncated=True)
        ok = self._env(result_status="PARTIAL", truncated=True,
                       raw_response_ref="r1")
        self.assertTrue(ok.truncated)


class CardTest(unittest.TestCase):
    def test_typed_block_needs_at_least_one_fact(self):
        """사실이 없으면 블록을 만들지 않는다. 빈 블록은 지어낼 자리다."""
        with self.assertRaises(ValidationError):
            CardBlock(block_id="b1", kind="QUANTITIES", order=1,
                      fact_revision_ids=())

    def test_raw_block_may_cite_an_approved_span_instead(self):
        """RV-05 — 승인된 원문 카드를 표현하려고 사실을 억지로 만들지 않는다."""
        b = CardBlock(block_id="b1", kind="RAW", order=1, raw_span_id="6001")
        self.assertEqual(b.raw_span_id, "6001")
        with self.assertRaises(ValidationError):
            CardBlock(block_id="b1", kind="RAW", order=1)
        with self.assertRaises(ValidationError):
            CardBlock(block_id="b1", kind="STEPS", order=1,
                      fact_revision_ids=("1",), raw_span_id="6001")

    def test_block_order_is_explicit_and_unique(self):
        """RV-06 — 리스트 순서에만 기대면 DB 왕복에서 절차가 뒤집힌다."""
        with self.assertRaises(ValidationError):
            CardPlan(entity_id="3001", title="t", blocks=[
                block("b1", order=1), block("b2", order=1)])

    def test_fact_ids_collects_across_blocks(self):
        plan = CardPlan(entity_id="3001", title="카페라떼", blocks=[
            block("b1", "QUANTITIES", 1, fact_revision_ids=("1", "2")),
            block("b2", "STEPS", 2, fact_revision_ids=("3",)),
        ])
        self.assertEqual(plan.fact_ids(), {"1", "2", "3"})

    def test_approved_block_cannot_be_mutated_after_parsing(self):
        """RV-07 — 파싱 뒤 인용 목록을 늘릴 수 있으면 '승인된 것만 인용' 이 약속에 그친다."""
        b = block()
        with self.assertRaises(ValidationError):
            b.block_id = "다른블록"
        with self.assertRaises(AttributeError):
            b.fact_revision_ids.append("9999")

    def test_non_linked_disposition_requires_reason(self):
        """이유 없는 보류·제외를 남기지 않는다. 지표를 부풀리는 자리가 된다."""
        with self.assertRaises(ValidationError):
            OccurrenceDisposition(occurrence_id="7001", disposition="EXCLUDED")
        ok = OccurrenceDisposition(occurrence_id="7001", disposition="EXCLUDED",
                                   reason="업무와 무관")
        self.assertEqual(ok.disposition, "EXCLUDED")

    def test_disposition_is_keyed_by_occurrence(self):
        """RV-08 — 같은 사실이 자료 세 곳에 나오면 판정도 세 건이다.

        사실 단위로만 기록하면 "3번 나왔고 2번은 제외했다" 가 한 줄로 뭉개진다.
        """
        one = OccurrenceDisposition(occurrence_id="7001", fact_revision_id="4002",
                                    disposition="LINKED", card_id="1001",
                                    block_id="b1")
        two = OccurrenceDisposition(occurrence_id="7002", fact_revision_id="4002",
                                    disposition="EXCLUDED", reason="중복")
        self.assertNotEqual(one.occurrence_id, two.occurrence_id)
        self.assertEqual(one.fact_revision_id, two.fact_revision_id)

    def test_linked_must_say_where_it_landed(self):
        with self.assertRaises(ValidationError):
            OccurrenceDisposition(occurrence_id="7001", fact_revision_id="4002",
                                  disposition="LINKED")


class SnapshotTest(unittest.TestCase):
    def test_block_cannot_reference_a_fact_outside_the_snapshot(self):
        """없는 사실을 가리키면 R 이 인용할 수 없는 카드를 받는다."""
        with self.assertRaises(ValidationError):
            snapshot(cards=(card(blocks=(block(fact_revision_ids=("9999",)),)),),
                     fact_revisions=())

    def test_required_prerequisite_must_ship_together(self):
        """선행 사실이 빠지면 위험한 절반만 전달된다."""
        with self.assertRaises(ValidationError):
            snapshot(fact_revisions=(fact(requires=("9999",)),))

    def test_prerequisite_cycle_rejected(self):
        """RV-02 — 순환하면 렌더러가 순서를 정하지 못한다."""
        with self.assertRaises(ValidationError):
            snapshot(
                cards=(card(blocks=(block(fact_revision_ids=("4002", "4003")),)),),
                fact_revisions=(fact("4002", requires=("4003",)),
                                fact("4003", requires=("4002",))))

    def test_duplicate_fact_revision_id_rejected(self):
        """RV-01 — 존재만 보면 같은 ID 의 서로 다른 사실이 둘 다 실린다.

        어느 쪽이 인용되는지가 목록 순서에 달리게 된다.
        """
        with self.assertRaises(ValidationError):
            snapshot(fact_revisions=(fact("4002", assertion="225ml"),
                                     fact("4002", assertion="275ml")))

    def test_duplicate_card_rejected(self):
        with self.assertRaises(ValidationError):
            snapshot(cards=(card(), card(card_version_id="2004")))

    def test_orphan_fact_rejected(self):
        """RV-01 — 어느 블록도 닿지 못하는 사실은 인용될 길이 없다.

        검수를 거치지 않은 내용이 공개 묶음에만 남는 통로가 된다.
        """
        with self.assertRaises(ValidationError):
            snapshot(fact_revisions=(fact("4002"), fact("4003")))

    def test_prerequisite_reached_through_requires_is_not_orphan(self):
        snap = snapshot(fact_revisions=(fact("4002", requires=("4003",)),
                                        fact("4003", assertion="먼저 전원을 끈다")))
        self.assertEqual(len(snap.fact_revisions), 2)

    def test_hash_must_be_sha256_hex(self):
        """RV-09 — 길이만 보면 임의 문자열이 통과한다."""
        with self.assertRaises(ValidationError):
            snapshot(snapshot_hash="abc12345")

    def test_hash_carries_its_algorithm(self):
        """알고리즘을 값에 담아 두면 나중에 바꿀 때 옛 hash 와 섞이지 않는다."""
        with self.assertRaises(ValidationError):
            snapshot(snapshot_hash="a" * 64)

    def test_naive_datetime_rejected(self):
        """RV-09 — 시각대 없는 승인 시각은 9시간 밀려 판 순서를 뒤집는다."""
        with self.assertRaises(ValidationError):
            snapshot(created_at=datetime(2026, 9, 14, 12, 0))

    def test_published_fact_must_have_provenance(self):
        """RV-06 — 출처 없는 사실은 '승인된 매장 지식' 임을 검사할 수 없다."""
        with self.assertRaises(ValidationError):
            fact(provenance=())

    def test_snapshot_is_immutable_after_parsing(self):
        snap = snapshot()
        with self.assertRaises(ValidationError):
            snap.knowledge_revision = "2"
        with self.assertRaises(AttributeError):
            snap.cards.append(card(card_id="1002"))

    def test_valid_snapshot_passes(self):
        snap = snapshot(cards=(card(variant=Variant(temperature="ICE")),),
                        fact_revisions=(fact(quantity=Quantity(value="225", unit="ml"),
                                             conditions=("temperature=ICE",)),))
        self.assertEqual(snap.schema_version, "published_knowledge/v1")


class AnswerPlanTest(unittest.TestCase):
    def _block(self, **kw):
        base = dict(card_id="1001", card_version_id="2003", block_id="b1",
                    fact_revision_ids=("4002",))
        base.update(kw)
        return SelectedBlock(**base)

    def _plan(self, **kw):
        return AnswerPlan(snapshot_id="9001", knowledge_revision="1", **kw)

    def test_answer_requires_citation(self):
        """불변식 3·6 — 근거 없는 ANSWER 는 존재할 수 없다."""
        with self.assertRaises(ValidationError):
            self._plan(action="ANSWER")

    def test_answer_with_citation_passes(self):
        plan = self._plan(action="ANSWER", selected_blocks=(self._block(),))
        self.assertEqual(plan.citation_count(), 1)

    def test_clarify_needs_slot_options_and_context(self):
        with self.assertRaises(ValidationError):
            self._plan(action="CLARIFY", clarification_slot="temperature")
        with self.assertRaises(ValidationError):
            self._plan(action="CLARIFY", clarification_slot="temperature",
                       allowed_options=("HOT", "ICE"))
        ok = self._plan(action="CLARIFY", clarification_slot="temperature",
                        allowed_options=("HOT", "ICE"), context_id="00000000-0000-4000-8000-000000000001")
        self.assertEqual(ok.action, "CLARIFY")

    def test_clarify_does_not_cite(self):
        """되묻는 중에는 아직 답하지 않는다."""
        with self.assertRaises(ValidationError):
            self._plan(action="CLARIFY", clarification_slot="temperature",
                       allowed_options=("HOT",), context_id="00000000-0000-4000-8000-000000000001",
                       selected_blocks=(self._block(),))

    def test_escalate_needs_reason_and_does_not_cite(self):
        with self.assertRaises(ValidationError):
            self._plan(action="ESCALATE")
        with self.assertRaises(ValidationError):
            self._plan(action="ESCALATE", escalation_reason="지식 없음",
                       selected_blocks=(self._block(),))

    def test_escalate_cannot_carry_clarify_fields(self):
        """RV-03 — 섞이면 점주에게 알림이 가면서 신입은 값을 고르고 있다."""
        with self.assertRaises(ValidationError):
            self._plan(action="ESCALATE", escalation_reason="지식 없음",
                       clarification_slot="temperature",
                       allowed_options=("HOT",), context_id="00000000-0000-4000-8000-000000000001")

    def test_answer_cannot_carry_context_id(self):
        with self.assertRaises(ValidationError):
            self._plan(action="ANSWER", selected_blocks=(self._block(),),
                       context_id="00000000-0000-4000-8000-000000000001")

    def test_policy_actions_never_cite_store_knowledge(self):
        for action in ("REFUSE", "SAFE_ROUTE"):
            with self.assertRaises(ValidationError):
                self._plan(action=action, selected_blocks=(self._block(),))
            self.assertEqual(self._plan(action=action).action, action)


class AnswerPlanAgainstSnapshotTest(unittest.TestCase):
    """RV-04 — 모양이 통과했다는 것은 권한이 있다는 뜻이 아니다.

    임의의 snapshot_id·card_id 를 넣어도 pydantic 은 통과시킨다. 서버가 쥔
    snapshot 과 JWT 매장에 대조해야 비로소 "이 매장의 승인 카드" 가 된다.
    """

    def _plan(self, **kw):
        base = dict(snapshot_id="9001", knowledge_revision="1", action="ANSWER",
                    selected_blocks=(SelectedBlock(
                        card_id="1001", card_version_id="2003", block_id="b1",
                        fact_revision_ids=("4002",)),))
        base.update(kw)
        return AnswerPlan(**base)

    def test_valid_plan_passes(self):
        validate_answer_plan(self._plan(), snapshot(), store_id="5")

    def test_other_store_snapshot_rejected(self):
        """불변식 4 — 매장 격리는 API 코드가 전부 책임진다."""
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(self._plan(), snapshot(), store_id="6")

    def test_unknown_card_rejected(self):
        plan = self._plan(selected_blocks=(SelectedBlock(
            card_id="9999", card_version_id="2003", block_id="b1",
            fact_revision_ids=("4002",)),))
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(plan, snapshot(), store_id="5")

    def test_stale_card_version_rejected(self):
        """버전이 다르면 답변 시점과 인용 시점의 지식이 달라 재현이 깨진다."""
        plan = self._plan(selected_blocks=(SelectedBlock(
            card_id="1001", card_version_id="2004", block_id="b1",
            fact_revision_ids=("4002",)),))
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(plan, snapshot(), store_id="5")

    def test_stale_knowledge_revision_rejected(self):
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(self._plan(knowledge_revision="2"),
                                 snapshot(), store_id="5")

    def test_fact_outside_the_block_rejected(self):
        """블록 밖 사실을 끌어오면 검수된 조합이 아닌 것을 보여주게 된다.

        4003 은 같은 카드의 다른 블록에 있다. snapshot 에 실려 있으므로 존재
        검사만으로는 통과하지만, 검수는 블록 단위로 이뤄졌다.
        """
        snap = snapshot(
            cards=(card(blocks=(block("b1", fact_revision_ids=("4002",)),
                                block("b2", "NOTES", 2,
                                      fact_revision_ids=("4003",)))),),
            fact_revisions=(fact("4002"), fact("4003", assertion="주의 사항")))
        plan = self._plan(selected_blocks=(SelectedBlock(
            card_id="1001", card_version_id="2003", block_id="b1",
            fact_revision_ids=("4003",)),))
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(plan, snap, store_id="5")

    def test_unknown_block_rejected(self):
        plan = self._plan(selected_blocks=(SelectedBlock(
            card_id="1001", card_version_id="2003", block_id="없는블록",
            fact_revision_ids=("4002",)),))
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(plan, snapshot(), store_id="5")

    def test_prerequisite_must_be_cited_too(self):
        """RV-02 — snapshot 에 실려 있어도 인용하지 않으면 신입에게 보이지 않는다.

        "약품을 넣는다" 만 인용하고 "먼저 전원을 끈다" 를 빼면 위험한 절반만 간다.
        """
        snap = snapshot(
            cards=(card(blocks=(block(fact_revision_ids=("4002", "4003")),)),),
            fact_revisions=(fact("4002", requires=("4003",)),
                            fact("4003", assertion="먼저 전원을 끈다")))
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_plan(self._plan(), snap, store_id="5")
        ok = self._plan(selected_blocks=(SelectedBlock(
            card_id="1001", card_version_id="2003", block_id="b1",
            fact_revision_ids=("4002", "4003")),))
        validate_answer_plan(ok, snap, store_id="5")


if __name__ == "__main__":
    unittest.main()
