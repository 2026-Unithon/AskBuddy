"""CP-00A 원가 계측 계약 — 결측과 0 을 구분하는지 고정한다.

0 으로 채우면 총액이 사실보다 싸 보이고, 그 수치로 D21 통과를 선언하게 된다.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from pydantic import ValidationError

from app.contracts.usage import ModelUsage, UsageAttempt, UsageContext
from app.usage.pricing import price_attempt, summarize
from app.usage.rates import RateCard

PRICED = RateCard({
    "version": "test-1",
    "models": {
        "gemini-3.6-flash": {
            "input_per_1m_tokens": "0.30",
            "output_per_1m_tokens": "2.50",
        },
        "whisper-1": {"per_minute": "0.006"},
    },
    "storage": {"per_gb_month": "0.021"},
})
UNPRICED = RateCard({"version": "unset", "models": {}, "storage": {}})


def _ctx(**kw):
    base = dict(store_id="5", cost_phase="REGISTRATION", stage="EXTRACT",
                logical_call_id="call-1")
    base.update(kw)
    return UsageContext(**base)


def _attempt(**kw):
    base = dict(context=_ctx(), requested_model="gemini-3.6-flash")
    base.update(kw)
    return UsageAttempt(**base)


class ContractTest(unittest.TestCase):
    def test_store_id_is_required(self):
        """매장 귀속 없는 비용은 D21 계산에 쓸 수 없다."""
        with self.assertRaises(ValidationError):
            UsageContext(cost_phase="OPERATING", stage="ANSWER", logical_call_id="c")

    def test_complete_without_usage_is_rejected(self):
        with self.assertRaises(ValidationError):
            _attempt(usage_status="COMPLETE")

    def test_incomplete_observation_cannot_claim_a_total(self):
        """관측이 불완전하면 총액을 주장하지 않는다."""
        with self.assertRaises(ValidationError):
            _attempt(usage_status="PARTIAL",
                     usage=ModelUsage(prompt_tokens=10), cost_usd=Decimal("1"))

    def test_not_billable_must_have_no_usage(self):
        with self.assertRaises(ValidationError):
            _attempt(usage_status="NOT_BILLABLE", usage=ModelUsage(prompt_tokens=1))

    def test_missing_is_none_not_zero(self):
        """못 잰 것은 null 이다. 0 은 '무상' 이라는 뜻이다."""
        usage = ModelUsage()
        self.assertIsNone(usage.prompt_tokens)
        self.assertTrue(usage.is_empty())
        self.assertFalse(ModelUsage(prompt_tokens=0).is_empty())


class PricingTest(unittest.TestCase):
    def test_priced_complete_call_gets_a_total(self):
        a = _attempt(usage_status="COMPLETE",
                     usage=ModelUsage(prompt_tokens=1_000_000,
                                      completion_tokens=1_000_000))
        known, cost, status = price_attempt(a, PRICED)
        self.assertEqual(known, Decimal("2.80"))
        self.assertEqual(cost, Decimal("2.80"))
        self.assertEqual(status, "PRICED")

    def test_no_rate_keeps_tokens_but_gives_no_total(self):
        """요율이 없어도 계측은 돈다. 토큰을 쌓고 나중에 곱한다."""
        a = _attempt(usage_status="COMPLETE",
                     usage=ModelUsage(prompt_tokens=1_000_000))
        known, cost, status = price_attempt(a, UNPRICED)
        self.assertIsNone(cost)
        self.assertEqual(status, "NO_RATE")

    def test_partial_observation_gives_known_but_not_total(self):
        a = _attempt(usage_status="PARTIAL",
                     usage=ModelUsage(prompt_tokens=1_000_000))
        known, cost, _ = price_attempt(a, PRICED)
        self.assertEqual(known, Decimal("0.30"))
        self.assertIsNone(cost, "관측이 불완전하면 총액을 내지 않는다")

    def test_unknown_billable_unit_is_not_silently_free(self):
        """모르는 과금 단위를 0 으로 넘기면 총액이 거짓이 된다."""
        a = _attempt(usage_status="COMPLETE",
                     usage=ModelUsage(billable_units=Decimal("38"),
                                      billable_unit_name="frame"))
        _, cost, status = price_attempt(a, PRICED)
        self.assertIsNone(cost)
        self.assertEqual(status, "UNKNOWN_UNITS")

    def test_stt_minutes_are_priced(self):
        a = _attempt(requested_model="whisper-1", usage_status="COMPLETE",
                     usage=ModelUsage(billable_units=Decimal("38"),
                                      billable_unit_name="minute"))
        _, cost, status = price_attempt(a, PRICED)
        self.assertEqual(cost, Decimal("0.228"))
        self.assertEqual(status, "PRICED")

    def test_mock_run_is_not_billable(self):
        """mock 실행을 원가로 집계하지 않는다 (D10)."""
        a = _attempt(mode="mock", usage_status="NOT_BILLABLE")
        known, cost, _ = price_attempt(a, PRICED)
        self.assertEqual(cost, Decimal("0"))


class SummaryTest(unittest.TestCase):
    def test_one_unobserved_call_blocks_the_total(self):
        """하나라도 못 재면 합계를 주장하지 않는다. 관측률로 드러낸다."""
        attempts = [
            _attempt(usage_status="COMPLETE",
                     usage=ModelUsage(prompt_tokens=1_000_000)),
            _attempt(context=_ctx(logical_call_id="c2"), usage_status="UNKNOWN"),
        ]
        # 요율표를 쓰지 않는 경로라 기본 요율표(미설정)로 계산된다
        s = summarize(attempts)
        self.assertEqual(s["attempt_count"], 2)
        self.assertEqual(s["unknown_count"], 1)
        self.assertEqual(s["observation_rate"], 0.5)
        self.assertIsNone(s["total_cost_usd"])

    def test_empty_is_not_zero_cost(self):
        s = summarize([])
        self.assertIsNone(s["observation_rate"])
        self.assertIsNone(s["total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
