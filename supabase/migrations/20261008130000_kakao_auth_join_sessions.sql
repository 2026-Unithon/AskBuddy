-- 카카오 로그인 · 초대 링크 · 합류 승인 · 90일 세션 (이슈 #37)
-- 새 인증 API와 함께 적용한다. 이전 초대코드는 폐기되므로 구버전 합류와 호환되지 않는다.
begin;

-- 외부 로그인 연결. 카카오 프로필 원본·토큰은 저장하지 않는다
create table user_identities (
  identity_id       bigint generated always as identity primary key,
  user_id           bigint not null references users(user_id) on delete cascade,
  provider          varchar(20) not null check (provider in ('KAKAO')),
  provider_user_id  varchar(64) not null,
  created_at        timestamptz not null default now(),
  last_login_at     timestamptz not null default now(),
  unique (provider, provider_user_id),
  unique (user_id, provider)
);

-- 합류 요청. 승인 전에는 store_members 행이 없다
create table store_join_requests (
  request_id    bigint generated always as identity primary key,
  store_id      bigint not null references stores(store_id) on delete cascade,
  user_id       bigint not null references users(user_id) on delete cascade,
  invite_id     bigint references invite_codes(invite_id) on delete set null,
  status        varchar(20) not null default 'PENDING'
                check (status in ('PENDING','APPROVED','REJECTED')),
  requested_at  timestamptz not null default now(),
  decided_at    timestamptz,
  decided_by    bigint references users(user_id) on delete set null,
  check ((status = 'PENDING') = (decided_at is null))
);
create unique index store_join_requests_one_pending
  on store_join_requests (store_id, user_id) where status = 'PENDING';
create index store_join_requests_user on store_join_requests (user_id, requested_at desc);

-- 90일 슬라이딩 세션. 원문은 쿠키에만, DB 에는 SHA-256(hex)만 둔다
create table auth_refresh_tokens (
  token_id      bigint generated always as identity primary key,
  user_id       bigint not null references users(user_id) on delete cascade,
  token_hash    char(64) not null unique,
  family_id     uuid not null,
  expires_at    timestamptz not null,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz,
  revoked_at    timestamptz,
  replaced_by   bigint references auth_refresh_tokens(token_id) on delete set null
);
create index auth_refresh_tokens_active_user
  on auth_refresh_tokens (user_id) where revoked_at is null;
create index auth_refresh_tokens_family on auth_refresh_tokens (family_id);

-- 단일 로그인 화면: 새 계정은 가입 직후 역할을 고른다. 고르기 전에는 비어 있다.
-- users_role_check(in 목록)는 null 을 통과시키므로 그대로 둔다
alter table users alter column role drop not null;

-- 내보내기는 삭제가 아니라 표시. 질문·학습 기록 FK 가 cascade 라 행을 지우면 기록이 사라진다
alter table store_members
  add column removed_at timestamptz,
  add column removed_by bigint references users(user_id) on delete set null;

-- 초대 링크 재생성. 매장당 활성 링크는 하나
alter table invite_codes add column revoked_at timestamptz;
-- 4자리 코드는 대입 가능하다. 전부 무효로 하고 점주가 새 링크를 만든다.
-- 매장당 활성 코드가 여러 개인 경우가 있어 unique 인덱스보다 먼저 정리한다
update invite_codes set revoked_at = now() where revoked_at is null;
create unique index invite_codes_one_active
  on invite_codes (store_id) where revoked_at is null;

alter table notification_events drop constraint notification_events_event_type_check;
alter table notification_events add constraint notification_events_event_type_check
  check (event_type in ('INGEST_COMPLETED','PENDING_QUESTION','OWNER_ANSWER',
                        'JOIN_REQUESTED','JOIN_APPROVED'));

-- 승인 알림은 알바 화면으로 보낸다. 지금까지는 점주 화면만 허용했다
alter table notification_events drop constraint notification_events_destination_check;
alter table notification_events add constraint notification_events_destination_check
  check (destination ~ '^/(owner|staff)/[A-Za-z0-9_/?=&.-]*$');

alter table notification_events drop constraint notification_events_aggregate_type_check;
alter table notification_events add constraint notification_events_aggregate_type_check
  check (aggregate_type in ('INGEST_JOB','PENDING_QUESTION','OWNER_ANSWER','JOIN_REQUEST'));

commit;
