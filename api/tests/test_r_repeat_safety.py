"""반복별 필수 질문 악화를 대표 순증/만장일치가 가리지 않는지 검증한다."""
import unittest

from app.team.answer_metrics import paired_gate


class RepeatSafetyTest(unittest.TestCase):
    def pairs(self):
        baseline = {str(i): False for i in range(8)} | {"required": True}
        candidate = {str(i): True for i in range(8)} | {"required": True}
        return [(dict(baseline), dict(candidate)) for _ in range(3)]

    def evaluate(self, pairs, **overrides):
        options = dict(control_width=0, must_have_regressions=0,
                       ledger_recall_regressed=False, cost_gate_passed=True,
                       must_have_ids=["required"])
        return paired_gate(pairs, **(options | overrides))

    def test_required_always_success_to_mixed_blocks_despite_positive_median(self):
        pairs = self.pairs()
        pairs[2][1]["required"] = False
        result = self.evaluate(pairs)
        self.assertEqual(result["median_delta"], 8)
        self.assertFalse(result["eligible"])
        self.assertFalse(result["must_have_passed"])
        self.assertEqual(result["must_have_regression_ids"], ["required"])
        self.assertEqual(result["stability_transitions"]["ALL_SUCCESS->MIXED"], ["required"])

    def test_mixed_required_regression_cannot_be_dropped(self):
        pairs = self.pairs()
        pairs[0][0]["required"] = False
        pairs[1][1]["required"] = False
        result = self.evaluate(pairs)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["stability_transitions"]["MIXED->MIXED"], ["required"])

    def test_required_always_success_to_failure_blocks(self):
        pairs = self.pairs()
        for _, candidate in pairs:
            candidate["required"] = False
        self.assertFalse(self.evaluate(pairs)["eligible"])

    def test_unknown_stays_in_denominator_and_blocks(self):
        pairs = self.pairs()
        pairs[2][1]["required"] = None
        result = self.evaluate(pairs)
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["must_have_passed"])
        self.assertIsNone(result["median_delta"])
        self.assertEqual(result["question_count"], 9)
        self.assertEqual(result["unjudged_ids"], ["required"])
        self.assertEqual(result["deltas"], [8, 8, None])

    def test_missing_manifest_is_not_zero_required_cases(self):
        result = self.evaluate(self.pairs(), must_have_ids=None)
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["must_have_passed"])
        self.assertIn("MISSING_MUST_HAVE_MANIFEST", result["blocking_reasons"])

    def test_unknown_nonrequired_case_also_blocks_complete_gate(self):
        pairs = self.pairs()
        pairs[0][1]["0"] = None
        result = self.evaluate(pairs)
        self.assertFalse(result["eligible"])
        self.assertTrue(result["must_have_passed"])

    def test_missing_or_invalid_ids_are_rejected(self):
        pairs = self.pairs()
        del pairs[0][1]["required"]
        with self.assertRaises(ValueError):
            self.evaluate(pairs)
        for ids in (["outside"], ["required", "required"], "required"):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.evaluate(self.pairs(), must_have_ids=ids)

    def test_valid_improvement_keeps_original_median_and_cost_gate(self):
        result = self.evaluate(self.pairs())
        self.assertTrue(result["eligible"])
        self.assertEqual(result["deltas"], [8, 8, 8])
        self.assertEqual(result["schema_version"], "r_paired_gate/v2")
        self.assertFalse(self.evaluate(self.pairs(), cost_gate_passed=False)["eligible"])
        self.assertFalse(self.evaluate(self.pairs(), must_have_regressions=1)["eligible"])

    def test_external_unknown_gate_is_rejected_not_treated_as_false(self):
        for options in (dict(control_width=float("nan")), dict(control_width=float("inf")),
                        dict(control_width=True), dict(must_have_regressions=-1),
                        dict(must_have_regressions=True), dict(ledger_recall_regressed=None),
                        dict(cost_gate_passed="yes")):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.evaluate(self.pairs(), **options)

    def test_non_boolean_judgment_is_rejected(self):
        pairs = self.pairs()
        pairs[0][1]["0"] = 1
        with self.assertRaises(ValueError):
            self.evaluate(pairs)

    def test_stability_improvement_is_reported_without_double_counting(self):
        pairs = self.pairs()
        pairs[0][0]["required"] = False
        result = self.evaluate(pairs)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["median_delta"], 8)
        self.assertEqual(result["deltas"], [9, 8, 8])
        self.assertEqual(result["stability_transitions"]["MIXED->ALL_SUCCESS"], ["required"])

    def test_confirmed_failure_is_not_erased_by_another_unknown(self):
        pairs = self.pairs()
        pairs[0][1]["required"] = False
        pairs[1][1]["required"] = None
        result = self.evaluate(pairs)
        self.assertFalse(result["must_have_passed"])
        self.assertIn("MUST_HAVE_REGRESSION", result["blocking_reasons"])
        self.assertIn("UNJUDGED_RESULTS", result["blocking_reasons"])
