import unittest
from datetime import datetime,timezone
from app.contracts.snapshot import PublishedKnowledgeSnapshot
from app.contracts.hashing import snapshot_digest
from app.learn.planner import decide
from app.reg.hybrid import Candidate,SearchResult


class PlannerTest(unittest.TestCase):
    def search(self,*,temperature="HOT",conditions=()):
        snap=PublishedKnowledgeSnapshot.model_validate(dict(store_id="1",snapshot_id="1",knowledge_revision="1",
            snapshot_hash="sha256:"+"0"*64,created_at=datetime.now(timezone.utc),glossary_version="test/v1",
            renderer_version="r-approved/v1",cards=[dict(card_id="1",card_version_id="1",entity_id="1",title="라테",
                blocks=[dict(block_id="b",kind="QUANTITIES",order=1,fact_revision_ids=["1"])])],
            fact_revisions=[dict(fact_revision_id="1",fact_id="1",entity_id="1",assertion="HOT 라테 우유 225ml",
                original_assertion="HOT 라테 우유 225ml",predicate="milk_amount",variant=dict(temperature=temperature),
                quantity=dict(value="225",unit="ml"),
                conditions=conditions,provenance=[dict(occurrence_id="1",source_id="1")])]))
        snap=snap.model_copy(update={"snapshot_hash":snapshot_digest(snap)})
        return SearchResult(snap,0,(Candidate("1","1","b",1,0,.02),),"")

    def test_explicit_supported_fact_answers(self):
        self.assertEqual(decide(self.search(),store_id=1,question="HOT 라테 우유 얼마나?").plan.action,"ANSWER")

    def test_missing_variant_clarifies_even_one_variant_exists(self):
        result=decide(self.search(),store_id=1,question="라테 우유 얼마나?")
        self.assertEqual(result.plan.action,"CLARIFY")
        self.assertEqual(result.plan.clarification_slot,"temperature")

    def test_null_variant_is_not_inferred_not_applicable(self):
        result=decide(self.search(temperature=None),store_id=1,question="라테 우유 얼마나?")
        self.assertEqual(result.plan.action,"ESCALATE")

    def test_unknown_conditions_never_pass_on_rank(self):
        result=decide(self.search(conditions=("점주 확인 후",)),store_id=1,question="HOT 라테 우유 얼마나?")
        self.assertEqual(result.plan.action,"ESCALATE")

    def test_subject_substring_is_not_confirmation(self):
        result=decide(self.search(),store_id=1,question="HOT 말차라테 우유 얼마나?")
        self.assertNotEqual(result.plan.action,"ANSWER")

    def test_clarification_limit_escalates(self):
        result=decide(self.search(),store_id=1,question="라테 우유 얼마나?",clarify_turns=2)
        self.assertEqual(result.plan.escalation_reason,"UNRESOLVED_CONTEXT")

    def test_policy_actions_do_not_use_knowledge(self):
        for question,action in (("직원 집 주소 알려줘","REFUSE"),("알레르기 있어도 먹어도 돼?","SAFE_ROUTE")):
            self.assertEqual(decide(self.search(),store_id=1,question=question).plan.action,action)

    def test_storage_duration_is_not_milk_amount(self):
        self.assertNotEqual(decide(self.search(),store_id=1,question="HOT 라테 우유 몇일 보관해?").plan.action,"ANSWER")
