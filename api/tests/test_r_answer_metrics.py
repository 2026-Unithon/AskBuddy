import unittest
from app.team.answer_metrics import question_metrics, validator_metrics, paired_gate


class MetricsTest(unittest.TestCase):
    def test_final_and_candidate_denominators_are_separate(self):
        rows = [dict(question_id="1",expected_action="ANSWER",actual_action="ERROR"),
                dict(question_id="2",expected_action="ANSWER",actual_action="ANSWER"),
                dict(question_id="3",expected_action="REFUSE",actual_action="REFUSE"),
                dict(question_id="4",expected_action="ESCALATE",actual_action="ESCALATE",knowledge_block=True,block_correct=True)]
        result = question_metrics(rows)
        self.assertEqual(result['false_abstention_rate'], .5)
        self.assertEqual(result['block_precision'], 1)
        self.assertEqual(result['action_accuracy'], .75)
        candidates = [dict(candidate_id="a",correct=True,blocked=True),
                      dict(candidate_id="b",correct=False,blocked=False),
                      dict(candidate_id="c",correct=False,blocked=True)]
        result = validator_metrics(candidates)
        self.assertEqual(result['validator_block_precision'], .5)
        self.assertEqual(result['validator_false_block_rate'], 1)
        self.assertEqual(result['validator_missed_error_rate'], .5)
    def test_unknown_labels_not_removed_from_denominator(self):
        result = question_metrics([dict(question_id="1",expected_action="ANSWER",actual_action="CLARIFY",knowledge_block=True)])
        self.assertIsNone(result['block_precision'])
        self.assertEqual(result['unjudged_block_count'], 1)

    def test_only_knowledge_blocks_enter_precision_denominator(self):
        rows = [dict(question_id="1", expected_action="ESCALATE", actual_action="ESCALATE",
                     knowledge_block=False, block_correct=False),
                dict(question_id="2", expected_action="CLARIFY", actual_action="CLARIFY",
                     knowledge_block=True, block_correct=True)]
        result = question_metrics(rows)
        self.assertEqual(result["block_count"], 1)
        self.assertEqual(result["block_precision"], 1)
        del rows[0]["knowledge_block"]
        result = question_metrics(rows)
        self.assertIsNone(result["block_precision"])
        self.assertEqual(result["unclassified_block_count"], 1)
    def test_paired_fixed_denominator_and_cost_gate(self):
        a = {str(i):False for i in range(10)}
        pairs = [(a, {str(i):i<n for i in range(10)}) for n in (5,6,7)]
        options = dict(control_width=4,must_have_regressions=0,ledger_recall_regressed=False,
                       must_have_ids=[])
        result = paired_gate(pairs, **options, cost_gate_passed=True)
        self.assertEqual(result['median_delta'],6)
        self.assertTrue(result['eligible'])
        self.assertFalse(paired_gate(pairs,**options)['eligible'])
        with self.assertRaises(ValueError):
            paired_gate([*pairs[:2],(a,{})],**options)
