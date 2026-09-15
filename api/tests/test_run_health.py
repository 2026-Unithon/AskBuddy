"""실행 건강도와 출력 채점 (W0).

여기 있는 검사는 전부 **실제로 겪은 오측정**에서 나왔다.
하네스가 틀린 수를 내면 그 위의 모든 판단이 틀린다.
"""
from __future__ import annotations

import unittest

from app.team.extraction import (
    RUN_DEAD,
    RUN_OK,
    RUN_PARTIAL,
    classify_claim,
    decide_majority,
    decide_unanimous,
    judge_run_health,
    score_output,
)


class RunHealthTest(unittest.TestCase):
    def test_all_sources_failed_is_not_a_measurement(self):
        """자료 5건이 전부 실패했는데 손실 100% 가 측정값으로 남았던 일이 있다."""
        state, reason = judge_run_health({"FAILED": 5}, card_count=0)
        self.assertEqual(state, RUN_DEAD)
        self.assertIn("측정이 아니다", reason)

    def test_zero_cards_is_not_a_measurement(self):
        """자료는 DONE 인데 카드가 없으면 조립이 돌지 않은 것이다."""
        state, reason = judge_run_health({"DONE": 5}, card_count=0)
        self.assertEqual(state, RUN_DEAD)
        self.assertIn("파이프라인이 돌지 않았다", reason)

    def test_partial_failure_is_not_success(self):
        """일부만 실패하면 분모가 달라진 측정이다. 성공과 같은 칸에 두지 않는다."""
        state, reason = judge_run_health({"DONE": 3, "FAILED": 2}, card_count=20)
        self.assertEqual(state, RUN_PARTIAL)
        self.assertIsNone(reason)

    def test_healthy_run(self):
        self.assertEqual(judge_run_health({"DONE": 5}, card_count=41),
                         (RUN_OK, None))

    def test_empty_store_is_not_dead(self):
        """자료가 아예 없는 매장은 실패가 아니다. 카드 0장으로 걸린다."""
        state, _ = judge_run_health({}, card_count=10)
        self.assertEqual(state, RUN_OK)


class OutputScoringTest(unittest.TestCase):
    """정답지만 순회하면 재현율만 보인다 — 쓰레기를 500건 뱉어도 점수가 같다."""

    TRUTH = [
        {"fact_id": "t-1", "subject": "음료 A", "variant": "ICE",
         "attribute": "우유량", "value": "225ml"},
        {"fact_id": "t-2", "subject": "재료 B", "variant": None,
         "attribute": "사용기한", "value": "14일"},
    ]

    def test_exact_match(self):
        verdict, fid, _ = classify_claim(
            {"subject": "음료 A", "variant": "ICE", "attribute": "우유량",
             "value": "225ml"}, self.TRUTH)
        self.assertEqual((verdict, fid), ("MATCHED", "t-1"))

    def test_wrong_attribute_same_value_is_unverified(self):
        verdict, _, _ = classify_claim(
            {"subject": "재료 B", "attribute": "발주주기", "value": "14일"}, self.TRUTH)
        self.assertEqual(verdict, "UNVERIFIED")

    def test_shared_word_does_not_match_different_numbers(self):
        for expected, actual in (("14 days", "90 days"), ("약 30분", "약 5분"),
                                 ("225ml", "225g")):
            with self.subTest(expected=expected, actual=actual):
                truth = [{"fact_id": "t", "subject": "예시", "attribute": "시간", "value": expected}]
                verdict, _, _ = classify_claim(
                    {"subject": "예시", "attribute": "시간", "value": actual}, truth)
                self.assertEqual(verdict, "CONFLICT")

    def test_same_subject_different_attribute_is_not_a_conflict(self):
        """"재료 B 발주요일" 과 "재료 B 사용기한" 은 둘 다 참이다.

        속성을 보지 않으면 같은 대상의 모든 추가 사실이 모순으로 잡힌다 —
        처음 만든 채점기가 정확히 그랬고, 오연결 9건 중 8건이 오탐이었다.
        """
        verdict, _, _ = classify_claim(
            {"subject": "재료 B", "attribute": "발주요일", "value": "화요일"},
            self.TRUTH)
        self.assertEqual(verdict, "UNVERIFIED")

    def test_same_attribute_different_value_is_a_conflict(self):
        """같은 것을 묻는데 다른 값. 누락보다 위험하다 — 신입은 그걸 따른다."""
        verdict, fid, _ = classify_claim(
            {"subject": "재료 B", "attribute": "사용기한", "value": "30일"},
            self.TRUTH)
        self.assertEqual((verdict, fid), ("CONFLICT", "t-2"))

    def test_missing_variant_is_a_conflict_not_a_match(self):
        """규격 없는 값은 '아무거나' 가 아니라 미확정이다 (MVP 31-2·D19).

        그대로 카드가 되면 ICE 전용 값이 HOT 에도 적용된다.
        """
        verdict, _, reason = classify_claim(
            {"subject": "음료 A", "variant": None, "attribute": "우유량",
             "value": "225ml"}, self.TRUTH)
        self.assertEqual(verdict, "CONFLICT")
        self.assertIn("규격", reason)

    def test_precision_is_a_range_not_a_number(self):
        """정답지는 전수가 아니다. 없는 것을 틀렸다고 단정하지 않는다."""
        claims = [
            {"fact_id": 1, "subject": "음료 A", "variant": "ICE",
             "attribute": "우유량", "value": "225ml"},          # MATCHED
            {"fact_id": 2, "subject": "청소기", "attribute": "주기",
             "value": "매일"},                                   # UNVERIFIED
        ]
        out = score_output(claims, self.TRUTH)
        self.assertEqual(out["precision_lower"], 0.5)
        self.assertEqual(out["precision_upper"], 1.0)
        self.assertEqual(out["undetermined_rate"], 0.5)

    def test_no_claims_reports_zero_not_perfect(self):
        """한 건도 안 뽑았을 때 정확도 100% 가 나오면 안 된다."""
        out = score_output([], self.TRUTH)
        self.assertEqual(out["claim_count"], 0)
        self.assertNotIn("precision_lower", out)


class RepeatDecisionTest(unittest.TestCase):
    """반복 판정 — 만장일치가 기준이고 갈린 것은 세어서 보고한다 (W0).

    실측: 같은 설정 두 묶음에서 다수결로 10건이 뒤집혔는데 만장일치로는 0건이었다.
    다수결이 잡음에서 신호를 만들고 있었다.
    """

    def test_unanimous_is_stable(self):
        self.assertEqual(decide_unanimous(["COVERED"] * 3), ("COVERED", True))

    def test_two_of_three_is_not_stable(self):
        """2:1 은 다수결로는 안정이지만 만장일치로는 흔들림이다."""
        split = ["COVERED", "COVERED", "MISSING"]
        self.assertTrue(decide_majority(split)[1])
        self.assertFalse(decide_unanimous(split)[1])

    def test_noise_does_not_become_a_change(self):
        """2:1 과 1:2 가 맞붙는 경우. 아무것도 안 바꿨는데 개선으로 보이던 자리다."""
        a = ["COVERED", "COVERED", "MISSING"]
        b = ["COVERED", "MISSING", "MISSING"]
        # 다수결은 COVERED → MISSING, 즉 '악화' 로 읽는다
        self.assertEqual((decide_majority(a)[0], decide_majority(b)[0]),
                         ("COVERED", "MISSING"))
        # 만장일치는 양쪽 다 흔들림이므로 판정하지 않는다
        self.assertFalse(decide_unanimous(a)[1])
        self.assertFalse(decide_unanimous(b)[1])

    def test_empty_is_not_unanimous(self):
        self.assertFalse(decide_unanimous([])[1])


if __name__ == "__main__":
    unittest.main()
