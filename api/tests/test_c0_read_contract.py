"""CP-01 R의 정상/거절 경계. 합성 데이터만 사용한다."""
import unittest
import json
from pathlib import Path
from datetime import datetime, timezone

from pydantic import ValidationError

from app.contracts.answer import AnswerPlan, SelectedBlock
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.learn.answer_validation import ResolvedSelection, validate_answer_plan


def snapshot():
    return PublishedKnowledgeSnapshot(
        store_id="1", snapshot_id="2", knowledge_revision=1,
        snapshot_hash="legacy-test", created_at=datetime.now(timezone.utc),
        glossary_version="g1", renderer_version="r1",
        cards=[dict(card_id="3", card_version_id="4", entity_id="5", title="합성 음료",
                    blocks=[dict(block_id="b1", kind="QUANTITIES", fact_revision_ids=["6"])])],
        fact_revisions=[dict(fact_revision_id="6", assertion="HOT 우유 200ml",
                             predicate="milk", variant=dict(temperature="HOT"),
                             quantity=dict(value="200", unit="ml"))],
    )


def answer(**changes):
    data = dict(snapshot_id="2", knowledge_revision="1", action="ANSWER", selected_blocks=[
        dict(card_id="3", card_version_id="4", block_id="b1", fact_revision_ids=["6"])
    ])
    data.update(changes)
    return AnswerPlan(**data)


QUERY = ResolvedSelection("5", "milk", (("HOT", None),))


class ShapeTest(unittest.TestCase):
    def test_exported_schema_and_fixtures(self):
        target = Path(__file__).parent / "fixtures/contracts/v1/r_answer"
        schema = json.loads((target / "answer_plan.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema, AnswerPlan.model_json_schema())
        fixtures = json.loads((target / "answer_plan.fixtures.json").read_text(encoding="utf-8"))
        for data in fixtures["accepted"]:
            plan = AnswerPlan.model_validate(data)
            self.assertEqual(plan, AnswerPlan.model_validate_json(plan.model_dump_json()))
        for data in fixtures["rejected"]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                AnswerPlan.model_validate(data)

    def test_all_action_exclusive_fields(self):
        for action in ("ANSWER", "ESCALATE", "REFUSE", "SAFE_ROUTE"):
            base = dict(action=action, selected_blocks=[])
            if action == "ANSWER":
                base["selected_blocks"] = answer().selected_blocks
            if action == "ESCALATE":
                base["escalation_reason"] = "없음"
            for field, value in (("clarification_slot", "temperature"), ("allowed_options", ["HOT"]),
                                 ("context_id", "00000000-0000-4000-8000-000000000001")):
                with self.subTest(action=action, field=field), self.assertRaises(ValidationError):
                    answer(**base, **{field: value})
        for action in ("ANSWER", "REFUSE", "SAFE_ROUTE"):
            with self.assertRaises(ValidationError):
                answer(action=action, escalation_reason="")

    def test_invalid_ids_and_revisions(self):
        for bad in ("0", "01", "-1", "9223372036854775808", 1, True, "1\n"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                answer(snapshot_id=bad)
        for bad in (1, True, "01", "-1", "9223372036854775808"):
            with self.assertRaises(ValidationError):
                answer(knowledge_revision=bad)
        self.assertEqual(answer(knowledge_revision="0").knowledge_revision, "0")

    def test_duplicate_references_and_immutability(self):
        block = answer().selected_blocks[0]
        with self.assertRaises(ValidationError):
            answer(selected_blocks=[block, block])
        with self.assertRaises(ValidationError):
            SelectedBlock(**{**block.model_dump(), "fact_revision_ids": ["6", "6"]})
        with self.assertRaises(ValidationError):
            block.card_id = "99"
        self.assertIsInstance(block.fact_revision_ids, tuple)
        self.assertEqual(answer().citation_count(), 1)

    def test_json_round_trip(self):
        plan = answer()
        self.assertEqual(AnswerPlan.model_validate_json(plan.model_dump_json()), plan)
        self.assertEqual(AnswerPlan.model_json_schema()["properties"]["knowledge_revision"]["type"], "string")


class ConsumerTest(unittest.TestCase):
    def test_approved_selection(self):
        self.assertEqual(validate_answer_plan(answer(), snapshot(), QUERY, store_id=1), answer())

    def test_cross_store_stale_and_invented_reference(self):
        for plan, sid in ((answer(), 2), (answer(snapshot_id="99"), 1),
                          (answer(knowledge_revision="2"), 1)):
            with self.assertRaises(ValueError):
                validate_answer_plan(plan, snapshot(), QUERY, store_id=sid)
        for field, value in (("card_id", "99"), ("card_version_id", "99"),
                             ("block_id", "other"), ("fact_revision_ids", ["99"])):
            data = answer().selected_blocks[0].model_dump()
            data[field] = value
            with self.assertRaises(ValueError):
                validate_answer_plan(answer(selected_blocks=[data]), snapshot(), QUERY, store_id=1)

    def test_wrong_entity_predicate_variant(self):
        for query in (ResolvedSelection("99", "milk", (("HOT", None),)),
                      ResolvedSelection("5", "water", (("HOT", None),)),
                      ResolvedSelection("5", "milk", (("ICE", None),)),
                      ResolvedSelection("5", "milk", ())):
            with self.assertRaises(ValueError):
                validate_answer_plan(answer(), snapshot(), query, store_id=1)

    def test_legacy_raw_is_not_automatically_answerable(self):
        snap = snapshot()
        snap.cards[0].blocks[0].kind = "RAW"
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_SCHEMA"):
            validate_answer_plan(answer(), snap, QUERY, store_id=1)

    def test_duplicate_snapshot_and_cycle(self):
        for mutation in (lambda s: s.cards.append(s.cards[0]),
                         lambda s: s.fact_revisions.append(s.fact_revisions[0]),
                         lambda s: s.cards[0].blocks.append(s.cards[0].blocks[0]),
                         lambda s: s.fact_revisions[0].requires.append("6")):
            snap = snapshot()
            mutation(snap)
            with self.assertRaises(ValueError):
                validate_answer_plan(answer(), snap, QUERY, store_id=1)

    def test_partial_block_or_missing_dependency_rejected(self):
        snap = snapshot()
        extra = snap.fact_revisions[0].model_copy(update={"fact_revision_id": "7", "requires": ["6"]})
        snap.fact_revisions.append(extra)
        snap.cards[0].blocks[0].fact_revision_ids.append("7")
        with self.assertRaises(ValueError):
            validate_answer_plan(answer(), snap, QUERY, store_id=1)
        selected = answer().selected_blocks[0].model_dump()
        selected["fact_revision_ids"] = ["6", "7"]
        validate_answer_plan(answer(selected_blocks=[selected]), snap, QUERY, store_id=1)
        snap.cards[0].blocks[0].fact_revision_ids.reverse()
        selected["fact_revision_ids"] = ["7", "6"]
        with self.assertRaises(ValueError):
            validate_answer_plan(answer(selected_blocks=[selected]), snap, QUERY, store_id=1)

    def test_unknown_unit_rejected(self):
        snap = snapshot()
        snap.fact_revisions[0].quantity.unit = None
        with self.assertRaises(ValueError):
            validate_answer_plan(answer(), snap, QUERY, store_id=1)

    def test_hot_ice_comparison_requires_both_confirmed_variants(self):
        snap = snapshot()
        data = snap.fact_revisions[0].model_dump()
        data.update(fact_revision_id="7", variant={"temperature": "ICE"}, assertion="ICE 우유 150ml")
        data["quantity"] = {"value": "150", "unit": "ml"}
        snap.fact_revisions.append(type(snap.fact_revisions[0])(**data))
        block = snap.cards[0].blocks[0].model_copy(update={"block_id": "b2", "fact_revision_ids": ["7"]})
        snap.cards[0].blocks.append(block)
        plan = answer(selected_blocks=[*answer().selected_blocks,
            dict(card_id="3", card_version_id="4", block_id="b2", fact_revision_ids=["7"])])
        compare = ResolvedSelection("5", "milk", (("HOT", None), ("ICE", None)))
        validate_answer_plan(plan, snap, compare, store_id=1)
        for candidate, query in ((answer(), compare), (plan, QUERY)):
            with self.assertRaises(ValueError):
                validate_answer_plan(candidate, snap, query, store_id=1)
