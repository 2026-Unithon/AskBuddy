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
