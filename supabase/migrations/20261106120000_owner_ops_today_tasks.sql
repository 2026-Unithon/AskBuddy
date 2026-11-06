-- 점주 운영 기능: 오늘만 할 일(사장 지시) + 알림 종류 + 문장 다듬기 원가 단계.
-- 오늘만 할 일은 지식카드가 아니다. 승인·검색·학습 경로에 섞이지 않게 별도 테이블에 둔다(불변식 11).
-- 영업일이 지나면 화면에서 빠질 뿐 행은 지우지 않는다 — 주간 리포트의 지시·완료 건수 근거다.

create table if not exists today_tasks (
  task_id        bigint generated always as identity primary key,
  store_id       bigint not null references stores(store_id) on delete cascade,
  business_date  date not null,
  body           text not null check (length(btrim(body)) between 1 and 300),
  original_text  text not null check (length(btrim(original_text)) between 1 and 300),
  created_by     bigint not null references users(user_id),
  created_at     timestamptz not null default now(),
  canceled_at    timestamptz,
  unique (store_id, task_id)
);
create index if not exists today_tasks_store_day on today_tasks (store_id, business_date);

-- 대상 알바생. 만들 때 고른 사람을 고정한다(나중에 들어온 직원에게 소급하지 않는다)
create table if not exists today_task_targets (
  store_id   bigint not null references stores(store_id) on delete cascade,
  task_id    bigint not null,
  member_id  bigint not null references store_members(member_id) on delete cascade,
  seen_at    timestamptz,
  done_at    timestamptz,
  primary key (store_id, task_id, member_id),
  foreign key (store_id, task_id) references today_tasks (store_id, task_id) on delete cascade
);
create index if not exists today_task_targets_member on today_task_targets (store_id, member_id);

-- 대상 직원이 같은 매장 사람인지 DB 에서도 막는다(D1 은 API 가 책임지지만 이중으로 둔다)
create or replace function askbuddy_today_target_store_check()
returns trigger language plpgsql as $$
begin
  if not exists (select 1 from store_members m where m.member_id = new.member_id and m.store_id = new.store_id) then
    raise exception '오늘만 할 일 대상의 매장이 맞지 않는다 (store=%, member=%)', new.store_id, new.member_id;
  end if;
  return new;
end $$;

drop trigger if exists trg_today_task_targets_store_check on today_task_targets;
create trigger trg_today_task_targets_store_check
before insert or update on today_task_targets
for each row execute function askbuddy_today_target_store_check();

-- 알림: 오늘만 할 일은 대상 알바생에게 무조건 앱 알림을 만든다
alter table notification_events drop constraint notification_events_event_type_check;
alter table notification_events add constraint notification_events_event_type_check
  check (event_type in ('INGEST_COMPLETED','PENDING_QUESTION','OWNER_ANSWER',
                        'JOIN_REQUESTED','JOIN_APPROVED','TODAY_TASK'));

alter table notification_events drop constraint notification_events_aggregate_type_check;
alter table notification_events add constraint notification_events_aggregate_type_check
  check (aggregate_type in ('INGEST_JOB','PENDING_QUESTION','OWNER_ANSWER','JOIN_REQUEST','TODAY_TASK'));

-- 알바 첫 화면(/staff) 자체로도 보낼 수 있게 한다. 이전 형식은 모두 그대로 통과한다
alter table notification_events drop constraint notification_events_destination_check;
alter table notification_events add constraint notification_events_destination_check
  check (destination ~ '^/(owner|staff)([/?][A-Za-z0-9_/?=&.-]*)?$');

-- 원가 원장: 점주 지시 문장 다듬기 호출 단계
alter table ai_usage_attempts drop constraint if exists ai_usage_attempts_stage_check;
alter table ai_usage_attempts add constraint ai_usage_attempts_stage_check check (stage in (
  'STT','EXTRACT','ASSEMBLE','CLASSIFY','RELATION',
  'EMBED','QUERY','RERANK','ANSWER','VALIDATE','POLISH'));
