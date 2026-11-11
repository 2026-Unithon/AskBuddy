-- 계획 8(2026-11-10): 로그인된 기기, 의견, 퇴사, 탈퇴
-- 탈퇴 칸(stores.closing_at·purge_due_at·deleted_at, users.deleted_at)은 계획 9 의 20261110110000_store_purge.sql 에 있다
alter table auth_refresh_tokens add column if not exists user_agent varchar(300);

create table if not exists user_feedback (
  feedback_id bigint generated always as identity primary key,
  store_id    bigint references stores(store_id) on delete cascade,
  user_id     bigint references users(user_id) on delete set null,
  kind        varchar(10) not null check (kind in ('INQUIRY','IDEA')),
  body        text not null check (char_length(btrim(body)) between 1 and 2000),
  created_at  timestamptz not null default now()
);
create index if not exists user_feedback_created on user_feedback (created_at desc);
