"""R 유료 캠페인 사전등록 — 등록·예산 가드·사후 대조.

D17·D18 이 요구하는 "실험 전 고정" 이 실제로 강제되는지 본다. 유료 호출은 하지
않는다(이 테스트는 등록 레코드와 산술 보고만 다룬다).
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.contracts.hashing import digest
from app.team.prereg import (
    BudgetDeniedByPrereg,
    CampaignRegistration,
    PreregViolation,
    authorize_live_call,
    build_registration,
    campaign_passes_prereg,
    check_campaign,
    registration_hash,
    verify_live_plan,
)

NOW = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


def _budget(**over) -> dict:
    budget = dict(usd_cap="2.50", approved_by="점주", approved_at=NOW - timedelta(hours=1),
                  approval_ref="2026-10-14 대화 승인")
    budget.update(over)
    return budget


def _fields(**over) -> dict:
    fields = dict(
        registered_at=NOW, registered_by="R 담당", purpose="P4 실제 품질·지연 인수",
        manifest_hash=HASH, truth_kind="HUMAN_REVIEWED", truth_version="p4/v1",
        snapshot_id="1", knowledge_revision="1", snapshot_hash=OTHER_HASH,
        evaluator_hashes={"v2_campaign.py": HASH}, source_manifest_hash=HASH,
        question_ids=("q1", "q2", "q3"), must_have_ids=("q1",),
        repeat_count=3, control_count=3, min_median_delta=1, cost_neutral=False,
        provider_mode="LIVE", model_ids=("gemini-3.6-flash",),
        failure_policy=dict(timeout_as="UNJUDGED", per_call_timeout_seconds=30, retry_limit=1,
                            partial_run="DISCARD_RUN"),
        budget=_budget(),
    )
    fields.update(over)
    return fields


def _registration(**over) -> CampaignRegistration:
    return CampaignRegistration(**_fields(**over))


def _report(registration: CampaignRegistration, **over) -> dict:
    report = dict(
        plan=dict(registration_ref=registration_hash(registration),
                  manifest_hash=registration.manifest_hash,
                  repeat_count=registration.repeat_count,
                  control_count=registration.control_count,
                  cost_neutral=registration.cost_neutral),
        evaluator_hashes=dict(registration.evaluator_hashes),
        gate=dict(question_count=len(registration.question_ids),
                  must_have_ids=list(registration.must_have_ids),
                  median_delta=2, eligible=True),
    )
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(report.get(key), dict):
            report[key] = {**report[key], **value}
        else:
            report[key] = value
    return report


class RegistrationShapeTest(unittest.TestCase):
    def test_build_returns_stable_hash(self):
        first, ref = build_registration(**_fields())
        second, again = build_registration(**_fields())
        self.assertEqual(ref, again)
        self.assertEqual(ref, registration_hash(first))
        self.assertTrue(ref.startswith("sha256:"))

    def test_any_change_moves_the_hash(self):
        _, ref = build_registration(**_fields())
        for over in (dict(min_median_delta=2), dict(repeat_count=4),
                     dict(question_ids=("q1", "q2")), dict(purpose="다른 목적"),
                     dict(model_ids=("gemini-3.6-flash", "claude-haiku-4-5-20251001"))):
            with self.subTest(over=over):
                _, moved = build_registration(**_fields(**over))
                self.assertNotEqual(ref, moved)

    def test_minimum_repeats_and_controls(self):
        for over in (dict(repeat_count=2), dict(control_count=2)):
            with self.subTest(over=over):
                with self.assertRaises(ValueError):
                    _registration(**over)

    def test_campaign_needs_a_representative_delta(self):
        with self.assertRaises(ValueError):
            _registration(min_median_delta=None)

    def test_diagnostic_allows_one_run_and_no_controls(self):
        registration = _registration(run_kind="DIAGNOSTIC", repeat_count=1, control_count=0,
                                     min_median_delta=None)
        self.assertEqual(registration.run_kind, "DIAGNOSTIC")

    def test_diagnostic_must_not_declare_a_representative_delta(self):
        with self.assertRaises(ValueError):
            _registration(run_kind="DIAGNOSTIC", repeat_count=1, control_count=0,
                          min_median_delta=3)

    def test_diagnostic_still_needs_budget_and_input_pinning(self):
        with self.assertRaises(ValueError):
            _registration(run_kind="DIAGNOSTIC", repeat_count=1, control_count=0,
                          min_median_delta=None, budget=None)

    def test_must_have_must_be_inside_denominator(self):
        with self.assertRaises(ValueError):
            _registration(must_have_ids=("q9",))

    def test_duplicate_question_ids_rejected(self):
        with self.assertRaises(ValueError):
            _registration(question_ids=("q1", "q1"))

    def test_live_mode_requires_budget(self):
        with self.assertRaises(ValueError):
            _registration(budget=None)

    def test_synthetic_mode_may_omit_budget(self):
        registration = _registration(provider_mode="SYNTHETIC", budget=None)
        self.assertIsNone(registration.budget)

    def test_budget_approval_cannot_postdate_registration(self):
        with self.assertRaises(ValueError):
            _registration(budget=_budget(approved_at=NOW + timedelta(minutes=1)))

    def test_krw_cap_needs_exchange_rate(self):
        with self.assertRaises(ValueError):
            _registration(budget=_budget(krw_cap="10000"))
        ok = _registration(budget=_budget(krw_cap="10000", fx_krw_per_usd="1380"))
        self.assertEqual(ok.budget.krw_cap, "10000")

    def test_unknown_money_stays_none_not_zero(self):
        registration = _registration()
        self.assertIsNone(registration.budget.krw_cap)
        self.assertIsNone(registration.budget.fx_krw_per_usd)

    def test_zero_budget_rejected(self):
        with self.assertRaises(ValueError):
            _registration(budget=_budget(usd_cap="0"))

    def test_naive_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            _registration(registered_at=datetime(2026, 10, 14, 3, 0))

    def test_unknown_field_is_refused(self):
        with self.assertRaises(ValueError):
            _registration(extra_knob=1)

    def test_evaluator_hash_format_is_checked(self):
        with self.assertRaises(ValueError):
            _registration(evaluator_hashes={"v2_campaign.py": "deadbeef"})


class AuthorizeLiveCallTest(unittest.TestCase):
    def test_within_budget_passes(self):
        authorize_live_call(_registration(), now=NOW, spent_usd="1.00")

    def test_cap_reached_blocks_next_call(self):
        with self.assertRaises(BudgetDeniedByPrereg):
            authorize_live_call(_registration(), now=NOW, spent_usd="2.50")

    def test_pending_amount_counts_toward_cap(self):
        with self.assertRaises(BudgetDeniedByPrereg):
            authorize_live_call(_registration(), now=NOW, spent_usd="2.00", pending_usd="0.60")

    def test_synthetic_registration_cannot_make_paid_calls(self):
        registration = _registration(provider_mode="SYNTHETIC", budget=None)
        with self.assertRaises(PreregViolation):
            authorize_live_call(registration, now=NOW, spent_usd="0")

    def test_running_before_registration_is_not_preregistered(self):
        with self.assertRaises(PreregViolation):
            authorize_live_call(_registration(), now=NOW - timedelta(seconds=1), spent_usd="0")

    def test_naive_now_and_bad_amount_rejected(self):
        with self.assertRaises(PreregViolation):
            authorize_live_call(_registration(), now=datetime(2026, 10, 14, 4, 0), spent_usd="0")
        with self.assertRaises(PreregViolation):
            authorize_live_call(_registration(), now=NOW, spent_usd="많이")
        with self.assertRaises(PreregViolation):
            authorize_live_call(_registration(), now=NOW, spent_usd="-1")


class VerifyLivePlanTest(unittest.TestCase):
    def _args(self, **over) -> dict:
        args = dict(challenge_hash="a" * 64, source_manifest_hash=HASH,
                    model="gemini-3.6-flash", turn_ids=("q1", "q2", "q3"))
        args.update(over)
        return args

    def test_matching_plan_passes(self):
        verify_live_plan(_registration(), **self._args())

    def test_bare_hex_and_prefixed_hashes_are_the_same(self):
        verify_live_plan(_registration(), **self._args(challenge_hash=HASH))

    def test_other_question_set_is_refused(self):
        with self.assertRaises(PreregViolation):
            verify_live_plan(_registration(), **self._args(challenge_hash="c" * 64))

    def test_code_change_after_registration_is_refused(self):
        with self.assertRaises(PreregViolation):
            verify_live_plan(_registration(), **self._args(source_manifest_hash=OTHER_HASH))

    def test_unregistered_model_is_refused(self):
        with self.assertRaises(PreregViolation):
            verify_live_plan(_registration(), **self._args(model="다른-모델"))

    def test_denominator_order_and_size_must_match(self):
        for ids in (("q1", "q2"), ("q3", "q2", "q1"), ("q1", "q2", "q3", "q4")):
            with self.subTest(ids=ids):
                with self.assertRaises(PreregViolation):
                    verify_live_plan(_registration(), **self._args(turn_ids=ids))

    def test_synthetic_registration_cannot_start_a_live_run(self):
        registration = _registration(provider_mode="SYNTHETIC", budget=None)
        with self.assertRaises(PreregViolation):
            verify_live_plan(registration, **self._args())

    def test_plan_cannot_exceed_registered_krw_cap(self):
        registration = _registration(
            budget=_budget(krw_cap="10000", fx_krw_per_usd="1380"))
        verify_live_plan(registration, **self._args(max_krw=10000))
        with self.assertRaises(BudgetDeniedByPrereg):
            verify_live_plan(registration, **self._args(max_krw=10001))

    def test_krw_plan_without_registered_krw_cap_is_refused(self):
        with self.assertRaises(PreregViolation):
            verify_live_plan(_registration(), **self._args(max_krw=5000))


class CheckCampaignTest(unittest.TestCase):
    def test_matching_run_has_no_problem(self):
        registration = _registration()
        self.assertEqual(check_campaign(_report(registration), registration), [])
        self.assertTrue(campaign_passes_prereg(_report(registration), registration))

    def test_registration_ref_must_be_this_registration(self):
        registration = _registration()
        other = _registration(purpose="다른 캠페인")
        report = _report(registration, plan=dict(registration_ref=registration_hash(other)))
        self.assertIn("REGISTRATION_REF_MISMATCH", check_campaign(report, registration))

    def test_denominator_shrink_is_caught(self):
        registration = _registration()
        report = _report(registration, gate=dict(question_count=2))
        self.assertIn("DENOMINATOR_CHANGED", check_campaign(report, registration))

    def test_unregistered_must_have_is_caught(self):
        registration = _registration()
        report = _report(registration, gate=dict(must_have_ids=["q1", "q2"]))
        self.assertIn("MUST_HAVE_NOT_REGISTERED", check_campaign(report, registration))

    def test_missing_must_have_manifest_is_caught(self):
        registration = _registration()
        report = _report(registration, gate=dict(must_have_ids=None))
        self.assertIn("MUST_HAVE_MANIFEST_MISSING", check_campaign(report, registration))

    def test_grader_change_after_the_run_is_caught(self):
        registration = _registration()
        report = _report(registration, evaluator_hashes={"v2_campaign.py": OTHER_HASH})
        self.assertIn("EVALUATOR_CHANGED", check_campaign(report, registration))

    def test_repeat_and_control_counts_are_compared(self):
        registration = _registration()
        report = _report(registration, plan=dict(repeat_count=5, control_count=4))
        problems = check_campaign(report, registration)
        self.assertIn("REPEAT_COUNT_CHANGED", problems)
        self.assertIn("CONTROL_COUNT_CHANGED", problems)

    def test_unjudged_representative_delta_blocks(self):
        registration = _registration()
        report = _report(registration, gate=dict(median_delta=None))
        self.assertIn("REPRESENTATIVE_DELTA_UNJUDGED", check_campaign(report, registration))

    def test_below_registered_minimum_delta_blocks(self):
        registration = _registration(min_median_delta=5)
        report = _report(registration, gate=dict(median_delta=4))
        self.assertIn("BELOW_REGISTERED_MIN_DELTA", check_campaign(report, registration))

    def test_all_problems_are_reported_not_just_the_first(self):
        registration = _registration()
        report = _report(registration, plan=dict(manifest_hash=HASH.replace("a", "c"),
                                                 repeat_count=9),
                         gate=dict(median_delta=None))
        problems = check_campaign(report, registration)
        self.assertIn("MANIFEST_MISMATCH", problems)
        self.assertIn("REPEAT_COUNT_CHANGED", problems)
        self.assertIn("REPRESENTATIVE_DELTA_UNJUDGED", problems)

    def test_arithmetic_gate_failure_is_not_a_prereg_pass(self):
        registration = _registration()
        report = _report(registration, gate=dict(eligible=False))
        self.assertEqual(check_campaign(report, registration), [])
        self.assertFalse(campaign_passes_prereg(report, registration))

    def test_diagnostic_registration_cannot_be_graded_as_a_campaign(self):
        registration = _registration(run_kind="DIAGNOSTIC", repeat_count=1, control_count=0,
                                     min_median_delta=None)
        report = _report(registration)
        self.assertEqual(check_campaign(report, registration), ["DIAGNOSTIC_NOT_A_CAMPAIGN"])
        self.assertFalse(campaign_passes_prereg(report, registration))

    def test_empty_report_does_not_pass_quietly(self):
        registration = _registration()
        self.assertTrue(check_campaign({}, registration))
        self.assertFalse(campaign_passes_prereg({}, registration))


class HashIndependenceTest(unittest.TestCase):
    def test_registration_hash_is_canonical_json_of_the_record(self):
        registration = _registration()
        self.assertEqual(registration_hash(registration),
                         digest(registration.model_dump(mode="json")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
