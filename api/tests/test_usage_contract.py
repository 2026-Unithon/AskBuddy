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


class StorageCostTest(unittest.TestCase):
    """저장비는 누적이라 작은 누락도 개월 수만큼 커진다."""

    def setUp(self):
        from app.usage.storage_inventory import storage_cost
        self.fn = storage_cost

    def test_known_sizes_are_priced_over_months(self):
        objs = [{"bytes": 1024 ** 3}, {"bytes": 1024 ** 3}]  # 2GB
        r = self.fn(objs, Decimal("3"), Decimal("0.021"))
        self.assertEqual(r["cost_status"], "COMPLETE")
        self.assertAlmostEqual(float(r["cost_usd"]), 0.126, places=6)

    def test_one_unknown_size_blocks_the_total(self):
        r = self.fn([{"bytes": 1024 ** 3}, {"bytes": None}],
                    Decimal("1"), Decimal("0.021"))
        self.assertIsNone(r["cost_usd"], "크기를 못 재면 총액을 주장하지 않는다")
        self.assertEqual(r["unknown_size_count"], 1)
        self.assertEqual(r["cost_status"], "PARTIAL")

    def test_missing_rate_keeps_bytes_but_no_cost(self):
        r = self.fn([{"bytes": 1024 ** 3}], Decimal("1"), None)
        self.assertIsNone(r["cost_usd"])
        self.assertEqual(r["known_bytes"], 1024 ** 3)

    def test_empty_store_is_unknown_not_zero(self):
        r = self.fn([], Decimal("1"), Decimal("0.021"))
        self.assertEqual(r["cost_status"], "UNKNOWN")
        self.assertIsNone(r["cost_usd"])


class ReportTest(unittest.TestCase):
    """등록·운영을 가르고, 못 재면 통과를 선언하지 않는다."""

    def setUp(self):
        from app.usage import report
        self.r = report

    def test_scenarios_file_loads(self):
        data = self.r.load_scenarios()
        self.assertEqual(len(data["scenarios"]), 3)

    def test_first_month_is_more_expensive_than_stable(self):
        """신입이 몰리는 달이 가장 비싸다. 평균으로 뭉개면 첫 달을 못 버틴다."""
        base = next(s for s in self.r.load_scenarios()["scenarios"] if s["id"] == "BASE")
        first = self.r.project_operating(base, Decimal("0.001"), Decimal("0"), month=1)
        stable = self.r.project_operating(base, Decimal("0.001"), Decimal("0"), month=2)
        self.assertGreater(first["questions"], stable["questions"])
        self.assertEqual(first["questions"], 960)

    def test_unmeasured_cost_is_undetermined_not_pass(self):
        self.assertEqual(self.r.judge_d21(None), self.r.UNDETERMINED)

    def test_over_budget_fails(self):
        self.assertEqual(self.r.judge_d21(Decimal("3001")), self.r.FAIL)
        self.assertEqual(self.r.judge_d21(Decimal("3000")), self.r.PASS)

    def test_missing_component_blocks_the_total(self):
        base = next(s for s in self.r.load_scenarios()["scenarios"] if s["id"] == "LOW")
        out = self.r.project_operating(base, None, Decimal("1"))
        self.assertIsNone(out["total_usd"], "한 항목이라도 못 재면 총액이 없다")

    def test_unit_costs_report_observation_rate(self):
        attempts = [
            {"stage": "ANSWER", "usage_status": "COMPLETE",
             "known_cost_usd": "0.002", "prompt_tokens": 500, "completion_tokens": 50},
            {"stage": "ANSWER", "usage_status": "UNKNOWN", "known_cost_usd": None},
        ]
        u = self.r.unit_costs(attempts)["ANSWER"]
        self.assertEqual(u["attempts"], 2)
        self.assertEqual(u["observation_rate"], 0.5)

    def test_registration_months_is_budget_equivalent_not_payback(self):
        self.assertEqual(self.r.registration_months(Decimal("6000")), Decimal("2"))
        self.assertIsNone(self.r.registration_months(None))
