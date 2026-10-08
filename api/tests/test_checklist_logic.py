from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from pydantic import ValidationError

from app.checklist.calendar import ShiftWindow, business_date, pick_current_shift, split_lines
from app.checklist import repository as repo
from app.checklist.router import Member, date_policy, month_range, records_access, require_owner_member
from app.checklist.schemas import CardLinks, CheckItem, IdList, Settings, ShiftCreate, ShiftOrder, ShiftUpdate
from app.checklist.scope import ChecklistCard, Scope, Shift, build_today, cards_in_scope, line_keys, resolve_scope
from app.errors import ApiError

FOUR = time(4, 0)


def card(card_id, version, lines, *, common=False, shifts=()):
    return ChecklistCard(card_id, version, f"카드{card_id}", tuple(lines), common, frozenset(shifts))


class CalendarTest(unittest.TestCase):
    def test_business_date_before_day_start_is_previous_day(self):
        # 서울 10/7 03:59 = UTC 10/6 18:59 → 영업일 10/6
        now = datetime(2026, 10, 6, 18, 59, tzinfo=timezone.utc)
        self.assertEqual(business_date(now, "Asia/Seoul", FOUR), date(2026, 10, 6))

    def test_business_date_at_day_start_is_new_day(self):
        now = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)  # 서울 04:00
        self.assertEqual(business_date(now, "Asia/Seoul", FOUR), date(2026, 10, 7))

    def test_split_lines_drops_blank_and_trims(self):
        self.assertEqual(split_lines(" 머신 청소 \n\n 원두 소분\n"), ["머신 청소", "원두 소분"])

    def test_current_shift_inside_window(self):
        shifts = [ShiftWindow(1, 0, time(7), time(11)), ShiftWindow(2, 1, time(14), time(18))]
        self.assertEqual(pick_current_shift(shifts, time(15), FOUR), (2, False))

    def test_current_shift_overnight(self):
        shifts = [ShiftWindow(3, 0, time(22), time(1))]
        self.assertEqual(pick_current_shift(shifts, time(0, 30), FOUR), (3, False))

    def test_current_shift_upcoming_before_opening(self):
        shifts = [ShiftWindow(1, 0, time(7), time(11)), ShiftWindow(2, 1, time(14), time(18))]
        self.assertEqual(pick_current_shift(shifts, time(5), FOUR), (1, True))

    def test_current_shift_falls_back_to_first_after_last(self):
        shifts = [ShiftWindow(1, 0, time(7), time(11))]
        self.assertEqual(pick_current_shift(shifts, time(23), FOUR), (1, False))

    def test_untimed_shifts_are_never_auto_picked_but_fallback(self):
        shifts = [ShiftWindow(5, 0, None, None)]
        self.assertEqual(pick_current_shift(shifts, time(12), FOUR), (5, False))

    def test_no_shifts(self):
        self.assertEqual(pick_current_shift([], time(12), FOUR), (None, False))


class ScopeTest(unittest.TestCase):
    def test_owner_scope_is_all(self):
        self.assertEqual(resolve_scope("OWNER", [1, 2], {1}), Scope(True, (1, 2)))

    def test_staff_without_assignment_is_all(self):
        self.assertEqual(resolve_scope("STAFF", [1, 2], set()), Scope(True, (1, 2)))

    def test_store_without_shifts_is_all(self):
        self.assertEqual(resolve_scope("STAFF", [], {9}), Scope(True, ()))

    def test_staff_assigned_keeps_shift_order_and_drops_archived(self):
        self.assertEqual(resolve_scope("STAFF", [1, 2, 3], {3, 1, 99}), Scope(False, (1, 3)))

    def test_cards_in_scope_common_plus_assigned(self):
        cards = [card(1, 10, ["a"], common=True), card(2, 20, ["b"], shifts={1}), card(3, 30, ["c"], shifts={2})]
        got = cards_in_scope(cards, Scope(False, (1,)))
        self.assertEqual([c.card_id for c in got], [1, 2])

    def test_card_only_on_archived_shift_is_hidden(self):
        # 보관한 근무조에만 있던 카드: common=False, 활성 shift_ids 비어 있음 → 어디에도 안 나온다
        cards = [card(4, 40, ["d"], common=False, shifts=())]
        self.assertEqual(cards_in_scope(cards, Scope(True, (1, 2))), [])

    def test_line_keys_count_card_once_even_in_two_shifts(self):
        cards = [card(2, 20, ["b1", "b2"], shifts={1, 2})]
        self.assertEqual(line_keys(cards), {(20, 1), (20, 2)})


class BuildTodayTest(unittest.TestCase):
    def setUp(self):
        self.shifts = [Shift(1, "오픈", 0, time(7), time(11)), Shift(2, "마감", 1, time(22), time(1))]
        self.cards = [
            card(1, 10, ["물 채우기"], common=True),
            card(2, 20, ["머신 켜기", "원두 소분"], shifts={1}),
            card(3, 30, ["머신 청소"], shifts={1, 2}),
        ]

    def build(self, **kw):
        base = dict(
            business_date=date(2026, 10, 7), previous_business_date=date(2026, 10, 6), previous_submitted=True,
            shifts=self.shifts, cards=self.cards, scope=Scope(True, (1, 2)), checked={(20, 1)},
            selected_shift_id=1, upcoming=False, include_all=False, submissions=[], my_submission=None,
        )
        base.update(kw)
        return build_today(**base)

    def test_groups_common_then_selected_shift(self):
        today = self.build()
        self.assertEqual([g["name"] for g in today["groups"]], ["공통", "오픈"])
        self.assertEqual(today["view"], {"total": 4, "done": 1})

    def test_scope_counts_unique_lines(self):
        today = self.build()
        self.assertEqual(today["scope_counts"], {"total": 4, "done": 1})

    def test_include_all_lists_every_scope_shift(self):
        today = self.build(include_all=True)
        self.assertEqual([g["name"] for g in today["groups"]], ["공통", "오픈", "마감"])

    def test_all_scope_submission_does_not_tick_shifts(self):
        today = self.build(submissions=[{"scope_shift_ids": None}])
        self.assertFalse(any(s["submitted"] for s in today["shifts"]))

    def test_shift_submitted_only_for_covered_shift(self):
        today = self.build(submissions=[{"scope_shift_ids": [2]}])
        self.assertEqual({s["shift_id"]: s["submitted"] for s in today["shifts"]}, {1: False, 2: True})

    def test_no_shifts_store_shows_common_only(self):
        today = self.build(shifts=[], cards=[self.cards[0]], scope=Scope(True, ()), selected_shift_id=None)
        self.assertEqual([g["name"] for g in today["groups"]], ["공통"])
        self.assertIsNone(today["current_shift_id"])

    def test_selected_shift_outside_scope_is_ignored(self):
        today = self.build(scope=Scope(False, (1,)), selected_shift_id=2)
        self.assertEqual([g["name"] for g in today["groups"]], ["공통"])
        self.assertIsNone(today["current_shift_id"])


class SchemaAndAuthTest(unittest.TestCase):
    def test_shift_name_trimmed_and_required(self):
        self.assertEqual(ShiftCreate(name="  미들조 ").name, "미들조")
        with self.assertRaises(ValidationError):
            ShiftCreate(name="   ")

    def test_shift_times_both_or_neither(self):
        with self.assertRaises(ValidationError):
            ShiftCreate(name="오픈", starts_at=time(7))
        self.assertEqual(ShiftCreate(name="마감", starts_at=time(22), ends_at=time(1)).ends_at, time(1))

    def test_shift_update_clear_time(self):
        update = ShiftUpdate(clear_time=True)
        self.assertTrue(update.clear_time)

    def test_timezone_aware_time_is_rejected(self):
        aware = time(7, tzinfo=timezone.utc)
        with self.assertRaises(ValidationError):
            ShiftCreate(name="오픈", starts_at=aware, ends_at=time(11))
        with self.assertRaises(ValidationError):
            ShiftUpdate(starts_at=time(7), ends_at=aware)
        with self.assertRaises(ValidationError):
            Settings(business_day_starts_at=aware)

    def test_equal_start_and_end_is_rejected(self):
        with self.assertRaises(ValidationError):
            ShiftCreate(name="오픈", starts_at=time(7), ends_at=time(7))
        with self.assertRaises(ValidationError):
            ShiftUpdate(starts_at=time(7), ends_at=time(7))

    def test_clear_time_with_times_is_rejected(self):
        with self.assertRaises(ValidationError):
            ShiftUpdate(clear_time=True, starts_at=time(7), ends_at=time(11))

    def test_ids_are_bounded(self):
        big = 9223372036854775808
        for build in (
            lambda v: IdList(ids=[v]),
            lambda v: ShiftOrder(shift_ids=[v]),
            lambda v: CardLinks(checklist=True, shift_ids=[v]),
            lambda v: CheckItem(card_version_id=v, line_no=1, checked=True),
        ):
            for bad in (0, -1, big):
                with self.assertRaises(ValidationError):
                    build(bad)
            build(9223372036854775807)

    def test_staff_is_not_owner(self):
        member = Member(store_id=1, user_id=2, member_id=3, role="STAFF", personal=True,
                        timezone="Asia/Seoul", day_starts_at=time(4), staff_records_visible=True)
        with self.assertRaises(ApiError) as raised:
            require_owner_member(member)
        self.assertEqual(raised.exception.code, "OWNER_ONLY")


class DatePolicyTest(unittest.TestCase):
    TODAY = date(2026, 10, 7)

    def test_today_is_not_late(self):
        self.assertFalse(date_policy(self.TODAY, self.TODAY, True, allow_late=True))

    def test_yesterday_unsubmitted_late_allowed(self):
        self.assertTrue(date_policy(self.TODAY, self.TODAY - timedelta(days=1), False, allow_late=True))

    def test_yesterday_on_plain_check_is_conflict(self):
        with self.assertRaises(ApiError) as raised:
            date_policy(self.TODAY, self.TODAY - timedelta(days=1), False, allow_late=False)
        self.assertEqual(raised.exception.code, "BUSINESS_DATE_CHANGED")
        self.assertEqual(raised.exception.details, {"current_business_date": "2026-10-07", "previous_unsubmitted": True})

    def test_yesterday_already_submitted_is_conflict(self):
        with self.assertRaises(ApiError) as raised:
            date_policy(self.TODAY, self.TODAY - timedelta(days=1), True, allow_late=True)
        self.assertFalse(raised.exception.details["previous_unsubmitted"])

    def test_two_days_ago_is_conflict(self):
        with self.assertRaises(ApiError):
            date_policy(self.TODAY, self.TODAY - timedelta(days=2), False, allow_late=True)


class _FakeDb:
    """apply_checks 가 줄마다 한 문장(fetchval)으로 바꾸므로, 저장 상태에 따라 바뀐 줄이면 1·아니면 None 을 돌려준다."""

    def __init__(self, stored):
        self.stored, self.executed, self.statements = stored, [], 0

    async def fetchval(self, sql, store_id, business_date, version_id, line_no, *rest):
        self.statements += 1
        checked = rest[0]
        current = self.stored.get((version_id, line_no))
        changed = (current is not True) if checked else (current is True)
        if changed:
            self.stored[(version_id, line_no)] = checked
        return 1 if changed else None

    async def execute(self, sql, *args):
        self.executed.append(sql)


class ApplyChecksTest(unittest.IsolatedAsyncioTestCase):
    D = date(2026, 10, 7)

    async def test_same_value_is_skipped(self):
        db = _FakeDb({(1, 1): True})
        await repo.apply_checks(db, 1, self.D, 5, [(1, 1, True)], late=True, personal=True)
        self.assertEqual(db.executed, [])

    async def test_new_unchecked_line_is_skipped(self):
        db = _FakeDb({})
        await repo.apply_checks(db, 1, self.D, 5, [(1, 2, False)], late=False, personal=True)
        self.assertEqual(db.executed, [])
        self.assertNotIn((1, 2), db.stored)

    async def test_change_records_upsert_and_event_when_personal(self):
        db = _FakeDb({(1, 1): True})
        await repo.apply_checks(db, 1, self.D, 5, [(1, 1, False)], late=False, personal=True)
        self.assertEqual(db.statements, 1)
        self.assertEqual(len(db.executed), 1)
        self.assertIn("checklist_check_events", db.executed[0])

    async def test_change_without_personal_has_no_event(self):
        db = _FakeDb({})
        await repo.apply_checks(db, 1, self.D, 5, [(1, 1, True)], late=False, personal=False)
        self.assertEqual(db.statements, 1)
        self.assertEqual(db.executed, [])


class RecordsAccessTest(unittest.TestCase):
    def member(self, role, user_id=1, visible=True):
        return Member(store_id=1, user_id=user_id, member_id=user_id, role=role, personal=True,
                      timezone="Asia/Seoul", day_starts_at=time(4), staff_records_visible=visible)

    def test_self_always_visible(self):
        self.assertTrue(records_access(self.member("STAFF", 5), 5, "STAFF"))

    def test_staff_cannot_read_others(self):
        with self.assertRaises(ApiError) as raised:
            records_access(self.member("STAFF", 5), 6, "STAFF")
        self.assertEqual(raised.exception.status_code, 403)

    def test_owner_reads_staff_when_visible(self):
        self.assertTrue(records_access(self.member("OWNER", 1, visible=True), 6, "STAFF"))

    def test_owner_hidden_when_staff_records_off(self):
        self.assertFalse(records_access(self.member("OWNER", 1, visible=False), 6, "STAFF"))

    def test_unknown_user_is_not_found(self):
        with self.assertRaises(ApiError) as raised:
            records_access(self.member("OWNER", 1), 99, None)
        self.assertEqual(raised.exception.status_code, 404)

    def test_staff_unknown_user_is_forbidden_not_not_found(self):
        with self.assertRaises(ApiError) as raised:
            records_access(self.member("STAFF", 5), 99, None)
        self.assertEqual(raised.exception.status_code, 403)


class MonthRangeTest(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(month_range("2026-02"), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(month_range("2024-02")[1], date(2024, 2, 29))
        self.assertEqual(month_range("2026-12")[1], date(2026, 12, 31))

    def test_invalid_month_is_422(self):
        for bad in ("2026-13", "2026-00"):
            with self.assertRaises(ApiError) as raised:
                month_range(bad)
            self.assertEqual(raised.exception.status_code, 422)
