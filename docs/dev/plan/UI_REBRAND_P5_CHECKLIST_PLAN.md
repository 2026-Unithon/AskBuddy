# P5 근무조 체크리스트 백엔드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 근무조·체크리스트·제출·개인 기록 API(`/checklist/*`)와 migration 을 만들어, 프론트(P5 화면)가 붙을 수 있는 백엔드를 완성한다.

**Architecture:** 새 모듈 `api/app/checklist/` 하나에 순수 계산(`calendar.py`·`scope.py`), DB 접근(`repository.py`), 스키마(`schemas.py`), 라우트(`router.py`)를 나눈다. 영업일·범위·묶음 계산은 DB 없이 단위 테스트하고, DB·권한·격리는 일회용 DB 재구축 검증(`verify_checklist.py`)에서 라우트 함수를 직접 불러 확인한다.

**Tech Stack:** FastAPI · Python 3.12 · asyncpg · pydantic v2 · PostgreSQL 15/17(pgvector 이미지) · unittest

**Spec:** [UI_REBRAND_P5_CHECKLIST.md](UI_REBRAND_P5_CHECKLIST.md) (설계 확정 3차). 결정 번호 C1~C9 는 그 문서를 가리킨다.

## Global Constraints

- RLS 없음(D1). 모든 DB 함수는 `store_id` 를 필수 인자로 받는다. 기본값·`Optional` 금지. `WHERE store_id = $1` 없는 조회 금지
- `store_id`·`user_id` 는 JWT(`ApiClaims`)에서만. 요청 본문·URL 의 store id 를 받지 않는다
- 매장 구성원 확인은 요청마다 `store_members(store_id, user_id)` 를 다시 읽는다. 없거나 역할이 JWT `role` 과 다르면 403
- 오류는 `app.errors.ApiError(status, CODE, 한국어 메시지)` 로 던진다. 다른 매장 대상은 404, 점주 전용 경로의 직원은 403 `OWNER_ONLY`
- 시간은 `TIMESTAMPTZ`·`time`. 영업일 계산은 서버만 한다
- 체크리스트에는 `review_status='APPROVED'` 이고 `published_version_id` 가 있는 카드만 (불변식 11)
- 주석은 한국어. 상태 문자열은 대문자 상수
- migration 은 새 파일만. 버전 `20261006090000` (`20261005110000` 뒤, `test_migration_versions.py` 로 중복 확인)
- 커밋은 사용자 요청 시에만. 이 계획의 커밋 단계는 **"변경 파일 목록 확인"으로 대신한다**(메모리: 커밋·푸시는 사용자가)

## Review Focus

- **카드를 마지막 근무조에서 빼면 공통이 돼 버리는 문제** — 근무조 "할 일 담기"에서 카드를 빼서 그 카드에 근무조가 하나도 안 남으면 체크리스트에서 빠져야 한다(공통으로 바뀌면 안 된다, C9). Task 3 의 `verify` 에 고정
- **보관한 근무조에만 연결된 카드** — 근무조를 지우면(보관) 그 근무조에만 있던 카드는 어떤 범위에도 나오지 않아야 한다(공통 아님). Task 2 `cards_in_scope` 테스트 + Task 6 검증
- **영업일 경계 직전에 연 화면의 체크** — 04:00 직후 어제 날짜로 온 `PUT /checks` 는 저장하지 않고 409, 어제 미제출이면 `previous_unsubmitted=true`. Task 4 `date_policy` 테스트
- **내 기록 끈 사람의 체크** — 매장 체크는 바뀌되 이벤트·`updated_by` 가 남지 않아야 한다(C7-1). Task 6 검증
- **같은 카드가 범위 안 두 근무조에 있을 때 개수** — 제출 total 은 줄을 한 번만 센다. Task 2 테스트

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `supabase/migrations/20261006090000_checklist.sql` | 컬럼 3개 + 테이블 7개 |
| `api/app/checklist/__init__.py` | 빈 파일 |
| `api/app/checklist/calendar.py` | 영업일·지금 근무조·본문 줄 나누기 (순수) |
| `api/app/checklist/scope.py` | 범위 계산·묶음·개수·오늘 응답 조립 (순수) |
| `api/app/checklist/schemas.py` | 요청 본문 모델 |
| `api/app/checklist/repository.py` | 모든 SQL (store_id 필수) |
| `api/app/checklist/router.py` | `/checklist/*` 라우트, 구성원 확인, 날짜 정책 |
| `api/app/main.py` | 라우터 등록 1줄 |
| `api/app/errors.py` | 검증 오류 envelope 대상에 `/checklist` 추가 1줄 |
| `api/tests/test_checklist_logic.py` | calendar·scope·date_policy·스키마 단위 테스트 |
| `api/scripts/verify_checklist.py` | 일회용 DB 에서 라우트 함수 직접 호출 검증 |
| `api/scripts/verify_r_schema_rebuild.py` | `verify_checklist` 호출 추가 |
| `.claude/skills/store-isolation-check/check_store_id.py` | `TENANT_TABLES` 에 새 테이블 7개 |

---

### Task 1: Migration 과 격리 검사기 갱신

**Files:**
- Create: `supabase/migrations/20261006090000_checklist.sql`
- Modify: `.claude/skills/store-isolation-check/check_store_id.py` (`TENANT_TABLES`)
- Test: `api/tests/test_migration_versions.py` (기존, 중복 버전 검사)

**Interfaces:**
- Produces: 테이블 `store_shifts`, `checklist_cards`, `checklist_card_shifts`, `member_shifts`, `checklist_checks`, `checklist_check_events`, `checklist_submissions`; 컬럼 `stores.timezone`, `stores.business_day_starts_at`, `stores.staff_records_visible`, `store_members.personal_records_enabled`

- [ ] **Step 1: migration 작성**

```sql
-- P5 근무조 체크리스트 (docs/dev/plan/UI_REBRAND_P5_CHECKLIST.md)
-- 체크 항목은 승인 카드 공개 버전 본문의 한 줄이다. 매장 격리는 API 가 책임진다(D1).

-- 매장 설정: 시간대·영업일 시작 시각(C5)·점주가 알바생 기록을 보는지(C7-2)
alter table stores
  add column if not exists timezone varchar(40) not null default 'Asia/Seoul',
  add column if not exists business_day_starts_at time not null default '04:00',
  add column if not exists staff_records_visible boolean not null default true;

-- 구성원 각자 "내 기록 남기기"(C7-1)
alter table store_members
  add column if not exists personal_records_enabled boolean not null default true;

-- 근무조(C1). 지우면 보관해 과거 기록을 남긴다. ends_at <= starts_at 이면 자정을 넘는다
create table if not exists store_shifts (
  shift_id    bigint generated always as identity primary key,
  store_id    bigint not null references stores(store_id) on delete cascade,
  name        varchar(30) not null check (length(btrim(name)) > 0),
  starts_at   time,
  ends_at     time,
  sort_order  int not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  archived_at timestamptz,
  unique (store_id, shift_id),
  check ((starts_at is null) = (ends_at is null))
);
create unique index if not exists store_shifts_active_name
  on store_shifts (store_id, lower(name)) where archived_at is null;

-- 체크리스트 카드(C2·C9). 근무조 행이 없으면 "공통" 단위다
create table if not exists checklist_cards (
  store_id   bigint not null references stores(store_id) on delete cascade,
  card_id    bigint not null,
  created_at timestamptz not null default now(),
  primary key (store_id, card_id),
  foreign key (store_id, card_id) references knowledge_cards (store_id, card_id) on delete cascade
);

create table if not exists checklist_card_shifts (
  store_id bigint not null references stores(store_id) on delete cascade,
  card_id  bigint not null,
  shift_id bigint not null,
  primary key (store_id, card_id, shift_id),
  foreign key (store_id, card_id) references checklist_cards (store_id, card_id) on delete cascade,
  foreign key (store_id, shift_id) references store_shifts (store_id, shift_id) on delete cascade
);

-- 직원 담당 근무조(C3). 행이 없으면 전체 범위
create table if not exists member_shifts (
  store_id  bigint not null references stores(store_id) on delete cascade,
  member_id bigint not null references store_members(member_id) on delete cascade,
  shift_id  bigint not null,
  primary key (store_id, member_id, shift_id),
  foreign key (store_id, shift_id) references store_shifts (store_id, shift_id) on delete cascade
);

-- 줄 체크 현재 상태(매장 단위 하나). 해제도 행을 지우지 않는다
create table if not exists checklist_checks (
  store_id        bigint not null references stores(store_id) on delete cascade,
  business_date   date not null,
  card_version_id bigint not null,
  line_no         int not null check (line_no >= 1),
  checked         boolean not null,
  updated_by      bigint references users(user_id) on delete set null,
  updated_at      timestamptz not null default now(),
  primary key (store_id, business_date, card_version_id, line_no)
);

-- 체크 이벤트(개인 기록 근거, C7). 내 기록 남기기가 꺼진 사람은 만들지 않는다(C7-1)
create table if not exists checklist_check_events (
  event_id        bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  business_date   date not null,
  card_version_id bigint not null,
  line_no         int not null check (line_no >= 1),
  checked         boolean not null,
  user_id         bigint not null references users(user_id) on delete cascade,
  late            boolean not null default false,
  created_at      timestamptz not null default now()
);
create index if not exists checklist_check_events_user_day
  on checklist_check_events (store_id, user_id, business_date);

-- 제출(C4). 그때 범위·개수를 고정한다. 사람·영업일당 하나.
-- 내 기록 남기기가 꺼져 있어도 운영(점주 현황·어제 창 판정)을 위해 남기되 personal=false
create table if not exists checklist_submissions (
  store_id        bigint not null references stores(store_id) on delete cascade,
  business_date   date not null,
  user_id         bigint not null references users(user_id) on delete cascade,
  scope_shift_ids bigint[],
  total_lines     int not null check (total_lines >= 0),
  done_lines      int not null check (done_lines >= 0 and done_lines <= total_lines),
  late            boolean not null default false,
  personal        boolean not null default true,
  submitted_at    timestamptz not null default now(),
  primary key (store_id, business_date, user_id)
);
```

- [ ] **Step 2: 격리 검사기 갱신** — `.claude/skills/store-isolation-check/check_store_id.py` 의 `TENANT_TABLES` 집합에 아래 7개를 더한다.

```python
    "store_shifts", "checklist_cards", "checklist_card_shifts", "member_shifts",
    "checklist_checks", "checklist_check_events", "checklist_submissions",
```

- [ ] **Step 3: 버전 중복 검사**

Run: `cd api && python -m pytest tests/test_migration_versions.py -q`
Expected: `1 passed`

- [ ] **Step 4: 로컬 개발 DB 에 적용**

Run: `supabase migration up --local` (worktree 루트에서)
Expected: `Applying migration 20261006090000_checklist.sql...` 오류 없음. (이 DB 는 원래 폴더 백엔드 작업과 공유한다 — 추가형이라 영향 없음)

- [ ] **Step 5: 변경 파일 확인** — `git status --short` 에 위 2개 파일만

---

### Task 2: 순수 계산 — 영업일·지금 근무조·줄·범위·오늘 응답

**Files:**
- Create: `api/app/checklist/__init__.py`, `api/app/checklist/calendar.py`, `api/app/checklist/scope.py`
- Test: `api/tests/test_checklist_logic.py`

**Interfaces:**
- Produces:
  - `calendar.business_date(now_utc: datetime, tz: str, day_starts_at: time) -> date`
  - `calendar.local_time(now_utc: datetime, tz: str) -> time`
  - `calendar.split_lines(content: str) -> list[str]`
  - `calendar.ShiftWindow(shift_id: int, sort_order: int, starts_at: time | None, ends_at: time | None)`
  - `calendar.pick_current_shift(shifts: list[ShiftWindow], now: time, day_starts_at: time) -> tuple[int | None, bool]` (shift_id, upcoming)
  - `scope.Shift(shift_id, name, sort_order, starts_at, ends_at)`
  - `scope.ChecklistCard(card_id, card_version_id, title, lines: tuple[str, ...], common: bool, shift_ids: frozenset[int])`
  - `scope.Scope(all: bool, shift_ids: tuple[int, ...])`
  - `scope.resolve_scope(role: str, active_shift_ids: list[int], member_shift_ids: set[int]) -> Scope`
  - `scope.cards_in_scope(cards: list[ChecklistCard], scope: Scope) -> list[ChecklistCard]`
  - `scope.line_keys(cards: list[ChecklistCard]) -> set[tuple[int, int]]`
  - `scope.build_today(*, business_date, previous_business_date, previous_submitted, shifts, cards, scope, checked, selected_shift_id, upcoming, include_all, submissions, my_submission) -> dict`
  - `scope.COMMON_NAME = "공통"`

- [ ] **Step 1: 실패하는 테스트 작성** — `api/tests/test_checklist_logic.py`

```python
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone

from app.checklist.calendar import ShiftWindow, business_date, pick_current_shift, split_lines
from app.checklist.scope import ChecklistCard, Scope, Shift, build_today, cards_in_scope, line_keys, resolve_scope

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

    def test_shift_submitted_when_all_scope_submission_exists(self):
        today = self.build(submissions=[{"scope_shift_ids": None}])
        self.assertTrue(all(s["submitted"] for s in today["shifts"]))

    def test_shift_submitted_only_for_covered_shift(self):
        today = self.build(submissions=[{"scope_shift_ids": [2]}])
        self.assertEqual({s["shift_id"]: s["submitted"] for s in today["shifts"]}, {1: False, 2: True})

    def test_no_shifts_store_shows_common_only(self):
        today = self.build(shifts=[], cards=[self.cards[0]], scope=Scope(True, ()), selected_shift_id=None)
        self.assertEqual([g["name"] for g in today["groups"]], ["공통"])
        self.assertIsNone(today["current_shift_id"])
```

- [ ] **Step 2: 실패 확인**

Run: `cd api && python -m pytest tests/test_checklist_logic.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.checklist'`

- [ ] **Step 3: `api/app/checklist/__init__.py`** — 빈 파일

- [ ] **Step 4: `api/app/checklist/calendar.py`**

```python
"""영업일·지금 근무조·본문 줄 — DB 없이 계산한다 (설계 §5)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_DAY = 24 * 60


def business_date(now_utc: datetime, tz: str, day_starts_at: time) -> date:
    """영업일 시작 시각 이전 새벽은 전날 영업일이다 (C5)."""
    local = now_utc.astimezone(ZoneInfo(tz))
    return (local - timedelta(hours=day_starts_at.hour, minutes=day_starts_at.minute)).date()


def local_time(now_utc: datetime, tz: str) -> time:
    return now_utc.astimezone(ZoneInfo(tz)).time().replace(second=0, microsecond=0)


def split_lines(content: str) -> list[str]:
    """체크 항목 = 공개 본문의 한 줄. 빈 줄은 뺀다 (C8, 웹 NumberedContent 와 같은 규칙)."""
    return [line.strip() for line in content.split("\n") if line.strip()]


@dataclass(frozen=True)
class ShiftWindow:
    shift_id: int
    sort_order: int
    starts_at: time | None
    ends_at: time | None


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _covers(shift: ShiftWindow, now: time) -> bool:
    if shift.starts_at is None or shift.ends_at is None:
        return False
    start, end, t = _minutes(shift.starts_at), _minutes(shift.ends_at), _minutes(now)
    if start < end:
        return start <= t < end
    # 자정을 넘는 근무조 (ends_at <= starts_at)
    return t >= start or t < end


def pick_current_shift(shifts: list[ShiftWindow], now: time, day_starts_at: time) -> tuple[int | None, bool]:
    """지금 근무조. 맞는 게 없으면 오늘(영업일) 남은 가장 빠른 근무조를 upcoming 으로, 그것도 없으면 첫 근무조."""
    if not shifts:
        return None, False
    ordered = sorted(shifts, key=lambda s: (s.sort_order, s.shift_id))
    for shift in ordered:
        if _covers(shift, now):
            return shift.shift_id, False

    day_start = _minutes(day_starts_at)

    def position(value: time) -> int:
        # 영업일 시작부터 몇 분 지났는지
        return (_minutes(value) - day_start) % _DAY

    later = [s for s in ordered if s.starts_at is not None and position(s.starts_at) > position(now)]
    if later:
        nearest = min(later, key=lambda s: (position(s.starts_at), s.sort_order))  # type: ignore[arg-type]
        return nearest.shift_id, True
    return ordered[0].shift_id, False
```

- [ ] **Step 5: `api/app/checklist/scope.py`**

```python
"""범위·묶음·개수 계산과 오늘 응답 조립 (설계 §5·§6). DB 를 모른다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any

COMMON_NAME = "공통"


@dataclass(frozen=True)
class Shift:
    shift_id: int
    name: str
    sort_order: int
    starts_at: time | None
    ends_at: time | None


@dataclass(frozen=True)
class ChecklistCard:
    card_id: int
    card_version_id: int
    title: str
    lines: tuple[str, ...]
    common: bool                 # 근무조 연결이 하나도 없으면 공통 단위 (C9)
    shift_ids: frozenset[int]    # 활성 근무조만. 보관 근무조 연결은 빠져 있다


@dataclass(frozen=True)
class Scope:
    all: bool
    shift_ids: tuple[int, ...]   # 범위 안 근무조(활성, 정렬 순서)


def resolve_scope(role: str, active_shift_ids: list[int], member_shift_ids: set[int]) -> Scope:
    """점주·근무조 없는 매장·담당 없는 직원은 전체. 아니면 담당 근무조만 (C3)."""
    assigned = tuple(s for s in active_shift_ids if s in member_shift_ids)
    if role == "OWNER" or not active_shift_ids or not assigned:
        return Scope(True, tuple(active_shift_ids))
    return Scope(False, assigned)


def cards_in_scope(cards: list[ChecklistCard], scope: Scope) -> list[ChecklistCard]:
    allowed = set(scope.shift_ids)
    return [c for c in cards if c.common or (c.shift_ids & allowed)]


def line_keys(cards: list[ChecklistCard]) -> set[tuple[int, int]]:
    """한 카드가 여러 근무조에 있어도 줄은 한 번만 센다."""
    return {(c.card_version_id, n) for c in cards for n in range(1, len(c.lines) + 1)}


def _card_view(card: ChecklistCard, checked: set[tuple[int, int]]) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "card_version_id": card.card_version_id,
        "title": card.title,
        "lines": [
            {"line_no": n, "text": text, "checked": (card.card_version_id, n) in checked}
            for n, text in enumerate(card.lines, start=1)
        ],
    }


def _counts(cards: list[ChecklistCard], checked: set[tuple[int, int]]) -> dict[str, int]:
    keys = line_keys(cards)
    return {"total": len(keys), "done": len(keys & checked)}


def _covers(submission: dict[str, Any], shift_id: int) -> bool:
    ids = submission.get("scope_shift_ids")
    return ids is None or shift_id in ids


def build_today(
    *,
    business_date: date,
    previous_business_date: date,
    previous_submitted: bool,
    shifts: list[Shift],
    cards: list[ChecklistCard],
    scope: Scope,
    checked: set[tuple[int, int]],
    selected_shift_id: int | None,
    upcoming: bool,
    include_all: bool,
    submissions: list[dict[str, Any]],
    my_submission: dict[str, Any] | None,
) -> dict[str, Any]:
    """오늘 할 일 응답. 공통 묶음을 항상 맨 앞에, 그 뒤에 고른 근무조(또는 어제 창이면 범위 전체)."""
    by_id = {s.shift_id: s for s in shifts}
    scoped = cards_in_scope(cards, scope)
    common = [c for c in scoped if c.common]

    shift_rows = []
    for shift_id in scope.shift_ids:
        shift = by_id[shift_id]
        own = [c for c in scoped if shift_id in c.shift_ids]
        shift_rows.append({
            "shift_id": shift_id,
            "name": shift.name,
            "starts_at": shift.starts_at.isoformat(timespec="minutes") if shift.starts_at else None,
            "ends_at": shift.ends_at.isoformat(timespec="minutes") if shift.ends_at else None,
            **_counts(own, checked),
            "submitted": any(_covers(s, shift_id) for s in submissions),
        })

    groups: list[dict[str, Any]] = []
    if common:
        groups.append({"shift_id": None, "name": COMMON_NAME, "cards": [_card_view(c, checked) for c in common]})
    visible_shift_ids = list(scope.shift_ids) if include_all else ([selected_shift_id] if selected_shift_id in by_id else [])
    view_cards = list(common)
    for shift_id in visible_shift_ids:
        own = [c for c in scoped if shift_id in c.shift_ids]
        if own:
            groups.append({"shift_id": shift_id, "name": by_id[shift_id].name, "cards": [_card_view(c, checked) for c in own]})
        view_cards.extend(own)

    return {
        "business_date": business_date.isoformat(),
        "previous_business_date": previous_business_date.isoformat(),
        "previous_submitted": previous_submitted,
        "scope": {"all": scope.all, "shift_ids": list(scope.shift_ids)},
        "current_shift_id": selected_shift_id,
        "upcoming": upcoming,
        "shifts": shift_rows,
        "groups": groups,
        "view": _counts(view_cards, checked),
        "scope_counts": _counts(scoped, checked),
        "my_submission": my_submission,
    }
```

- [ ] **Step 6: 통과 확인**

Run: `cd api && python -m pytest tests/test_checklist_logic.py -q`
Expected: 모든 테스트 PASS

- [ ] **Step 7: 변경 파일 확인** — `api/app/checklist/{__init__,calendar,scope}.py`, `api/tests/test_checklist_logic.py`

---

### Task 3: 구성원 확인·설정·근무조·연결 API (점주 관리)

**Files:**
- Create: `api/app/checklist/schemas.py`, `api/app/checklist/repository.py`, `api/app/checklist/router.py`
- Modify: `api/app/main.py` (라우터 등록), `api/app/errors.py` (검증 오류 envelope 경로)
- Test: `api/tests/test_checklist_logic.py` (스키마·권한 단위 테스트 추가)

**Interfaces:**
- Consumes: Task 1 테이블, Task 2 `Shift`, `ChecklistCard`, `split_lines`
- Produces (repository, 모두 첫 인자 `db`, 다음 `store_id: int` 필수):
  - `get_member(db, store_id, user_id) -> Record | None` (member_id, member_role, personal_records_enabled, timezone, business_day_starts_at, staff_records_visible)
  - `list_shifts(db, store_id) -> list[Shift]` (활성만, 정렬)
  - `create_shift(db, store_id, name, starts_at, ends_at) -> Shift`
  - `update_shift(db, store_id, shift_id, name, starts_at, ends_at, set_time: bool) -> Shift | None`
  - `archive_shift(db, store_id, shift_id) -> bool`
  - `reorder_shifts(db, store_id, shift_ids) -> bool`
  - `create_preset(db, store_id) -> list[Shift] | None`
  - `set_shift_cards(db, store_id, shift_id, card_ids) -> None`
  - `get_card_links(db, store_id, card_id) -> dict | None`
  - `set_card_links(db, store_id, card_id, checklist, shift_ids) -> None`
  - `card_exists(db, store_id, card_ids) -> bool`, `shifts_exist(db, store_id, shift_ids) -> bool`
  - `list_members(db, store_id) -> list[dict]`
  - `set_member_shifts(db, store_id, member_id, shift_ids) -> bool`
  - `update_settings(db, store_id, business_day_starts_at, staff_records_visible) -> None`
  - `set_personal_records(db, store_id, member_id, enabled) -> None`
- Produces (router): `Member` dataclass, `require_member(db, claims) -> Member`, `require_owner_member(member) -> None`, `router = APIRouter()`

- [ ] **Step 1: 실패하는 테스트 추가** — `api/tests/test_checklist_logic.py` 끝에

```python
from pydantic import ValidationError

from app.checklist.router import Member, require_owner_member
from app.checklist.schemas import ShiftCreate, ShiftUpdate
from app.errors import ApiError


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

    def test_staff_is_not_owner(self):
        member = Member(store_id=1, user_id=2, member_id=3, role="STAFF", personal=True,
                        timezone="Asia/Seoul", day_starts_at=time(4), staff_records_visible=True)
        with self.assertRaises(ApiError) as raised:
            require_owner_member(member)
        self.assertEqual(raised.exception.code, "OWNER_ONLY")
```

- [ ] **Step 2: 실패 확인** — Run: `cd api && python -m pytest tests/test_checklist_logic.py -q` · Expected: FAIL (`app.checklist.router` 없음)

- [ ] **Step 3: `api/app/checklist/schemas.py`**

```python
"""체크리스트 요청 본문. store_id 는 받지 않는다 (JWT 만)."""
from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field, field_validator, model_validator


class ShiftCreate(BaseModel):
    name: str = Field(max_length=30)
    starts_at: time | None = None
    ends_at: time | None = None

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("근무조 이름을 적어 주세요")
        return value

    @model_validator(mode="after")
    def _both_times(self):
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("시작·끝 시각은 함께 적어 주세요")
        return self


class ShiftUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    starts_at: time | None = None
    ends_at: time | None = None
    clear_time: bool = False   # 시간을 지우려면 true

    @field_validator("name")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("근무조 이름을 적어 주세요")
        return value

    @model_validator(mode="after")
    def _both_times(self):
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("시작·끝 시각은 함께 적어 주세요")
        return self


class ShiftOrder(BaseModel):
    shift_ids: list[int] = Field(min_length=1, max_length=50)


class IdList(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=500)


class CardLinks(BaseModel):
    checklist: bool
    shift_ids: list[int] = Field(default_factory=list, max_length=50)   # [] = 공통


class Settings(BaseModel):
    business_day_starts_at: time | None = None
    staff_records_visible: bool | None = None


class MySettings(BaseModel):
    personal_records_enabled: bool


class CheckItem(BaseModel):
    card_version_id: int = Field(gt=0)
    line_no: int = Field(ge=1)
    checked: bool


class CheckRequest(CheckItem):
    business_date: date


class SubmissionRequest(BaseModel):
    business_date: date
    checks: list[CheckItem] = Field(default_factory=list, max_length=1000)
```

- [ ] **Step 4: `api/app/checklist/repository.py` (관리 부분)**

```python
"""체크리스트 SQL. 모든 함수는 store_id 를 필수로 받고 모든 쿼리를 store_id 로 좁힌다 (D1)."""
from __future__ import annotations

from datetime import date, time
from typing import Any

import asyncpg

from app.checklist.calendar import split_lines
from app.checklist.scope import ChecklistCard, Shift

PRESET = (("오픈", time(7), time(11)), ("미들", time(14), time(18)), ("마감", time(18), time(23)))


def _shift(row) -> Shift:
    return Shift(int(row["shift_id"]), row["name"], int(row["sort_order"]), row["starts_at"], row["ends_at"])


async def get_member(db, store_id: int, user_id: int):
    return await db.fetchrow(
        """select m.member_id, m.member_role, m.personal_records_enabled,
                  s.timezone, s.business_day_starts_at, s.staff_records_visible
           from store_members m join stores s on s.store_id = m.store_id
           where m.store_id = $1 and m.user_id = $2""",
        store_id, user_id,
    )


async def list_shifts(db, store_id: int) -> list[Shift]:
    rows = await db.fetch(
        """select shift_id, name, sort_order, starts_at, ends_at from store_shifts
           where store_id = $1 and archived_at is null order by sort_order, shift_id""",
        store_id,
    )
    return [_shift(r) for r in rows]


async def shifts_exist(db, store_id: int, shift_ids: list[int]) -> bool:
    if not shift_ids:
        return True
    found = await db.fetchval(
        """select count(*) from store_shifts
           where store_id = $1 and shift_id = any($2::bigint[]) and archived_at is null""",
        store_id, list(set(shift_ids)),
    )
    return found == len(set(shift_ids))


async def card_exists(db, store_id: int, card_ids: list[int]) -> bool:
    if not card_ids:
        return True
    found = await db.fetchval(
        "select count(*) from knowledge_cards where store_id = $1 and card_id = any($2::bigint[])",
        store_id, list(set(card_ids)),
    )
    return found == len(set(card_ids))


async def create_shift(db, store_id: int, name: str, starts_at: time | None, ends_at: time | None) -> Shift:
    row = await db.fetchrow(
        """insert into store_shifts (store_id, name, starts_at, ends_at, sort_order)
           values ($1, $2, $3, $4,
             (select coalesce(max(sort_order), -1) + 1 from store_shifts where store_id = $1 and archived_at is null))
           returning shift_id, name, sort_order, starts_at, ends_at""",
        store_id, name, starts_at, ends_at,
    )
    return _shift(row)


async def update_shift(db, store_id: int, shift_id: int, name: str | None,
                       starts_at: time | None, ends_at: time | None, set_time: bool) -> Shift | None:
    row = await db.fetchrow(
        """update store_shifts set
             name = coalesce($3, name),
             starts_at = case when $6 then $4 else starts_at end,
             ends_at = case when $6 then $5 else ends_at end,
             updated_at = now()
           where store_id = $1 and shift_id = $2 and archived_at is null
           returning shift_id, name, sort_order, starts_at, ends_at""",
        store_id, shift_id, name, starts_at, ends_at, set_time,
    )
    return _shift(row) if row else None


async def archive_shift(db, store_id: int, shift_id: int) -> bool:
    result = await db.execute(
        """update store_shifts set archived_at = now(), updated_at = now()
           where store_id = $1 and shift_id = $2 and archived_at is null""",
        store_id, shift_id,
    )
    return result.endswith(" 1")


async def reorder_shifts(db, store_id: int, shift_ids: list[int]) -> bool:
    async with db.transaction():
        active = [s.shift_id for s in await list_shifts(db, store_id)]
        if sorted(active) != sorted(shift_ids) or len(set(shift_ids)) != len(shift_ids):
            return False
        for order, shift_id in enumerate(shift_ids):
            await db.execute(
                "update store_shifts set sort_order = $3, updated_at = now() where store_id = $1 and shift_id = $2",
                store_id, shift_id, order,
            )
    return True


async def create_preset(db, store_id: int) -> list[Shift] | None:
    """활성 근무조가 0개일 때만 오픈·미들·마감을 만든다. 이름·시간은 점주가 바로 고친다."""
    async with db.transaction():
        await db.execute("select 1 from stores where store_id = $1 for update", store_id)
        if await db.fetchval(
            "select count(*) from store_shifts where store_id = $1 and archived_at is null", store_id
        ):
            return None
        return [await create_shift(db, store_id, name, start, end) for name, start, end in PRESET]


async def _drop_orphans(db, store_id: int, card_ids: list[int]) -> None:
    """근무조에서 빠져 연결이 하나도 안 남은 카드는 체크리스트에서 뺀다 — 공통으로 바뀌면 안 된다 (C9)."""
    if not card_ids:
        return
    await db.execute(
        """delete from checklist_cards c
           where c.store_id = $1 and c.card_id = any($2::bigint[])
             and not exists (select 1 from checklist_card_shifts s
                             where s.store_id = c.store_id and s.card_id = c.card_id)""",
        store_id, card_ids,
    )


async def set_shift_cards(db, store_id: int, shift_id: int, card_ids: list[int]) -> None:
    async with db.transaction():
        before = [r["card_id"] for r in await db.fetch(
            "select card_id from checklist_card_shifts where store_id = $1 and shift_id = $2", store_id, shift_id)]
        for card_id in card_ids:
            await db.execute(
                "insert into checklist_cards (store_id, card_id) values ($1, $2) on conflict do nothing",
                store_id, card_id,
            )
            await db.execute(
                """insert into checklist_card_shifts (store_id, card_id, shift_id) values ($1, $2, $3)
                   on conflict do nothing""",
                store_id, card_id, shift_id,
            )
        await db.execute(
            """delete from checklist_card_shifts
               where store_id = $1 and shift_id = $2 and not (card_id = any($3::bigint[]))""",
            store_id, shift_id, card_ids,
        )
        await _drop_orphans(db, store_id, [c for c in before if c not in card_ids])


async def get_card_links(db, store_id: int, card_id: int) -> dict[str, Any] | None:
    if not await card_exists(db, store_id, [card_id]):
        return None
    linked = await db.fetchval(
        "select exists(select 1 from checklist_cards where store_id = $1 and card_id = $2)", store_id, card_id)
    rows = await db.fetch(
        """select cs.shift_id from checklist_card_shifts cs
           join store_shifts s on s.store_id = cs.store_id and s.shift_id = cs.shift_id and s.archived_at is null
           where cs.store_id = $1 and cs.card_id = $2 order by s.sort_order, s.shift_id""",
        store_id, card_id,
    )
    return {"card_id": card_id, "checklist": bool(linked), "shift_ids": [int(r["shift_id"]) for r in rows]}


async def set_card_links(db, store_id: int, card_id: int, checklist: bool, shift_ids: list[int]) -> None:
    async with db.transaction():
        if not checklist:
            await db.execute("delete from checklist_cards where store_id = $1 and card_id = $2", store_id, card_id)
            return
        await db.execute(
            "insert into checklist_cards (store_id, card_id) values ($1, $2) on conflict do nothing", store_id, card_id)
        await db.execute(
            """delete from checklist_card_shifts
               where store_id = $1 and card_id = $2 and not (shift_id = any($3::bigint[]))""",
            store_id, card_id, shift_ids,
        )
        for shift_id in shift_ids:
            await db.execute(
                """insert into checklist_card_shifts (store_id, card_id, shift_id) values ($1, $2, $3)
                   on conflict do nothing""",
                store_id, card_id, shift_id,
            )


async def list_members(db, store_id: int) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """select m.member_id, m.user_id, u.name, m.member_role,
                  coalesce(array_agg(ms.shift_id order by s.sort_order)
                           filter (where s.shift_id is not null), '{}') as shift_ids
           from store_members m
           join users u on u.user_id = m.user_id
           left join member_shifts ms on ms.store_id = m.store_id and ms.member_id = m.member_id
           left join store_shifts s on s.store_id = ms.store_id and s.shift_id = ms.shift_id and s.archived_at is null
           where m.store_id = $1
           group by m.member_id, m.user_id, u.name, m.member_role
           order by m.member_role desc, m.member_id""",
        store_id,
    )
    return [{"member_id": int(r["member_id"]), "user_id": int(r["user_id"]), "name": r["name"],
             "role": r["member_role"], "shift_ids": [int(x) for x in r["shift_ids"]]} for r in rows]


async def set_member_shifts(db, store_id: int, member_id: int, shift_ids: list[int]) -> bool:
    async with db.transaction():
        exists = await db.fetchval(
            "select exists(select 1 from store_members where store_id = $1 and member_id = $2)", store_id, member_id)
        if not exists:
            return False
        await db.execute("delete from member_shifts where store_id = $1 and member_id = $2", store_id, member_id)
        for shift_id in set(shift_ids):
            await db.execute(
                "insert into member_shifts (store_id, member_id, shift_id) values ($1, $2, $3)",
                store_id, member_id, shift_id,
            )
    return True


async def update_settings(db, store_id: int, business_day_starts_at: time | None,
                          staff_records_visible: bool | None) -> None:
    await db.execute(
        """update stores set
             business_day_starts_at = coalesce($2, business_day_starts_at),
             staff_records_visible = coalesce($3, staff_records_visible)
           where store_id = $1""",
        store_id, business_day_starts_at, staff_records_visible,
    )


async def set_personal_records(db, store_id: int, member_id: int, enabled: bool) -> None:
    await db.execute(
        "update store_members set personal_records_enabled = $3 where store_id = $1 and member_id = $2",
        store_id, member_id, enabled,
    )
```

- [ ] **Step 5: `api/app/checklist/router.py` (구성원 확인 + 관리 라우트)**

```python
"""/checklist — 근무조 체크리스트 (docs/dev/plan/UI_REBRAND_P5_CHECKLIST.md)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

import asyncpg
from fastapi import APIRouter, Response, status

from app.checklist import repository as repo
from app.checklist.schemas import CardLinks, IdList, MySettings, Settings, ShiftCreate, ShiftOrder, ShiftUpdate
from app.checklist.scope import Shift
from app.deps import Db
from app.errors import ApiClaims, ApiError

router = APIRouter()


@dataclass(frozen=True)
class Member:
    store_id: int
    user_id: int
    member_id: int
    role: str
    personal: bool
    timezone: str
    day_starts_at: time
    staff_records_visible: bool


# store-isolation-ok: store_id·user_id 를 JWT 에서 꺼내고 현재 멤버십을 다시 확인하는 경계
async def require_member(db, claims: dict[str, Any]) -> Member:
    store_id, user_id = claims.get("store_id"), claims.get("user_id")
    if store_id is None or user_id is None:
        raise ApiError(403, "STORE_REQUIRED", "먼저 매장에 연결해 주세요.")
    row = await repo.get_member(db, int(store_id), int(user_id))
    if row is None or row["member_role"] != claims.get("role"):
        raise ApiError(403, "MEMBERSHIP_REQUIRED", "이 매장에 접근할 수 없어요.")
    return Member(int(store_id), int(user_id), int(row["member_id"]), row["member_role"],
                  bool(row["personal_records_enabled"]), row["timezone"], row["business_day_starts_at"],
                  bool(row["staff_records_visible"]))


def require_owner_member(member: Member) -> None:
    if member.role != "OWNER":
        raise ApiError(403, "OWNER_ONLY", "사장님만 바꿀 수 있어요.")


def _shift_out(shift: Shift) -> dict[str, Any]:
    return {
        "shift_id": shift.shift_id, "name": shift.name, "sort_order": shift.sort_order,
        "starts_at": shift.starts_at.isoformat(timespec="minutes") if shift.starts_at else None,
        "ends_at": shift.ends_at.isoformat(timespec="minutes") if shift.ends_at else None,
    }


@router.get("/shifts")
async def list_shifts(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    return {"items": [_shift_out(s) for s in await repo.list_shifts(db, member.store_id)]}


@router.post("/shifts", status_code=status.HTTP_201_CREATED)
async def create_shift(body: ShiftCreate, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    try:
        shift = await repo.create_shift(db, member.store_id, body.name, body.starts_at, body.ends_at)
    except asyncpg.UniqueViolationError as exc:
        raise ApiError(409, "SHIFT_NAME_TAKEN", "같은 이름의 근무조가 있어요.") from exc
    return _shift_out(shift)


@router.patch("/shifts/{shift_id}")
async def update_shift(shift_id: int, body: ShiftUpdate, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    set_time = body.clear_time or body.starts_at is not None
    try:
        shift = await repo.update_shift(db, member.store_id, shift_id, body.name,
                                        None if body.clear_time else body.starts_at,
                                        None if body.clear_time else body.ends_at, set_time)
    except asyncpg.UniqueViolationError as exc:
        raise ApiError(409, "SHIFT_NAME_TAKEN", "같은 이름의 근무조가 있어요.") from exc
    if shift is None:
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    return _shift_out(shift)


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(shift_id: int, db: Db, claims: ApiClaims) -> Response:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.archive_shift(db, member.store_id, shift_id):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/shifts/order")
async def reorder_shifts(body: ShiftOrder, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.reorder_shifts(db, member.store_id, body.shift_ids):
        raise ApiError(409, "SHIFT_ORDER_STALE", "근무조가 바뀌었어요. 새로 불러온 뒤 다시 정렬해 주세요.")
    return {"items": [_shift_out(s) for s in await repo.list_shifts(db, member.store_id)]}


@router.post("/shifts/preset", status_code=status.HTTP_201_CREATED)
async def create_preset(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    shifts = await repo.create_preset(db, member.store_id)
    if shifts is None:
        raise ApiError(409, "SHIFTS_EXIST", "이미 근무조가 있어요.")
    return {"items": [_shift_out(s) for s in shifts]}


@router.put("/shifts/{shift_id}/cards")
async def set_shift_cards(shift_id: int, body: IdList, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.shifts_exist(db, member.store_id, [shift_id]):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    if not await repo.card_exists(db, member.store_id, body.ids):
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없어요.")
    await repo.set_shift_cards(db, member.store_id, shift_id, list(dict.fromkeys(body.ids)))
    return {"shift_id": shift_id, "card_ids": list(dict.fromkeys(body.ids))}


@router.get("/cards/{card_id}")
async def get_card_links(card_id: int, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    links = await repo.get_card_links(db, member.store_id, card_id)
    if links is None:
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없어요.")
    return links


@router.put("/cards/{card_id}")
async def set_card_links(card_id: int, body: CardLinks, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.card_exists(db, member.store_id, [card_id]):
        raise ApiError(404, "CARD_NOT_FOUND", "카드를 찾을 수 없어요.")
    if not await repo.shifts_exist(db, member.store_id, body.shift_ids):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    await repo.set_card_links(db, member.store_id, card_id, body.checklist, list(dict.fromkeys(body.shift_ids)))
    return await repo.get_card_links(db, member.store_id, card_id)  # type: ignore[return-value]


@router.get("/members")
async def list_members(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    return {"items": await repo.list_members(db, member.store_id)}


@router.put("/members/{member_id}/shifts")
async def set_member_shifts(member_id: int, body: IdList, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    if not await repo.shifts_exist(db, member.store_id, body.ids):
        raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
    if not await repo.set_member_shifts(db, member.store_id, member_id, body.ids):
        raise ApiError(404, "MEMBER_NOT_FOUND", "직원을 찾을 수 없어요.")
    return {"member_id": member_id, "shift_ids": sorted(set(body.ids))}


@router.patch("/settings")
async def update_settings(body: Settings, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    await repo.update_settings(db, member.store_id, body.business_day_starts_at, body.staff_records_visible)
    fresh = await require_member(db, claims)
    return {"business_day_starts_at": fresh.day_starts_at.isoformat(timespec="minutes"),
            "staff_records_visible": fresh.staff_records_visible, "timezone": fresh.timezone}


@router.patch("/me")
async def update_me(body: MySettings, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    await repo.set_personal_records(db, member.store_id, member.member_id, body.personal_records_enabled)
    return {"personal_records_enabled": body.personal_records_enabled}
```

> 경로 충돌 없음: `PUT /shifts/order` 와 같은 메서드·깊이의 `/shifts/{id}` 경로는 없다(`{id}` 는 PATCH·DELETE, `{id}/cards` 는 한 단계 더 깊다). 위 순서 그대로 둔다.

- [ ] **Step 6: 라우터 등록** — `api/app/main.py` 의 import 블록에 `from app.checklist.router import router as checklist_router`, `app.include_router(team_router, ...)` 다음 줄에

```python
app.include_router(checklist_router, prefix="/checklist", tags=["checklist"])
```

- [ ] **Step 7: 검증 오류 envelope 경로** — `api/app/errors.py` 의 `validation_error_handler` 안 `startswith((...))` 튜플에 `"/checklist",` 를 추가한다

- [ ] **Step 8: 통과 확인**

Run: `cd api && python -m pytest tests/test_checklist_logic.py -q && python -c "import app.main"`
Expected: 모든 테스트 PASS, import 오류 없음

- [ ] **Step 9: 격리 정적 검사**

Run: `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/checklist`
Expected: 위반 0건 (위반이 나오면 쿼리에 `store_id` 조건을 넣어 고친다. 면제 주석으로 덮지 않는다)

- [ ] **Step 10: 변경 파일 확인** — schemas/repository/router, main.py, errors.py, 테스트

---

### Task 4: 오늘 할 일·체크·제출 (날짜 정책·내 기록 설정 포함)

**Files:**
- Modify: `api/app/checklist/repository.py` (조회·체크·제출 함수 추가), `api/app/checklist/router.py` (라우트 3개 + `date_policy`)
- Test: `api/tests/test_checklist_logic.py` (`date_policy` 테스트)

**Interfaces:**
- Consumes: Task 2 `business_date`, `local_time`, `pick_current_shift`, `ShiftWindow`, `resolve_scope`, `cards_in_scope`, `line_keys`, `build_today`; Task 3 `require_member`, `Member`, repo 관리 함수
- Produces:
  - repo `load_cards(db, store_id) -> list[ChecklistCard]`
  - repo `member_shift_ids(db, store_id, member_id) -> set[int]`
  - repo `checked_keys(db, store_id, business_date, version_ids) -> set[tuple[int, int]]`
  - repo `apply_checks(db, store_id, business_date, user_id, items, *, late, personal) -> None`
  - repo `get_submission(db, store_id, business_date, user_id) -> dict | None`
  - repo `insert_submission(db, store_id, business_date, user_id, scope_shift_ids, total, done, *, late, personal) -> dict`
  - repo `submissions_on(db, store_id, business_date) -> list[dict]`
  - router `date_policy(today: date, requested: date, previous_submitted: bool, *, allow_late: bool) -> bool` (True = late)
  - router `today_view(db, member, *, now_utc, selected_shift_id, requested_date, include_all) -> dict`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from datetime import timedelta

from app.checklist.router import date_policy


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
```

- [ ] **Step 2: 실패 확인** — `cd api && python -m pytest tests/test_checklist_logic.py -q` · Expected: FAIL (`date_policy` 없음)

- [ ] **Step 3: repository 추가** (`repository.py` 끝)

```python
async def load_cards(db, store_id: int) -> list[ChecklistCard]:
    """승인·공개 버전이 있는 체크리스트 카드. 보관 근무조 연결은 빼고, 연결 행이 아예 없으면 공통 (C9)."""
    rows = await db.fetch(
        """select c.card_id, k.published_version_id as card_version_id, v.title, v.content,
                  bool_and(cs.shift_id is null) as common,
                  coalesce(array_agg(s.shift_id) filter (where s.shift_id is not null), '{}') as shift_ids
           from checklist_cards c
           join knowledge_cards k on k.store_id = c.store_id and k.card_id = c.card_id
           join card_versions v on v.store_id = k.store_id and v.version_id = k.published_version_id
           left join checklist_card_shifts cs on cs.store_id = c.store_id and cs.card_id = c.card_id
           left join store_shifts s on s.store_id = cs.store_id and s.shift_id = cs.shift_id and s.archived_at is null
           where c.store_id = $1 and k.review_status = 'APPROVED' and k.published_version_id is not null
           group by c.card_id, k.published_version_id, v.title, v.content, c.created_at
           order by c.created_at, c.card_id""",
        store_id,
    )
    cards = []
    for r in rows:
        lines = tuple(split_lines(r["content"]))
        if lines:
            cards.append(ChecklistCard(int(r["card_id"]), int(r["card_version_id"]), r["title"], lines,
                                       bool(r["common"]), frozenset(int(x) for x in r["shift_ids"])))
    return cards


async def member_shift_ids(db, store_id: int, member_id: int) -> set[int]:
    rows = await db.fetch("select shift_id from member_shifts where store_id = $1 and member_id = $2",
                          store_id, member_id)
    return {int(r["shift_id"]) for r in rows}


async def checked_keys(db, store_id: int, business_date: date, version_ids: list[int]) -> set[tuple[int, int]]:
    if not version_ids:
        return set()
    rows = await db.fetch(
        """select card_version_id, line_no from checklist_checks
           where store_id = $1 and business_date = $2 and checked and card_version_id = any($3::bigint[])""",
        store_id, business_date, version_ids,
    )
    return {(int(r["card_version_id"]), int(r["line_no"])) for r in rows}


async def apply_checks(db, store_id: int, business_date: date, user_id: int,
                       items: list[tuple[int, int, bool]], *, late: bool, personal: bool) -> None:
    """매장 체크 상태를 바꾼다. 내 기록 남기기가 꺼져 있으면 사람 흔적(updated_by·이벤트)을 남기지 않는다 (C7-1)."""
    actor = user_id if personal else None
    for version_id, line_no, checked in items:
        await db.execute(
            """insert into checklist_checks (store_id, business_date, card_version_id, line_no, checked, updated_by)
               values ($1, $2, $3, $4, $5, $6)
               on conflict (store_id, business_date, card_version_id, line_no)
               do update set checked = excluded.checked, updated_by = excluded.updated_by, updated_at = now()""",
            store_id, business_date, version_id, line_no, checked, actor,
        )
        if personal:
            await db.execute(
                """insert into checklist_check_events
                     (store_id, business_date, card_version_id, line_no, checked, user_id, late)
                   values ($1, $2, $3, $4, $5, $6, $7)""",
                store_id, business_date, version_id, line_no, checked, user_id, late,
            )


def _submission(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "user_id": int(row["user_id"]),
        "scope_shift_ids": None if row["scope_shift_ids"] is None else [int(x) for x in row["scope_shift_ids"]],
        "total_lines": int(row["total_lines"]), "done_lines": int(row["done_lines"]),
        "late": bool(row["late"]), "submitted_at": row["submitted_at"].isoformat(),
    }


async def get_submission(db, store_id: int, business_date: date, user_id: int) -> dict[str, Any] | None:
    return _submission(await db.fetchrow(
        """select user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at from checklist_submissions
           where store_id = $1 and business_date = $2 and user_id = $3""",
        store_id, business_date, user_id,
    ))


async def insert_submission(db, store_id: int, business_date: date, user_id: int,
                            scope_shift_ids: list[int] | None, total: int, done: int,
                            *, late: bool, personal: bool) -> dict[str, Any]:
    """사람·영업일당 하나. 이미 있으면 그대로 돌려준다(멱등)."""
    await db.execute(
        """insert into checklist_submissions
             (store_id, business_date, user_id, scope_shift_ids, total_lines, done_lines, late, personal)
           values ($1, $2, $3, $4, $5, $6, $7, $8)
           on conflict (store_id, business_date, user_id) do nothing""",
        store_id, business_date, user_id, scope_shift_ids, total, done, late, personal,
    )
    return await get_submission(db, store_id, business_date, user_id)  # type: ignore[return-value]


async def submissions_on(db, store_id: int, business_date: date) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """select user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at from checklist_submissions
           where store_id = $1 and business_date = $2 order by submitted_at""",
        store_id, business_date,
    )
    return [_submission(r) for r in rows]  # type: ignore[misc]
```

- [ ] **Step 4: router 추가** (`router.py`, import 보강 후 끝에)

추가 import:

```python
from datetime import date, datetime, timedelta, timezone

from fastapi import Query

from app.checklist.calendar import ShiftWindow, business_date, local_time, pick_current_shift
from app.checklist.schemas import CheckRequest, SubmissionRequest
from app.checklist.scope import build_today, cards_in_scope, line_keys, resolve_scope
```

```python
def date_policy(today: date, requested: date, previous_submitted: bool, *, allow_late: bool) -> bool:
    """오늘이면 False. 바로 전 영업일이고 아직 제출 안 했고 어제 창 경로면 True(late). 그 밖은 409 (C6)."""
    if requested == today:
        return False
    if allow_late and requested == today - timedelta(days=1) and not previous_submitted:
        return True
    raise ApiError(409, "BUSINESS_DATE_CHANGED", "하루가 바뀌었어요.", details={
        "current_business_date": today.isoformat(),
        "previous_unsubmitted": not previous_submitted,
    })


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _context(db, member: Member, now_utc: datetime):
    today = business_date(now_utc, member.timezone, member.day_starts_at)
    previous = today - timedelta(days=1)
    shifts = await repo.list_shifts(db, member.store_id)
    scope = resolve_scope(member.role, [s.shift_id for s in shifts],
                          await repo.member_shift_ids(db, member.store_id, member.member_id))
    cards = await repo.load_cards(db, member.store_id)
    previous_submitted = await repo.get_submission(db, member.store_id, previous, member.user_id) is not None
    return today, previous, shifts, scope, cards, previous_submitted


async def today_view(db, member: Member, *, now_utc: datetime, selected_shift_id: int | None,
                     requested_date: date | None, include_all: bool) -> dict[str, Any]:
    today, previous, shifts, scope, cards, previous_submitted = await _context(db, member, now_utc)
    target = today
    if requested_date is not None and requested_date != today:
        date_policy(today, requested_date, previous_submitted, allow_late=True)
        target, include_all = requested_date, True
    windows = [ShiftWindow(s.shift_id, s.sort_order, s.starts_at, s.ends_at) for s in shifts if s.shift_id in scope.shift_ids]
    current, upcoming = pick_current_shift(windows, local_time(now_utc, member.timezone), member.day_starts_at)
    if selected_shift_id is not None:
        if selected_shift_id not in scope.shift_ids:
            raise ApiError(404, "SHIFT_NOT_FOUND", "근무조를 찾을 수 없어요.")
        current, upcoming = selected_shift_id, False
    scoped = cards_in_scope(cards, scope)
    checked = await repo.checked_keys(db, member.store_id, target, [c.card_version_id for c in scoped])
    return build_today(
        business_date=target, previous_business_date=previous, previous_submitted=previous_submitted,
        shifts=shifts, cards=cards, scope=scope, checked=checked, selected_shift_id=current, upcoming=upcoming,
        include_all=include_all, submissions=await repo.submissions_on(db, member.store_id, target),
        my_submission=await repo.get_submission(db, member.store_id, target, member.user_id),
    )


@router.get("/today")
async def get_today(db: Db, claims: ApiClaims,
                    shift_id: int | None = Query(default=None),
                    date_: date | None = Query(default=None, alias="date")) -> dict[str, Any]:
    member = await require_member(db, claims)
    return await today_view(db, member, now_utc=_now(), selected_shift_id=shift_id,
                            requested_date=date_, include_all=False)


def _validate_items(items, allowed: set[tuple[int, int]]) -> list[tuple[int, int, bool]]:
    out = []
    for item in items:
        if (item.card_version_id, item.line_no) not in allowed:
            raise ApiError(409, "CHECK_OUT_OF_SCOPE", "지금 목록에 없는 항목이에요. 새로 불러와 주세요.")
        out.append((item.card_version_id, item.line_no, item.checked))
    return out


@router.put("/checks")
async def put_check(body: CheckRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today, previous, _, scope, cards, previous_submitted = await _context(db, member, _now())
    date_policy(today, body.business_date, previous_submitted, allow_late=False)
    items = _validate_items([body], line_keys(cards_in_scope(cards, scope)))
    async with db.transaction():
        await repo.apply_checks(db, member.store_id, today, member.user_id, items, late=False, personal=member.personal)
    return {"business_date": today.isoformat(), "card_version_id": body.card_version_id,
            "line_no": body.line_no, "checked": body.checked}


@router.post("/submissions")
async def submit(body: SubmissionRequest, db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    today, previous, _, scope, cards, previous_submitted = await _context(db, member, _now())
    late = date_policy(today, body.business_date, previous_submitted, allow_late=True)
    target = body.business_date
    scoped = cards_in_scope(cards, scope)
    keys = line_keys(scoped)
    items = _validate_items(body.checks, keys)
    async with db.transaction():
        await repo.apply_checks(db, member.store_id, target, member.user_id, items, late=late, personal=member.personal)
        checked = await repo.checked_keys(db, member.store_id, target, [c.card_version_id for c in scoped])
        submission = await repo.insert_submission(
            db, member.store_id, target, member.user_id, None if scope.all else list(scope.shift_ids),
            len(keys), len(keys & checked), late=late, personal=member.personal,
        )
    return {"business_date": target.isoformat(), "submission": submission}
```

- [ ] **Step 5: 통과 확인** — `cd api && python -m pytest tests/test_checklist_logic.py -q && python -c "import app.main"` · Expected: PASS

- [ ] **Step 6: 격리 정적 검사** — `python3 .claude/skills/store-isolation-check/check_store_id.py api/app/checklist` · Expected: 위반 0건

- [ ] **Step 7: 변경 파일 확인** — repository.py, router.py, 테스트

---

### Task 5: 점주 현황·개인 기록 조회

**Files:**
- Modify: `api/app/checklist/repository.py`, `api/app/checklist/router.py`
- Test: `api/tests/test_checklist_logic.py` (`records_access` 테스트)

**Interfaces:**
- Consumes: Task 4 `_context`, `today_view`, repo `submissions_on`
- Produces:
  - repo `last_submission(db, store_id, dates: list[date]) -> dict | None`
  - repo `record_days(db, store_id, user_id, start: date, end: date) -> list[dict]`
  - repo `record_day(db, store_id, user_id, day: date) -> dict`
  - repo `member_by_user(db, store_id, user_id) -> Record | None`
  - router `records_access(viewer: Member, target_user_id: int, target_role: str | None) -> bool` (visible 여부, 403 은 예외)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from app.checklist.router import records_access


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
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL (`records_access` 없음)

- [ ] **Step 3: repository 추가**

```python
async def member_by_user(db, store_id: int, user_id: int):
    return await db.fetchrow(
        """select m.member_id, m.member_role, m.personal_records_enabled, u.name from store_members m
           join users u on u.user_id = m.user_id where m.store_id = $1 and m.user_id = $2""",
        store_id, user_id,
    )


async def last_submission(db, store_id: int, dates: list[date]) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """select business_date, user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at
           from checklist_submissions where store_id = $1 and business_date = any($2::date[])
           order by submitted_at desc limit 1""",
        store_id, dates,
    )
    if row is None:
        return None
    out = _submission(row)
    out["business_date"] = row["business_date"].isoformat()  # type: ignore[index]
    return out


async def record_days(db, store_id: int, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
    """출근한 날 = 내 체크 이벤트나 개인 제출이 있는 날. %는 제출 때 고정값, 제출이 없으면 체크한 줄 수만."""
    rows = await db.fetch(
        """with last as (
             select distinct on (business_date, card_version_id, line_no) business_date, checked
             from checklist_check_events
             where store_id = $1 and user_id = $2 and business_date between $3 and $4
             order by business_date, card_version_id, line_no, event_id desc
           ), checks as (
             select business_date, count(*) filter (where checked) as checked_lines from last group by business_date
           ), subs as (
             select business_date, total_lines, done_lines from checklist_submissions
             where store_id = $1 and user_id = $2 and personal and business_date between $3 and $4
           )
           select coalesce(c.business_date, s.business_date) as day,
                  coalesce(c.checked_lines, 0) as checked_lines, s.total_lines, s.done_lines
           from checks c full join subs s on s.business_date = c.business_date
           order by day""",
        store_id, user_id, start, end,
    )
    days = []
    for r in rows:
        total = r["total_lines"]
        days.append({
            "date": r["day"].isoformat(), "submitted": total is not None,
            "checked_lines": int(r["checked_lines"]),
            "percent": (round(100 * r["done_lines"] / total) if total else None) if total is not None else None,
            "total": total, "done": r["done_lines"],
        })
    return days


async def record_day(db, store_id: int, user_id: int, day: date) -> dict[str, Any]:
    rows = await db.fetch(
        """with last as (
             select distinct on (card_version_id, line_no) card_version_id, line_no, checked, created_at
             from checklist_check_events
             where store_id = $1 and user_id = $2 and business_date = $3
             order by card_version_id, line_no, event_id desc
           )
           select l.card_version_id, l.line_no, l.created_at, v.title, v.content
           from last l join card_versions v on v.store_id = $1 and v.version_id = l.card_version_id
           where l.checked order by l.created_at""",
        store_id, user_id, day,
    )
    lines = []
    for r in rows:
        texts = split_lines(r["content"])
        if 1 <= r["line_no"] <= len(texts):
            lines.append({"title": r["title"], "text": texts[r["line_no"] - 1],
                          "checked_at": r["created_at"].isoformat()})
    sub = await db.fetchrow(
        """select user_id, scope_shift_ids, total_lines, done_lines, late, submitted_at from checklist_submissions
           where store_id = $1 and user_id = $2 and business_date = $3 and personal""",
        store_id, user_id, day,
    )
    return {"date": day.isoformat(), "lines": lines, "submission": _submission(sub)}
```

- [ ] **Step 4: router 추가**

```python
def records_access(viewer: Member, target_user_id: int, target_role: str | None) -> bool:
    """본인은 항상. 직원은 남의 기록 403. 점주는 매장 설정(알바생 기록)에 따라 (C7-2)."""
    if target_role is None:
        raise ApiError(404, "MEMBER_NOT_FOUND", "직원을 찾을 수 없어요.")
    if target_user_id == viewer.user_id:
        return True
    if viewer.role != "OWNER":
        raise ApiError(403, "RECORDS_FORBIDDEN", "다른 사람의 기록은 볼 수 없어요.")
    return viewer.staff_records_visible


@router.get("/status")
async def get_status(db: Db, claims: ApiClaims) -> dict[str, Any]:
    member = await require_member(db, claims)
    require_owner_member(member)
    now = _now()
    view = await today_view(db, member, now_utc=now, selected_shift_id=None, requested_date=None, include_all=True)
    today = date.fromisoformat(view["business_date"])
    shifts = {s.shift_id: s.name for s in await repo.list_shifts(db, member.store_id)}
    last = await repo.last_submission(db, member.store_id, [today, today - timedelta(days=1)])
    if last is not None:
        ids = last["scope_shift_ids"]
        last["shift_names"] = [] if ids is None else [shifts[i] for i in ids if i in shifts]
    return {"business_date": view["business_date"], "current_shift_id": view["current_shift_id"],
            "shifts": view["shifts"], "scope_counts": view["scope_counts"], "last_submission": last}


async def _target(db, member: Member, user_id: int | None) -> tuple[int, bool, bool]:
    target_id = user_id if user_id is not None else member.user_id
    row = await repo.member_by_user(db, member.store_id, target_id)
    visible = records_access(member, target_id, row["member_role"] if row else None)
    return target_id, visible, bool(row["personal_records_enabled"]) if row else False


@router.get("/records")
async def get_records(db: Db, claims: ApiClaims, month: str = Query(pattern=r"^\d{4}-\d{2}$"),
                      user_id: int | None = Query(default=None)) -> dict[str, Any]:
    member = await require_member(db, claims)
    target_id, visible, recording = await _target(db, member, user_id)
    start = date.fromisoformat(month + "-01")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    days = await repo.record_days(db, member.store_id, target_id, start, end) if visible else []
    return {"user_id": target_id, "month": month, "visible": visible, "recording": recording, "days": days}


@router.get("/records/{day}")
async def get_record_day(day: date, db: Db, claims: ApiClaims,
                         user_id: int | None = Query(default=None)) -> dict[str, Any]:
    member = await require_member(db, claims)
    target_id, visible, _ = await _target(db, member, user_id)
    if not visible:
        return {"user_id": target_id, "date": day.isoformat(), "visible": False, "lines": [], "submission": None}
    return {"user_id": target_id, "visible": True, **await repo.record_day(db, member.store_id, target_id, day)}
```

- [ ] **Step 5: 통과 확인** — `cd api && python -m pytest tests/test_checklist_logic.py -q && python -c "import app.main"` · Expected: PASS
- [ ] **Step 6: 격리 정적 검사** — Expected: 위반 0건
- [ ] **Step 7: 변경 파일 확인**

---

### Task 6: 일회용 DB 종단 검증과 CI 연결

**Files:**
- Create: `api/scripts/verify_checklist.py`
- Modify: `api/scripts/verify_r_schema_rebuild.py` (호출 추가)

**Interfaces:**
- Consumes: 라우트 함수 `router.create_shift`, `create_preset`, `set_shift_cards`, `set_card_links`, `set_member_shifts`, `update_settings`, `update_me`, `get_today`, `put_check`, `submit`, `get_status`, `get_records`, `get_record_day`, `delete_shift`, `today_view`, 스키마 클래스
- Produces: `async def verify(pool, db) -> None` (다른 verify 와 같은 모양)

- [ ] **Step 1: 검증 스크립트 작성** — `api/scripts/verify_checklist.py`

```python
"""P5 체크리스트 종단 검증. verify_r_schema_rebuild 가 만든 일회용 DB 에서만 돈다(운영·개발 DB 금지).

라우트 함수를 직접 불러 권한·격리·범위·영업일·제출·개인 기록을 확인한다.
"""
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

from app.checklist import router as cl
from app.checklist.schemas import CardLinks, CheckRequest, IdList, MySettings, Settings, ShiftCreate, SubmissionRequest
from app.db_session import ShortSession
from app.errors import ApiError

# 서울 2026-10-07 15:00 (UTC 06:00) — 영업일 10/7, 미들 시간
NOON = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 7)


async def _expect(code, coro):
    try:
        await coro
    except ApiError as exc:
        assert exc.code == code, (exc.code, code)
        return exc
    raise AssertionError(f"expected {code}")


async def verify(pool, db):
    session = ShortSession(pool)
    owner = await db.fetchval("insert into users(name,role) values('합성 체크 점주','OWNER') returning user_id")
    staff = await db.fetchval("insert into users(name,role) values('합성 체크 알바','STAFF') returning user_id")
    quiet = await db.fetchval("insert into users(name,role) values('합성 기록끔 알바','STAFF') returning user_id")
    sid = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 체크 매장','CAFE') returning store_id", owner)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER')", sid, owner)
    staff_mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF') returning member_id", sid, staff)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'STAFF')", sid, quiet)
    other_owner = await db.fetchval("insert into users(name,role) values('합성 다른 점주','OWNER') returning user_id")
    other = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 다른 매장','CAFE') returning store_id", other_owner)
    await db.execute("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER')", other, other_owner)

    async def card(store, title, content, status="APPROVED"):
        # 승인 상태로 넣으면 트리거가 공개 버전을 만든다
        return await db.fetchval("""insert into knowledge_cards(store_id,title,content,review_status)
            values($1,$2,$3,$4) returning card_id""", store, title, content, status)

    common = await card(sid, '합성 공통', '물 채우기')
    opening = await card(sid, '합성 오픈', '머신 켜기\n원두 소분')
    closing = await card(sid, '합성 마감', '머신 청소')
    draft = await card(sid, '합성 초안', '보이면 안 됨', status='PENDING')
    foreign = await card(other, '합성 남의 카드', '남의 줄')

    o = dict(store_id=sid, user_id=owner, role='OWNER')
    s = dict(store_id=sid, user_id=staff, role='STAFF')
    q = dict(store_id=sid, user_id=quiet, role='STAFF')
    x = dict(store_id=other, user_id=other_owner, role='OWNER')

    # 권한·격리
    await _expect('OWNER_ONLY', cl.create_shift(ShiftCreate(name='합성'), session, s))
    await _expect('MEMBERSHIP_REQUIRED', cl.list_shifts(session, dict(store_id=sid, user_id=other_owner, role='OWNER')))
    print('PASS checklist owner-only and membership')

    shifts = (await cl.create_preset(session, o))['items']
    await _expect('SHIFTS_EXIST', cl.create_preset(session, o))
    open_id, middle_id, close_id = (sh['shift_id'] for sh in shifts)
    await _expect('SHIFT_NAME_TAKEN', cl.create_shift(ShiftCreate(name=' 오픈 '), session, o))
    await _expect('SHIFT_NOT_FOUND', cl.set_shift_cards(open_id, IdList(ids=[]), session, x))
    await _expect('CARD_NOT_FOUND', cl.set_shift_cards(open_id, IdList(ids=[foreign]), session, o))
    print('PASS checklist preset, duplicate name, cross-store 404')

    await cl.set_card_links(common, CardLinks(checklist=True, shift_ids=[]), session, o)
    await cl.set_shift_cards(open_id, IdList(ids=[opening, closing, draft]), session, o)
    await cl.set_shift_cards(close_id, IdList(ids=[closing]), session, o)
    await cl.set_shift_cards(open_id, IdList(ids=[opening, draft]), session, o)
    links = await cl.get_card_links(closing, session, o)
    assert links == {'card_id': closing, 'checklist': True, 'shift_ids': [close_id]}, links
    await cl.set_shift_cards(close_id, IdList(ids=[]), session, o)
    assert (await cl.get_card_links(closing, session, o))['checklist'] is False
    print('PASS checklist removing last shift does not make card common')
    await cl.set_shift_cards(close_id, IdList(ids=[closing]), session, o)

    await cl.set_member_shifts(staff_mid, IdList(ids=[middle_id, close_id]), session, o)
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, s)
        view = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    names = [g['name'] for g in view['groups']]
    assert names == ['공통', '마감'], names     # 미들엔 카드 없음, 오픈은 담당 아님, 초안 숨김
    assert view['current_shift_id'] == middle_id and view['scope_counts'] == {'total': 2, 'done': 0}, view
    print('PASS checklist staff scope = common + assigned, drafts hidden')

    with patch.object(cl, '_now', return_value=NOON):
        version = view['groups'][0]['cards'][0]['card_version_id']
        await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=version, line_no=1, checked=True), session, s)
        await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=version, line_no=1, checked=True), session, s)
        opening_version = await db.fetchval('select published_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, opening)
        await _expect('CHECK_OUT_OF_SCOPE', cl.put_check(CheckRequest(business_date=TODAY, card_version_id=opening_version, line_no=1, checked=True), session, s))
        conflict = await _expect('BUSINESS_DATE_CHANGED', cl.put_check(CheckRequest(business_date=TODAY - timedelta(days=1), card_version_id=version, line_no=1, checked=True), session, s))
        assert conflict.details['previous_unsubmitted'] is True
    assert await db.fetchval('select count(*) from checklist_check_events where store_id=$1 and user_id=$2', sid, staff) == 2
    print('PASS checklist idempotent check, scope 409, stale date 409')

    # 내 기록 끈 사람: 매장 체크는 바뀌고 사람 흔적은 없다 (C7-1)
    await cl.update_me(MySettings(personal_records_enabled=False), session, q)
    with patch.object(cl, '_now', return_value=NOON):
        closing_version = await db.fetchval('select published_version_id from knowledge_cards where store_id=$1 and card_id=$2', sid, closing)
        await cl.put_check(CheckRequest(business_date=TODAY, card_version_id=closing_version, line_no=1, checked=True), session, q)
        sub = (await cl.submit(SubmissionRequest(business_date=TODAY), session, q))['submission']
    assert await db.fetchval('select updated_by from checklist_checks where store_id=$1 and card_version_id=$2', sid, closing_version) is None
    assert await db.fetchval('select count(*) from checklist_check_events where store_id=$1 and user_id=$2', sid, quiet) == 0
    assert await db.fetchval('select personal from checklist_submissions where store_id=$1 and user_id=$2', sid, quiet) is False
    assert sub['total_lines'] == 4 and sub['scope_shift_ids'] is None, sub   # 담당 없음 → 전체
    print('PASS checklist personal records off leaves no trace but keeps store state')

    with patch.object(cl, '_now', return_value=NOON):
        first = (await cl.submit(SubmissionRequest(business_date=TODAY), session, s))['submission']
        again = (await cl.submit(SubmissionRequest(business_date=TODAY), session, s))['submission']
    assert first == again and first['total_lines'] == 2 and first['done_lines'] == 2, first
    print('PASS checklist submission fixed and idempotent')

    # 어제 창: 다음 날 오후, 어제 미제출인 점주는 late 저장 가능, 이미 제출한 알바는 409
    tomorrow = NOON + timedelta(days=1)
    with patch.object(cl, '_now', return_value=tomorrow):
        late = (await cl.submit(SubmissionRequest(business_date=TODAY, checks=[
            {'card_version_id': opening_version, 'line_no': 2, 'checked': True}]), session, o))['submission']
        await _expect('BUSINESS_DATE_CHANGED', cl.submit(SubmissionRequest(business_date=TODAY), session, s))
        await _expect('BUSINESS_DATE_CHANGED', cl.submit(SubmissionRequest(business_date=TODAY - timedelta(days=1)), session, o))
    assert late['late'] is True and late['scope_shift_ids'] is None
    print('PASS checklist late save only for previous unsubmitted day')

    # 새 공개 버전이면 그날 체크는 새로 시작
    await db.execute("update knowledge_cards set content=$3 where store_id=$1 and card_id=$2", sid, common, '물 채우기\n컵 채우기')
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, s)
        fresh = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    assert not any(line['checked'] for line in fresh['groups'][0]['cards'][0]['lines'])
    print('PASS checklist new published version restarts checks')

    # 근무조 보관 → 그 근무조에만 있던 카드는 어디에도 안 나온다
    await cl.delete_shift(close_id, session, o)
    with patch.object(cl, '_now', return_value=NOON):
        member = await cl.require_member(session, o)
        owner_view = await cl.today_view(session, member, now_utc=NOON, selected_shift_id=None, requested_date=None, include_all=True)
    titles = [c['title'] for g in owner_view['groups'] for c in g['cards']]
    assert '합성 마감' not in titles, titles
    print('PASS checklist archived shift hides its cards')

    # 개인 기록: 알바 본인 보임, 점주가 알바생 기록 끄면 점주에겐 안 보이고 켜면 다시 보임 (C7-2)
    month = TODAY.strftime('%Y-%m')
    own = await cl.get_records(session, s, month=month, user_id=None)
    assert own['visible'] and own['days'][0]['percent'] == 100, own
    await _expect('RECORDS_FORBIDDEN', cl.get_records(session, s, month=month, user_id=owner))
    await cl.update_settings(Settings(staff_records_visible=False), session, o)
    hidden = await cl.get_records(session, o, month=month, user_id=staff)
    assert hidden['visible'] is False and hidden['days'] == []
    await cl.update_settings(Settings(staff_records_visible=True), session, o)
    shown = await cl.get_records(session, o, month=month, user_id=staff)
    assert shown['days'], shown
    day = await cl.get_record_day(TODAY, session, o, user_id=staff)
    assert [l['text'] for l in day['lines']] == ['물 채우기'], day
    quiet_records = await cl.get_records(session, q, month=month, user_id=None)
    assert quiet_records['days'] == [] and quiet_records['recording'] is False
    await _expect('MEMBER_NOT_FOUND', cl.get_records(session, o, month=month, user_id=other_owner))
    print('PASS checklist personal records visibility and owner toggle')

    with patch.object(cl, '_now', return_value=NOON):
        status = await cl.get_status(session, o)
    assert status['last_submission'] is not None and status['business_date'] == TODAY.isoformat(), status
    print('PASS checklist owner status')
```

- [ ] **Step 2: 재구축 검증에 연결** — `api/scripts/verify_r_schema_rebuild.py` 에서 `verify_legacy_publication(pool, fresh)` 바로 다음 줄에

```python
            from verify_checklist import verify as verify_checklist
            await verify_checklist(pool, fresh)
```

- [ ] **Step 3: 로컬 일회용 DB 로 실행**

Run (worktree 루트):
```bash
docker run --detach --rm --name askbuddy-checklist-verify --publish 127.0.0.1:55439:5432 \
  --env POSTGRES_PASSWORD=synthetic-local-test --env POSTGRES_DB=usage_verify pgvector/pgvector:pg17
for i in $(seq 1 20); do docker exec askbuddy-checklist-verify pg_isready -U postgres -d usage_verify && break; sleep 0.5; done
cd api && PYTHONUTF8=1 ../../2026unithon/api/.venv/bin/python -B scripts/verify_r_schema_rebuild.py; cd ..
docker stop askbuddy-checklist-verify
```
Expected: 기존 PASS 들 뒤에 `PASS checklist ...` 11줄, 마지막에 오류 없음. 실패하면 멈추고 원인을 고친다

- [ ] **Step 4: 전체 단위 테스트** — `cd api && python -m pytest tests -q` · Expected: 기존과 같은 결과 + 체크리스트 테스트 통과
- [ ] **Step 5: 격리 정적 검사(전체)** — `python3 .claude/skills/store-isolation-check/check_store_id.py api/app` · Expected: 새 위반 0건
- [ ] **Step 6: 설계 문서 반영** — `UI_REBRAND_P5_CHECKLIST.md` §5 "완료 %(달력)" 줄을 아래로 바꾼다(구현 단순화):
  `- **완료 %(달력)**: 제출이 있으면 done_lines / total_lines(제출 때 고정). 제출이 없는 날은 % 없이 "체크 N개"만 보여준다`
- [ ] **Step 7: 변경 파일 확인**

---

## 자체 점검

- 설계 §3 화면 중 백엔드가 필요한 것: 오늘 할 일(Task 4), 제출(4), 어제 창(4 `?date=`·late 제출), 점주 현황(5), 마이페이지(5), 근무조 설정·할 일 담기·직원 담당·알바생 기록·카드 상세 연결·내 기록(3) — 모두 대응
- 설계 §6 API 15개: shifts GET/POST/PATCH/DELETE·order·preset·shift cards·card GET/PUT·members GET/PUT·settings·me·today·checks·submissions·status·records·records/{date} — Task 3·4·5
- 프론트(P5 화면)는 이 계획 밖. 백엔드 완료 후 별도로 진행
