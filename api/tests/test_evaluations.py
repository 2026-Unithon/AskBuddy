from __future__ import annotations

import unittest

from app.team.metrics import (
    CaseOutcome,
    aggregate,
    citation_precision,
    expected_rank,
    fact_coverage,
    ndcg,
    percentile,
    reciprocal_rank,
    score_case,
)
from app.team.runner import estimate_cost


def _score(expected_kind, outcome, **kwargs):
    return score_case(
        expected_kind=expected_kind,
        expected_card_ids=kwargs.get("expected_card_ids", []),
        expected_facts=kwargs.get("expected_facts", []),
        expected_miss_reason=kwargs.get("expected_miss_reason"),
        outcome=outcome,
    )


class ScoringTest(unittest.TestCase):
    def test_hit_case_passes_when_expected_card_is_cited(self):
        score = _score(
            "HIT",
            CaseOutcome(
                actual_kind="HIT",
                retrieved_card_ids=[7, 9],
                citation_card_ids=[7],
                answer_text="우유는 2번 냉장고에 보관해요",
                retrieve_latency_ms=120,
                answer_latency_ms=800,
            ),
            expected_card_ids=[7],
            expected_facts=["2번 냉장고"],
        )
        self.assertTrue(score.passed)
        self.assertIsNone(score.failure_kind)
        self.assertEqual(score.expected_hit_rank, 1)
        self.assertEqual(score.fact_coverage, 1.0)
        self.assertEqual(score.total_latency_ms, 920)

    def test_hit_answer_without_citation_is_ungrounded_and_fails(self):
        """불변식 3 — 인용 없는 답변은 언제나 실패다."""
        score = _score(
            "HIT",
            CaseOutcome(actual_kind="HIT", retrieved_card_ids=[7], answer_text="아마 냉장고요"),
            expected_card_ids=[7],
        )
        self.assertTrue(score.ungrounded)
        self.assertFalse(score.passed)
        self.assertEqual(score.failure_kind, "NO_CITATION")

    def test_miss_on_answerable_question_is_false_miss(self):
        score = _score(
            "HIT",
            CaseOutcome(actual_kind="MISS", miss_reason="no_match"),
            expected_card_ids=[7],
        )
        self.assertEqual(score.failure_kind, "FALSE_MISS")
        self.assertFalse(score.kind_correct)

    def test_refuse_case_fails_when_answered(self):
        score = _score(
            "REFUSE",
            CaseOutcome(actual_kind="HIT", retrieved_card_ids=[3], citation_card_ids=[3]),
        )
        self.assertEqual(score.failure_kind, "SHOULD_NOT_ANSWER")
        self.assertFalse(score.kind_correct)

    def test_safe_route_case_passes_when_handed_to_owner(self):
        score = _score("SAFE_ROUTE", CaseOutcome(actual_kind="MISS", miss_reason="no_match"))
        self.assertTrue(score.passed)
        self.assertTrue(score.kind_correct)

    def test_miss_reason_mismatch_fails_when_reason_is_pinned(self):
        score = _score(
            "MISS",
            CaseOutcome(actual_kind="MISS", miss_reason="intent_mismatch"),
            expected_miss_reason="no_match",
        )
        self.assertEqual(score.failure_kind, "MISS_REASON_MISMATCH")

    def test_missing_expected_card_is_reported_separately_from_wrong_citation(self):
        score = _score(
            "HIT",
            CaseOutcome(actual_kind="HIT", retrieved_card_ids=[4], citation_card_ids=[4]),
            expected_card_ids=[7],
        )
        self.assertEqual(score.failure_kind, "EXPECTED_CARD_ABSENT")
        self.assertTrue(score.wrong_card)

    def test_missing_fact_fails_even_with_right_card(self):
        score = _score(
            "HIT",
            CaseOutcome(
                actual_kind="HIT",
                retrieved_card_ids=[7],
                citation_card_ids=[7],
                answer_text="냉장고에 있어요",
            ),
            expected_card_ids=[7],
            expected_facts=["2번 냉장고"],
        )
        self.assertEqual(score.failure_kind, "MISSING_FACT")
        self.assertEqual(score.fact_coverage, 0.0)

    def test_lower_rank_still_passes_but_is_recorded(self):
        score = _score(
            "HIT",
            CaseOutcome(actual_kind="HIT", retrieved_card_ids=[4, 7], citation_card_ids=[7]),
            expected_card_ids=[7],
        )
        self.assertTrue(score.passed)
        self.assertEqual(score.expected_hit_rank, 2)
        self.assertTrue(score.wrong_card)

    def test_run_error_never_counts_as_pass(self):
        score = _score("HIT", CaseOutcome(actual_kind="ERROR", error="boom"), expected_card_ids=[7])
        self.assertEqual(score.failure_kind, "RUN_ERROR")
        self.assertFalse(score.passed)


class HelperTest(unittest.TestCase):
    def test_fact_coverage_ignores_spacing_and_case(self):
        self.assertEqual(fact_coverage(["2번  냉장고"], "우유는 2번 냉장고 안"), 1.0)

    def test_fact_coverage_is_none_without_expectation(self):
        self.assertIsNone(fact_coverage([], "아무 답변"))

    def test_expected_rank_finds_first_match(self):
        self.assertEqual(expected_rank([9, 7], [4, 7, 9]), 2)
        self.assertIsNone(expected_rank([9], [4, 7]))

    def test_citation_precision_counts_only_expected_cards(self):
        self.assertEqual(citation_precision([7], [7, 4]), 0.5)
        self.assertIsNone(citation_precision([7], []))

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([10, 20, 30, 40], 0.5), 20.0)
        self.assertEqual(percentile([10, 20, 30, 40], 0.95), 40.0)
        self.assertIsNone(percentile([], 0.5))

    def test_cost_is_none_without_explicit_pricing(self):
        self.assertIsNone(estimate_cost(1000, 500, None))

    def test_cost_uses_given_pricing(self):
        self.assertEqual(estimate_cost(1000, 500, {"input": 0.1, "output": 0.4}), 0.3)


class RankQualityTest(unittest.TestCase):
    def test_reciprocal_rank_is_inverse_of_first_hit(self):
        self.assertEqual(reciprocal_rank([7], [7, 4]), 1.0)
        self.assertEqual(reciprocal_rank([7], [4, 7]), 0.5)
        self.assertEqual(reciprocal_rank([7], [4, 9, 7]), round(1 / 3, 4))

    def test_reciprocal_rank_is_zero_when_card_is_absent(self):
        """채점 제외가 아니라 0 이다. 빼면 MRR 이 부풀려진다."""
        self.assertEqual(reciprocal_rank([7], [4, 9]), 0.0)

    def test_reciprocal_rank_is_none_without_expectation(self):
        self.assertIsNone(reciprocal_rank([], [4]))

    def test_ndcg_is_one_when_expected_cards_lead(self):
        self.assertEqual(ndcg([7], [7, 4, 9]), 1.0)
        self.assertEqual(ndcg([7, 4], [7, 4, 9]), 1.0)

    def test_ndcg_drops_when_expected_card_slips(self):
        top = ndcg([7], [7, 4])
        slipped = ndcg([7], [4, 7])
        self.assertEqual(top, 1.0)
        self.assertLess(slipped, top)
        # 2위의 이득은 1/log2(3)
        self.assertAlmostEqual(slipped, 0.6309, places=3)

    def test_ndcg_is_zero_when_nothing_relevant_retrieved(self):
        self.assertEqual(ndcg([7], [4, 9]), 0.0)

    def test_ndcg_respects_cutoff_k(self):
        # k=1 이면 2위의 정답은 세지 않는다
        self.assertEqual(ndcg([7], [4, 7], k=1), 0.0)

    def test_ndcg_partial_credit_with_multiple_expected_cards(self):
        score = ndcg([7, 4], [7, 9])
        self.assertGreater(score, 0)
        self.assertLess(score, 1)

    def test_rank_metrics_only_scored_for_hit_cases(self):
        """miss 를 기대한 문항에 순위 품질은 뜻이 없다."""
        miss = _score("MISS", CaseOutcome(actual_kind="MISS", miss_reason="no_match"))
        self.assertIsNone(miss.reciprocal_rank)
        self.assertIsNone(miss.ndcg)

        hit = _score(
            "HIT",
            CaseOutcome(actual_kind="HIT", retrieved_card_ids=[4, 7], citation_card_ids=[7]),
            expected_card_ids=[7],
        )
        self.assertEqual(hit.reciprocal_rank, 0.5)
        self.assertAlmostEqual(hit.ndcg, 0.6309, places=3)


class AggregateTest(unittest.TestCase):
    def _rows(self):
        return [
            {
                "expected_kind": "HIT", "actual_kind": "HIT", "kind_correct": True,
                "passed": True, "failure_kind": None, "expected_hit_rank": 1,
                "reciprocal_rank": 1.0, "ndcg": 1.0,
                "wrong_card": False, "ungrounded": False, "citation_precision": 1.0,
                "fact_coverage": 1.0, "miss_reason": None, "total_latency_ms": 900,
                "prompt_tokens": 700, "completion_tokens": 90, "cost_usd": 0.001,
            },
            {
                "expected_kind": "HIT", "actual_kind": "MISS", "kind_correct": False,
                "passed": False, "failure_kind": "FALSE_MISS", "expected_hit_rank": None,
                "reciprocal_rank": 0.0, "ndcg": 0.0,
                "wrong_card": False, "ungrounded": False, "citation_precision": None,
                "fact_coverage": None, "miss_reason": "no_anchor", "total_latency_ms": 300,
                "prompt_tokens": None, "completion_tokens": None, "cost_usd": None,
            },
            {
                "expected_kind": "MISS", "actual_kind": "MISS", "kind_correct": True,
                "passed": True, "failure_kind": None, "expected_hit_rank": None,
                "reciprocal_rank": None, "ndcg": None,
                "wrong_card": False, "ungrounded": False, "citation_precision": None,
                "fact_coverage": None, "miss_reason": "no_match", "total_latency_ms": 200,
                "prompt_tokens": None, "completion_tokens": None, "cost_usd": None,
            },
        ]

    def test_metrics_cover_the_todo_list(self):
        m = aggregate(self._rows())
        self.assertEqual(m["case_count"], 3)
        self.assertEqual(m["passed_count"], 2)
        self.assertAlmostEqual(m["kind_accuracy"], 2 / 3, places=3)
        # 기대 카드 hit율은 HIT 문항(2건)만 분모로 쓴다
        self.assertEqual(m["expected_card_hit_rate"], 0.5)
        self.assertEqual(m["expected_card_top1_rate"], 0.5)
        self.assertEqual(m["ungrounded_count"], 0)
        self.assertEqual(m["miss_reason_distribution"], {"no_anchor": 1, "no_match": 1})
        self.assertEqual(m["failure_distribution"], {"FALSE_MISS": 1})
        # HIT 기대 2문항 중 하나는 1위(1.0), 하나는 미검색(0.0) → 평균 0.5
        self.assertEqual(m["mrr"], 0.5)
        self.assertEqual(m["ndcg_at_10"], 0.5)
        self.assertEqual(m["ndcg_k"], 10)
        self.assertEqual(m["latency_p50_ms"], 300.0)
        self.assertEqual(m["prompt_tokens_total"], 700)
        self.assertEqual(m["cost_usd_total"], 0.001)

    def test_empty_run_does_not_divide_by_zero(self):
        self.assertEqual(aggregate([]), {"case_count": 0})


if __name__ == "__main__":
    unittest.main()
