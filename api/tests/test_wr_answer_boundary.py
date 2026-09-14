"""W JSON fixture → 공통 참조 → R 적합성 → 공통 fake renderer 접점 인수."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.contracts import AnswerPlan, PublishedKnowledgeSnapshot, SelectedBlock, verify_snapshot_hash
from app.contracts.validate import validate_answer_references, AnswerPlanViolation
from app.fakes.renderer import FakeRenderer
from app.learn.answer_validation import (
    FactSuitability, SuitabilityAssessment, ResolvedSelection,
    question_hash, validate_answer_for_question,
)

ROOT = Path(__file__).parent / "fixtures/contracts/v1"


def load(name):
    return json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))


def inputs(case_id):
    snap = PublishedKnowledgeSnapshot.model_validate(load("snapshot"))
    verify_snapshot_hash(snap)
    authored = load("r_suitability")
    case = authored["cases"][case_id]
    variants = tuple(tuple(v) for v in case["variants"])
    checks = tuple(FactSuitability(fid, authored["facts"][fid]["variant_scope"],
                                  tuple(authored["facts"][fid]["conditions"]),
                                  tuple(authored["facts"][fid]["exceptions"]))
                   for fid in case["selected"])
    raw = tuple(tuple(ref) for ref in case.get("raw_blocks", []))
    assessment = SuitabilityAssessment(
        authored["store_id"], authored["snapshot_id"], authored["knowledge_revision"],
        authored["snapshot_hash"], question_hash(case["question"]), authored["entity_id"],
        case["predicate"], variants, tuple(case["targets"]), checks, raw)
    query = ResolvedSelection(authored["entity_id"], case["predicate"], variants,
                              case["question"], assessment)
    selections = []
    for card in snap.cards:
        for block in card.blocks:
            ids = tuple(fid for fid in case["selected"] if fid in block.fact_revision_ids)
            if ids:
                selections.append(SelectedBlock(card_id=card.card_id, card_version_id=card.card_version_id,
                                                block_id=block.block_id, fact_revision_ids=ids))
    selections.extend(SelectedBlock(card_id=c, card_version_id=v, block_id=b, raw_span_id=r)
                      for c, v, b, r in raw)
    plan = AnswerPlan(snapshot_id=snap.snapshot_id, knowledge_revision=snap.knowledge_revision,
                      action="ANSWER", selected_blocks=tuple(selections))
    return snap, plan, query


class SharedFixtureBoundaryTest(unittest.TestCase):
    def test_F02_through_F09_preserve_preexisting_expected_outputs(self):
        manifest = {c["id"]: c for c in load("manifest")["cases"]}
        for cid in ("F02", "F03", "F04", "F05", "F06", "F07", "F08", "F09"):
            with self.subTest(case=cid):
                snap, plan, query = inputs(cid)
                expected = manifest[cid]
                self.assertEqual(query.question, expected["question"])
                checked = validate_answer_for_question(plan, snap, query, store_id=1)
                response = FakeRenderer().render(checked, snap, store_id="1", request_id="synthetic")
                self.assertEqual(response.action, expected["action"])
                cited = {c.fact_revision_id for c in response.citations if c.fact_revision_id}
                self.assertEqual(cited, set(expected.get("must_cite", [])))
                self.assertTrue(cited.isdisjoint(expected.get("must_not_cite", [])))
                self.assertEqual({c.raw_span_id for c in response.citations if c.raw_span_id},
                                 set(expected.get("must_cite_raw", [])))
                for term in expected.get("must_contain", []):
                    self.assertIn(term, response.message)
                if cid == "F05":
                    self.assertIn("않는다", response.message)
                if cid == "F07":
                    self.assertEqual([c.fact_revision_id for c in response.citations], expected["ordered"])
                if cid == "F09":
                    self.assertEqual(response.message, snap.raw_spans[0].text)

    def test_comparison_requires_both_variants_and_no_extra_size(self):
        snap, plan, query = inputs("COMPARE")
        response = FakeRenderer().render(validate_answer_for_question(plan, snap, query, store_id=1),
                                         snap, store_id="1", request_id="compare")
        self.assertIn("225", response.message)
        self.assertIn("275", response.message)
        for ids in (("900",), ("900", "901", "902")):
            altered = plan.model_copy(update={"selected_blocks": (plan.selected_blocks[0].model_copy(
                update={"fact_revision_ids": ids}),)})
            with self.assertRaises(ValueError):
                validate_answer_for_question(altered, snap, query, store_id=1)

    def test_unknown_and_confirmed_not_applicable_are_different(self):
        snap, plan, query = inputs("F05")
        with self.assertRaises(ValueError):
            validate_answer_for_question(plan, snap, replace(query, assessment=None), store_id=1)
        bad = replace(query.assessment, facts=(replace(query.assessment.facts[0], variant_scope="SPECIFIC"),))
        with self.assertRaises(ValueError):
            validate_answer_for_question(plan, snap, replace(query, assessment=bad), store_id=1)

    def test_raw_approval_alone_is_not_question_suitability(self):
        snap, plan, query = inputs("F09")
        validate_answer_references(plan, snap, store_id="1")
        with self.assertRaisesRegex(ValueError, "UNRESOLVED_CONTEXT"):
            validate_answer_for_question(plan, snap, replace(query, assessment=None), store_id=1)

    def test_assessment_cannot_be_reused_for_other_question_scope_or_snapshot(self):
        snap, plan, query = inputs("F04")
        for change in (dict(question_hash=question_hash("다른 질문")), dict(store_id="2"),
                       dict(snapshot_id="101"), dict(knowledge_revision="6"),
                       dict(snapshot_hash="sha256:" + "0" * 64), dict(predicate="other"),
                       dict(entity_id="301"), dict(variants=(("HOT", None),))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_answer_for_question(plan, snap, replace(query, assessment=replace(query.assessment, **change)), store_id=1)

    def test_missing_condition_exception_or_fact_judgment_rejected(self):
        for cid, field in (("F04", "conditions"), ("F06", "exceptions")):
            snap, plan, query = inputs(cid)
            for checks in ((), (replace(query.assessment.facts[0], **{field: ()}),)):
                with self.subTest(case=cid, checks=checks), self.assertRaises(ValueError):
                    validate_answer_for_question(plan, snap, replace(query, assessment=replace(query.assessment, facts=checks)), store_id=1)

    def test_common_validator_is_the_single_reference_entry(self):
        snap, plan, query = inputs("F02")
        with patch("app.learn.answer_validation.references.validate_answer_references", wraps=validate_answer_references) as gate:
            validate_answer_for_question(plan, snap, query, store_id=1)
        gate.assert_called_once()

    def test_missing_or_reversed_steps_fail_before_rendering(self):
        snap, plan, query = inputs("F08")
        for ids in (("906",), ("906", "905")):
            altered = plan.model_copy(update={"selected_blocks": (plan.selected_blocks[0].model_copy(update={"fact_revision_ids": ids}),)})
            with self.assertRaises(ValueError):
                validate_answer_for_question(altered, snap, query, store_id=1)

    def test_common_blocks_cross_entity_and_ambiguous_raw(self):
        snap, plan, _ = inputs("F02")
        raw = snap.model_dump(mode="json")
        raw["fact_revisions"][0]["entity_id"] = "999"
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_references(plan, PublishedKnowledgeSnapshot.model_validate(raw), store_id="1")
        snap, plan, _ = inputs("F09")
        raw = snap.model_dump(mode="json")
        raw["cards"][0]["blocks"][3]["fact_revision_ids"] = ["900"]
        with self.assertRaises(AnswerPlanViolation):
            validate_answer_references(plan, PublishedKnowledgeSnapshot.model_validate(raw), store_id="1")

    def test_hash_tampering_and_stale_plan_are_errors(self):
        snap, plan, query = inputs("F04")
        data = snap.model_dump(mode="json")
        data["fact_revisions"][0]["assertion"] = "변조된 내용"
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            validate_answer_for_question(plan, PublishedKnowledgeSnapshot.model_validate(data), query, store_id=1)
        with self.assertRaisesRegex(ValueError, "STALE_KNOWLEDGE"):
            validate_answer_for_question(plan.model_copy(update={"knowledge_revision": "6"}), snap, query, store_id=1)

    def test_other_actions_do_not_require_answer_evidence_or_write_pending(self):
        snap, _, query = inputs("F02")
        for action, kw in (("CLARIFY", dict(clarification_slot="temperature", allowed_options=("HOT", "ICE"),
                                            context_id="00000000-0000-4000-8000-000000000001")),
                           ("ESCALATE", dict(escalation_reason="NO_EVIDENCE")),
                           ("REFUSE", {}), ("SAFE_ROUTE", {})):
            with self.subTest(action=action):
                plan = AnswerPlan(snapshot_id=snap.snapshot_id, knowledge_revision=snap.knowledge_revision,
                                  action=action, **kw)
                checked = validate_answer_for_question(plan, snap, replace(query, assessment=None), store_id=1)
                self.assertEqual(checked.action, action)
                self.assertFalse(checked.selected_blocks)
