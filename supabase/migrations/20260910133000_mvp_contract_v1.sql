-- =====================================================================
-- AskBuddy MVP 계약 v1 — Supabase 운영용 기존 데이터 보존형 확장 마이그레이션
-- 기준: docs/ASKBUDDY_MVP_CONTRACT_V1.md
--
-- 원칙
--   1. 001/002로 생성된 데이터를 삭제하지 않는다.
--   2. 기존 API가 사용하는 컬럼은 호환을 위해 유지한다.
--   3. 재실행해도 백필 행이 중복되지 않는다.
-- =====================================================================

begin;

select pg_advisory_xact_lock(hashtext('askbuddy:003_mvp_contract_v1'));

-- ---------------------------------------------------------------------
-- 1. 매장 · 카테고리 · 원본 확장
-- ---------------------------------------------------------------------

alter table stores
  add column if not exists guide_completed_at timestamptz,
  add column if not exists category_version int not null default 1
    check (category_version >= 1);

alter table task_categories
  add column if not exists is_system boolean not null default false,
  add column if not exists created_version int not null default 1,
  add column if not exists deleted_version int,
  add column if not exists deleted_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

-- 기존 OFF 카테고리는 삭제된 설정으로 보존한다. 다시 같은 이름을 추가하면
-- 새 행을 만들지 않고 이 행을 되살리는 것이 API 계약이다.
update task_categories
set deleted_at = coalesce(deleted_at, now()),
    deleted_version = coalesce(deleted_version, 1),
    updated_at = now()
where is_enabled = false
  and deleted_at is null;

-- 기존에 사용자가 만든 '기타'가 있으면 시스템 카테고리로 승격한다.
update task_categories
set is_system = true,
    is_enabled = true,
    deleted_at = null,
    deleted_version = null,
    updated_at = now()
where category_name = '기타';

-- 모든 기존 매장에 삭제할 수 없는 기타를 정확히 하나 보장한다.
insert into task_categories (
  store_id, category_name, is_enabled, sort_order,
  is_system, created_version, updated_at
)
select s.store_id, '기타', true, 9999, true, s.category_version, now()
from stores s
where not exists (
  select 1
  from task_categories c
  where c.store_id = s.store_id
    and c.category_name = '기타'
);

create unique index if not exists uq_task_categories_system_other
  on task_categories (store_id)
  where is_system = true and category_name = '기타';

create index if not exists idx_task_categories_current
  on task_categories (store_id, sort_order, category_id)
  where deleted_at is null;

create or replace function askbuddy_ensure_other_category()
returns trigger
language plpgsql
as $$
begin
  insert into task_categories (
    store_id, category_name, is_enabled, sort_order,
    is_system, created_version, updated_at
  )
  values (new.store_id, '기타', true, 9999, true, new.category_version, now())
  on conflict (store_id, category_name) do update
    set is_system = true,
        is_enabled = true,
        deleted_at = null,
        deleted_version = null,
        updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_stores_ensure_other_category on stores;
create trigger trg_stores_ensure_other_category
after insert on stores
for each row execute function askbuddy_ensure_other_category();

create or replace function askbuddy_protect_system_category()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' and old.is_system then
    raise exception using
      errcode = '23514',
      message = 'SYSTEM_CATEGORY_IMMUTABLE';
  end if;

  if tg_op = 'UPDATE' and old.is_system then
    if new.store_id is distinct from old.store_id
       or new.category_name is distinct from '기타'
       or new.is_system is distinct from true
       or new.is_enabled is distinct from true
       or new.deleted_at is not null
       or new.deleted_version is not null then
      raise exception using
        errcode = '23514',
        message = 'SYSTEM_CATEGORY_IMMUTABLE';
    end if;
  end if;

  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

drop trigger if exists trg_task_categories_protect_system on task_categories;
create trigger trg_task_categories_protect_system
before update or delete on task_categories
for each row execute function askbuddy_protect_system_category();

alter table sources
  add column if not exists upload_status varchar(20) not null default 'REGISTERED'
    check (upload_status in ('REGISTERED', 'UPLOAD_FAILED')),
  add column if not exists mime_type varchar(100),
  add column if not exists original_filename varchar(200);

create unique index if not exists uq_sources_store_source
  on sources (store_id, source_id);

-- ---------------------------------------------------------------------
-- 2. 안내 상태 · 추출 작업
-- ---------------------------------------------------------------------

create table if not exists owner_ui_state (
  user_id              bigint not null references users(user_id) on delete cascade,
  store_id             bigint not null references stores(store_id) on delete cascade,
  upload_guide_seen_at timestamptz,
  push_guide_seen_at   timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  primary key (user_id, store_id)
);

create index if not exists idx_owner_ui_state_store
  on owner_ui_state (store_id, user_id);

create table if not exists ingest_jobs (
  job_id               bigint generated always as identity primary key,
  store_id             bigint not null references stores(store_id) on delete cascade,
  created_by           bigint not null references users(user_id) on delete restrict,
  title                varchar(200),
  status               varchar(20) not null default 'QUEUED'
                       check (status in (
                         'QUEUED', 'EXTRACTING', 'CLASSIFYING',
                         'SUCCEEDED', 'PARTIAL', 'NO_RESULT', 'FAILED'
                       )),
  category_version     int not null check (category_version >= 1),
  prompt_version       varchar(100) not null,
  settings             jsonb not null default '{}'::jsonb,
  total_source_count   int not null default 0 check (total_source_count >= 0),
  success_source_count int not null default 0 check (success_source_count >= 0),
  failed_source_count  int not null default 0 check (failed_source_count >= 0),
  card_count           int not null default 0 check (card_count >= 0),
  excluded_candidate_count int not null default 0 check (excluded_candidate_count >= 0),
  error_code           varchar(80),
  error_message        varchar(1000),
  idempotency_key      varchar(200),
  started_at           timestamptz,
  completed_at         timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (store_id, idempotency_key)
);

create unique index if not exists uq_ingest_jobs_store_job
  on ingest_jobs (store_id, job_id);

create index if not exists idx_ingest_jobs_store_status_created
  on ingest_jobs (store_id, status, created_at desc);

create table if not exists ingest_job_sources (
  store_id      bigint not null,
  job_id        bigint not null,
  source_id     bigint not null,
  status        varchar(20) not null default 'QUEUED'
                check (status in (
                  'QUEUED', 'EXTRACTING', 'CLASSIFYING',
                  'SUCCEEDED', 'NO_RESULT', 'FAILED'
                )),
  card_count    int not null default 0 check (card_count >= 0),
  error_code    varchar(80),
  error_message varchar(1000),
  started_at    timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (job_id, source_id),
  foreign key (store_id, job_id)
    references ingest_jobs(store_id, job_id) on delete cascade,
  foreign key (store_id, source_id)
    references sources(store_id, source_id) on delete restrict
);

create index if not exists idx_ingest_job_sources_store_status
  on ingest_job_sources (store_id, status, job_id);

-- 기존 자료를 한 자료당 한 작업으로 백필한다. idempotency_key가 재실행 중복을 막는다.
insert into ingest_jobs (
  store_id, created_by, title, status, category_version,
  prompt_version, settings, total_source_count,
  success_source_count, failed_source_count, card_count,
  error_code, error_message, idempotency_key,
  started_at, completed_at, created_at, updated_at
)
select
  src.store_id,
  src.uploaded_by,
  coalesce(src.title, '기존 자료 #' || src.source_id),
  case
    when src.status = 'UPLOADED' then 'QUEUED'
    when src.status = 'PROCESSING' then 'EXTRACTING'
    when src.status = 'FAILED' then 'FAILED'
    when count(k.card_id) = 0 then 'NO_RESULT'
    else 'SUCCEEDED'
  end,
  s.category_version,
  'legacy-pre-v1',
  jsonb_build_object('migrated_from_source_status', src.status),
  1,
  case when src.status = 'DONE' then 1 else 0 end,
  case when src.status = 'FAILED' then 1 else 0 end,
  count(k.card_id)::int,
  case when src.status = 'FAILED' then 'LEGACY_SOURCE_FAILED' end,
  src.error_message,
  'legacy-source-' || src.source_id,
  case when src.status in ('PROCESSING', 'DONE', 'FAILED') then src.created_at end,
  case when src.status in ('DONE', 'FAILED') then coalesce(src.processed_at, src.created_at) end,
  src.created_at,
  coalesce(src.processed_at, src.created_at)
from sources src
join stores s on s.store_id = src.store_id
left join knowledge_cards k
  on k.store_id = src.store_id and k.source_id = src.source_id
group by src.source_id, s.category_version
on conflict (store_id, idempotency_key) do nothing;

insert into ingest_job_sources (
  store_id, job_id, source_id, status, card_count,
  error_code, error_message, started_at, completed_at, created_at, updated_at
)
select
  j.store_id,
  j.job_id,
  src.source_id,
  case
    when src.status = 'UPLOADED' then 'QUEUED'
    when src.status = 'PROCESSING' then 'EXTRACTING'
    when src.status = 'FAILED' then 'FAILED'
    when j.card_count = 0 then 'NO_RESULT'
    else 'SUCCEEDED'
  end,
  j.card_count,
  j.error_code,
  j.error_message,
  j.started_at,
  j.completed_at,
  j.created_at,
  j.updated_at
from ingest_jobs j
join sources src
  on src.store_id = j.store_id
 and j.idempotency_key = 'legacy-source-' || src.source_id
on conflict (job_id, source_id) do nothing;

-- 구 API가 /ingest/process를 계속 사용하는 확장 배포 기간에도 새 자료가
-- 작업 목록에서 사라지지 않도록 source 상태를 1개짜리 작업과 동기화한다.
create or replace function askbuddy_create_legacy_ingest_job()
returns trigger
language plpgsql
as $$
declare
  new_job_id bigint;
  current_category_version int;
begin
  select category_version into current_category_version
  from stores
  where store_id = new.store_id;

  insert into ingest_jobs (
    store_id, created_by, title, status, category_version,
    prompt_version, settings, total_source_count, idempotency_key, created_at, updated_at
  )
  values (
    new.store_id, new.uploaded_by, coalesce(new.title, '자료 #' || new.source_id),
    'QUEUED', current_category_version, 'legacy-adapter',
    jsonb_build_object('source_status_adapter', true), 1,
    'legacy-source-' || new.source_id, new.created_at, new.created_at
  )
  on conflict (store_id, idempotency_key) do update
    set updated_at = excluded.updated_at
  returning job_id into new_job_id;

  insert into ingest_job_sources (store_id, job_id, source_id, status, created_at, updated_at)
  values (new.store_id, new_job_id, new.source_id, 'QUEUED', new.created_at, new.created_at)
  on conflict (job_id, source_id) do nothing;

  return new;
end;
$$;

drop trigger if exists trg_sources_create_legacy_ingest_job on sources;
create trigger trg_sources_create_legacy_ingest_job
after insert on sources
for each row execute function askbuddy_create_legacy_ingest_job();

create or replace function askbuddy_sync_legacy_ingest_job()
returns trigger
language plpgsql
as $$
declare
  linked_job_id bigint;
  next_job_status varchar(20);
  next_source_status varchar(20);
  saved_card_count int;
begin
  select job_id into linked_job_id
  from ingest_jobs
  where store_id = new.store_id
    and idempotency_key = 'legacy-source-' || new.source_id;

  if linked_job_id is null then
    return new;
  end if;

  select count(*)::int into saved_card_count
  from knowledge_cards
  where store_id = new.store_id and source_id = new.source_id;

  next_job_status := case
    when new.status = 'UPLOADED' then 'QUEUED'
    when new.status = 'PROCESSING' then 'EXTRACTING'
    when new.status = 'FAILED' then 'FAILED'
    when saved_card_count = 0 then 'NO_RESULT'
    else 'SUCCEEDED'
  end;
  next_source_status := next_job_status;

  update ingest_jobs
  set status = next_job_status,
      success_source_count = case when new.status = 'DONE' then 1 else 0 end,
      failed_source_count = case when new.status = 'FAILED' then 1 else 0 end,
      card_count = saved_card_count,
      error_code = case when new.status = 'FAILED' then 'LEGACY_SOURCE_FAILED' end,
      error_message = new.error_message,
      started_at = case
        when new.status in ('PROCESSING', 'DONE', 'FAILED') then coalesce(started_at, now())
        else started_at
      end,
      completed_at = case
        when new.status in ('DONE', 'FAILED') then coalesce(new.processed_at, now())
        else null
      end,
      updated_at = now()
  where store_id = new.store_id and job_id = linked_job_id;

  update ingest_job_sources
  set status = next_source_status,
      card_count = saved_card_count,
      error_code = case when new.status = 'FAILED' then 'LEGACY_SOURCE_FAILED' end,
      error_message = new.error_message,
      started_at = case
        when new.status in ('PROCESSING', 'DONE', 'FAILED') then coalesce(started_at, now())
        else started_at
      end,
      completed_at = case
        when new.status in ('DONE', 'FAILED') then coalesce(new.processed_at, now())
        else null
      end,
      updated_at = now()
  where store_id = new.store_id
    and job_id = linked_job_id
    and source_id = new.source_id;

  return new;
end;
$$;

drop trigger if exists trg_sources_sync_legacy_ingest_job on sources;
create trigger trg_sources_sync_legacy_ingest_job
after update of status, error_message, processed_at on sources
for each row execute function askbuddy_sync_legacy_ingest_job();

-- ---------------------------------------------------------------------
-- 3. 카드 상태 · 버전 · 근거
-- ---------------------------------------------------------------------

alter table knowledge_cards
  add column if not exists review_status varchar(20) not null default 'PENDING'
    check (review_status in ('PENDING', 'NEEDS_REVIEW', 'APPROVED', 'EXCLUDED')),
  add column if not exists assignment_type varchar(20) not null default 'AUTOMATIC'
    check (assignment_type in ('AUTOMATIC', 'MANUAL')),
  add column if not exists category_version int not null default 1
    check (category_version >= 1),
  add column if not exists origin_job_id bigint references ingest_jobs(job_id) on delete set null,
  add column if not exists draft_version_id bigint,
  add column if not exists published_version_id bigint,
  add column if not exists excluded_at timestamptz,
  add column if not exists excluded_by bigint references users(user_id) on delete set null,
  add column if not exists needs_review_reason varchar(50);

alter table knowledge_cards
  alter column updated_at set default now();

update knowledge_cards
set review_status = case when is_verified then 'APPROVED' else review_status end,
    updated_at = coalesce(updated_at, created_at, now())
where (is_verified and review_status = 'PENDING')
   or updated_at is null;

update knowledge_cards k
set origin_job_id = j.job_id
from ingest_jobs j
where k.store_id = j.store_id
  and k.source_id is not null
  and j.idempotency_key = 'legacy-source-' || k.source_id
  and k.origin_job_id is null;

create unique index if not exists uq_knowledge_cards_store_card
  on knowledge_cards (store_id, card_id);

create index if not exists idx_knowledge_cards_store_review
  on knowledge_cards (store_id, review_status, updated_at desc);

create index if not exists idx_knowledge_cards_origin_job
  on knowledge_cards (store_id, origin_job_id, card_id);

create table if not exists card_versions (
  version_id     bigint generated always as identity primary key,
  store_id       bigint not null references stores(store_id) on delete cascade,
  card_id        bigint not null,
  version_no     int not null check (version_no >= 1),
  title          varchar(200) not null,
  content        text not null,
  change_source  varchar(20) not null
                 check (change_source in ('EXTRACTION', 'OWNER_EDIT', 'OWNER_ANSWER')),
  created_by     bigint references users(user_id) on delete set null,
  created_at     timestamptz not null default now(),
  unique (card_id, version_no),
  foreign key (store_id, card_id)
    references knowledge_cards(store_id, card_id) on delete cascade
);

create unique index if not exists uq_card_versions_store_version
  on card_versions (store_id, version_id);

create index if not exists idx_card_versions_store_card
  on card_versions (store_id, card_id, version_no desc);

-- 기존 카드는 현재 제목·본문을 첫 버전으로 보존한다.
insert into card_versions (
  store_id, card_id, version_no, title, content, change_source, created_at
)
select k.store_id, k.card_id, 1, k.title, k.content, 'EXTRACTION', k.created_at
from knowledge_cards k
where not exists (
  select 1 from card_versions v where v.card_id = k.card_id and v.version_no = 1
);

update knowledge_cards k
set draft_version_id = v.version_id,
    published_version_id = case when k.is_verified then v.version_id else null end
from card_versions v
where v.card_id = k.card_id
  and v.version_no = 1
  and (k.draft_version_id is null
       or (k.is_verified and k.published_version_id is null));

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'knowledge_cards_draft_version_fk'
  ) then
    alter table knowledge_cards
      add constraint knowledge_cards_draft_version_fk
      foreign key (draft_version_id) references card_versions(version_id) on delete restrict;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'knowledge_cards_published_version_fk'
  ) then
    alter table knowledge_cards
      add constraint knowledge_cards_published_version_fk
      foreign key (published_version_id) references card_versions(version_id) on delete restrict;
  end if;
end;
$$;

alter table card_embeddings
  add column if not exists version_id bigint references card_versions(version_id) on delete cascade;

update card_embeddings e
set version_id = k.published_version_id
from knowledge_cards k
where k.card_id = e.card_id
  and e.store_id = k.store_id
  and e.version_id is null
  and k.published_version_id is not null;

create index if not exists idx_card_embeddings_store_version
  on card_embeddings (store_id, version_id)
  where is_stale = false;

create table if not exists card_evidence (
  evidence_id  bigint generated always as identity primary key,
  store_id     bigint not null references stores(store_id) on delete cascade,
  version_id   bigint not null,
  source_id    bigint not null,
  locator_type varchar(20) not null
               check (locator_type in (
                 'TIMESTAMP', 'PAGE', 'FRAME', 'TEXT_RANGE', 'MESSAGE', 'WHOLE_SOURCE'
               )),
  locator      jsonb not null default '{}'::jsonb,
  excerpt      text,
  created_at   timestamptz not null default now(),
  foreign key (store_id, version_id)
    references card_versions(store_id, version_id) on delete cascade,
  foreign key (store_id, source_id)
    references sources(store_id, source_id) on delete restrict
);

create index if not exists idx_card_evidence_store_version
  on card_evidence (store_id, version_id, evidence_id);

create table if not exists card_review_events (
  event_id          bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  card_id           bigint not null,
  actor_id          bigint not null references users(user_id) on delete restrict,
  action            varchar(30) not null
                    check (action in (
                      'APPROVE', 'EDIT_DRAFT', 'PUBLISH_EDIT',
                      'EXCLUDE', 'RESTORE', 'MOVE_CATEGORY'
                    )),
  from_status       varchar(20),
  to_status         varchar(20),
  from_category_id  bigint references task_categories(category_id) on delete set null,
  to_category_id    bigint references task_categories(category_id) on delete set null,
  metadata          jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  foreign key (store_id, card_id)
    references knowledge_cards(store_id, card_id) on delete cascade
);

create index if not exists idx_card_review_events_store_created
  on card_review_events (store_id, created_at desc, event_id desc);

-- 기존 boolean API와 새 review_status를 마이그레이션 동안 동기화한다.
create or replace function askbuddy_sync_card_review_status()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'INSERT' then
    if new.category_version = 1 then
      select category_version into new.category_version
      from stores
      where store_id = new.store_id;
    end if;

    if new.origin_job_id is null and new.source_id is not null then
      select job_id into new.origin_job_id
      from ingest_jobs
      where store_id = new.store_id
        and idempotency_key = 'legacy-source-' || new.source_id;
    end if;

    if new.is_verified then
      new.review_status := 'APPROVED';
    else
      new.is_verified := new.review_status = 'APPROVED';
    end if;
  elsif new.review_status is distinct from old.review_status then
    new.is_verified := new.review_status = 'APPROVED';
  elsif new.is_verified is distinct from old.is_verified then
    if new.is_verified then
      new.review_status := 'APPROVED';
    elsif old.review_status = 'APPROVED' then
      new.review_status := 'PENDING';
    end if;
  end if;

  if new.review_status = 'APPROVED'
     and new.published_version_id is null
     and new.draft_version_id is not null then
    new.published_version_id := new.draft_version_id;
  end if;

  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_knowledge_cards_sync_review on knowledge_cards;
create trigger trg_knowledge_cards_sync_review
before insert or update on knowledge_cards
for each row execute function askbuddy_sync_card_review_status();

-- 구 API가 knowledge_cards.title/content를 직접 쓰는 동안에도 버전 계약을
-- 지킨다. 신규 API 전환 후에는 명시적인 card_versions 쓰기가 정본이 된다.
create or replace function askbuddy_version_legacy_card_write()
returns trigger
language plpgsql
as $$
declare
  new_version_id bigint;
  next_version_no int;
begin
  if tg_op = 'UPDATE'
     and new.title is not distinct from old.title
     and new.content is not distinct from old.content then
    return new;
  end if;

  select coalesce(max(version_no), 0) + 1 into next_version_no
  from card_versions
  where card_id = new.card_id;

  insert into card_versions (
    store_id, card_id, version_no, title, content, change_source, created_at
  )
  values (
    new.store_id, new.card_id, next_version_no, new.title, new.content,
    case when tg_op = 'INSERT' then 'EXTRACTION' else 'OWNER_EDIT' end,
    coalesce(new.updated_at, new.created_at, now())
  )
  returning version_id into new_version_id;

  update knowledge_cards
  set draft_version_id = new_version_id,
      published_version_id = case
        when review_status = 'APPROVED' then new_version_id
        else published_version_id
      end
  where card_id = new.card_id and store_id = new.store_id;

  return new;
end;
$$;

drop trigger if exists trg_knowledge_cards_version_legacy_write on knowledge_cards;
create trigger trg_knowledge_cards_version_legacy_write
after insert or update of title, content on knowledge_cards
for each row execute function askbuddy_version_legacy_card_write();

-- 기존 승인/수정 API는 version_id를 넘기지 않으므로 현재 공개 버전을 채운다.
create or replace function askbuddy_fill_embedding_version()
returns trigger
language plpgsql
as $$
begin
  select published_version_id into new.version_id
  from knowledge_cards
  where store_id = new.store_id and card_id = new.card_id;
  return new;
end;
$$;

drop trigger if exists trg_card_embeddings_fill_version on card_embeddings;
create trigger trg_card_embeddings_fill_version
before insert or update on card_embeddings
for each row execute function askbuddy_fill_embedding_version();

create or replace function askbuddy_mark_guide_completed()
returns trigger
language plpgsql
as $$
begin
  if new.review_status = 'APPROVED' then
    update stores
    set guide_completed_at = coalesce(guide_completed_at, now())
    where store_id = new.store_id
      and guide_completed_at is null;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_knowledge_cards_mark_guide_completed on knowledge_cards;
create trigger trg_knowledge_cards_mark_guide_completed
after insert or update on knowledge_cards
for each row execute function askbuddy_mark_guide_completed();

update stores s
set guide_completed_at = coalesce(
  s.guide_completed_at,
  (
    select min(coalesce(k.updated_at, k.created_at))
    from knowledge_cards k
    where k.store_id = s.store_id and k.review_status = 'APPROVED'
  )
)
where s.guide_completed_at is null
  and exists (
    select 1 from knowledge_cards k
    where k.store_id = s.store_id and k.review_status = 'APPROVED'
  );

-- ---------------------------------------------------------------------
-- 4. 동적 로드맵 · 학습 버전
-- ---------------------------------------------------------------------

alter table roadmap_stages
  add column if not exists category_id bigint references task_categories(category_id) on delete set null,
  add column if not exists is_active boolean not null default true;

alter table roadmap_items
  add column if not exists category_id bigint references task_categories(category_id) on delete set null,
  add column if not exists published_version_id bigint references card_versions(version_id) on delete set null,
  add column if not exists is_active boolean not null default true;

update roadmap_items i
set category_id = k.category_id,
    published_version_id = k.published_version_id,
    is_active = (k.review_status = 'APPROVED')
from knowledge_cards k
where k.card_id = i.card_id;

-- 고정 샘플 항목은 삭제하지 않고 신규 API에서 제외할 수 있게 비활성화한다.
update roadmap_items
set is_active = false
where card_id is null;

create index if not exists idx_roadmap_items_active_card
  on roadmap_items (card_id, category_id)
  where is_active = true;

alter table learning_progress
  add column if not exists completed_version_id bigint references card_versions(version_id) on delete set null,
  add column if not exists reconfirmed_at timestamptz;

alter table learning_progress
  drop constraint if exists learning_progress_status_check;

alter table learning_progress
  alter column status set default 'LOCKED';

alter table learning_progress
  add constraint learning_progress_status_check
  check (status in (
    'LOCKED', 'IN_PROGRESS',
    'NOT_STARTED', 'DONE', 'RECONFIRM_REQUIRED'
  ));

update learning_progress p
set completed_version_id = i.published_version_id
from roadmap_items i
where i.item_id = p.item_id
  and p.status = 'DONE'
  and p.completed_version_id is null
  and i.published_version_id is not null;

-- ---------------------------------------------------------------------
-- 5. 카테고리 재분류
-- ---------------------------------------------------------------------

create table if not exists reclassification_jobs (
  reclass_job_id         bigint generated always as identity primary key,
  store_id               bigint not null references stores(store_id) on delete cascade,
  requested_by           bigint not null references users(user_id) on delete restrict,
  target_category_version int not null check (target_category_version >= 1),
  status                 varchar(20) not null default 'QUEUED'
                         check (status in ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'STALE')),
  total_count            int not null default 0 check (total_count >= 0),
  applied_count          int not null default 0 check (applied_count >= 0),
  skipped_count          int not null default 0 check (skipped_count >= 0),
  failed_count           int not null default 0 check (failed_count >= 0),
  error_code             varchar(80),
  error_message          varchar(1000),
  idempotency_key        varchar(200),
  started_at             timestamptz,
  completed_at           timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  unique (store_id, idempotency_key)
);

create unique index if not exists uq_reclassification_jobs_store_job
  on reclassification_jobs (store_id, reclass_job_id);

create index if not exists idx_reclassification_jobs_store_status
  on reclassification_jobs (store_id, status, created_at desc);

create table if not exists reclassification_results (
  store_id             bigint not null,
  reclass_job_id       bigint not null,
  card_id              bigint not null,
  source_category_id   bigint references task_categories(category_id) on delete set null,
  proposed_category_id bigint references task_categories(category_id) on delete set null,
  card_updated_at_snapshot timestamptz not null,
  result               varchar(30) not null default 'PENDING'
                       check (result in (
                         'PENDING', 'APPLIED', 'SKIPPED_MANUAL',
                         'SKIPPED_NEWER_EDIT', 'FAILED'
                       )),
  reason               varchar(500),
  applied_at           timestamptz,
  created_at           timestamptz not null default now(),
  primary key (reclass_job_id, card_id),
  foreign key (store_id, reclass_job_id)
    references reclassification_jobs(store_id, reclass_job_id) on delete cascade,
  foreign key (store_id, card_id)
    references knowledge_cards(store_id, card_id) on delete cascade
);

create index if not exists idx_reclassification_results_store_result
  on reclassification_results (store_id, result, reclass_job_id);

-- ---------------------------------------------------------------------
-- 6. 앱 알림 · Web Push
-- ---------------------------------------------------------------------

create table if not exists push_subscriptions (
  subscription_id bigint generated always as identity primary key,
  user_id         bigint not null references users(user_id) on delete cascade,
  endpoint        text not null,
  p256dh          text not null,
  auth            text not null,
  user_agent      varchar(500),
  enabled         boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  last_success_at timestamptz,
  last_failure_at timestamptz,
  unique (user_id, endpoint)
);

create index if not exists idx_push_subscriptions_user_enabled
  on push_subscriptions (user_id)
  where enabled = true;

create table if not exists notification_events (
  notification_id  bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  recipient_user_id bigint not null references users(user_id) on delete cascade,
  event_type        varchar(30) not null
                    check (event_type in ('INGEST_COMPLETED', 'PENDING_QUESTION')),
  aggregate_type    varchar(30) not null
                    check (aggregate_type in ('INGEST_JOB', 'PENDING_QUESTION')),
  aggregate_id      bigint not null,
  dedupe_key        varchar(250) not null,
  title             varchar(200) not null,
  body              varchar(500) not null,
  destination       varchar(500) not null,
  status            varchar(20) not null default 'PENDING'
                    check (status in ('PENDING', 'REQUESTED', 'FAILED')),
  read_at           timestamptz,
  created_at        timestamptz not null default now(),
  requested_at      timestamptz,
  unique (recipient_user_id, dedupe_key)
);

create unique index if not exists uq_notification_events_store_notification
  on notification_events (store_id, notification_id);

create index if not exists idx_notification_events_recipient_created
  on notification_events (recipient_user_id, created_at desc);

create index if not exists idx_notification_events_store_unread
  on notification_events (store_id, recipient_user_id, created_at desc)
  where read_at is null;

create table if not exists notification_deliveries (
  delivery_id      bigint generated always as identity primary key,
  store_id         bigint not null references stores(store_id) on delete cascade,
  notification_id  bigint not null,
  subscription_id  bigint not null references push_subscriptions(subscription_id) on delete cascade,
  status           varchar(20) not null default 'PENDING'
                   check (status in ('PENDING', 'REQUESTED', 'FAILED')),
  provider_message varchar(1000),
  attempt_count    int not null default 0 check (attempt_count >= 0),
  requested_at     timestamptz,
  failed_at        timestamptz,
  created_at       timestamptz not null default now(),
  unique (notification_id, subscription_id),
  foreign key (store_id, notification_id)
    references notification_events(store_id, notification_id) on delete cascade
);

create index if not exists idx_notification_deliveries_store_status
  on notification_deliveries (store_id, status, notification_id);

-- ---------------------------------------------------------------------
-- 7. 팀 품질 평가
-- ---------------------------------------------------------------------

create table if not exists quality_evaluations (
  evaluation_id          bigint generated always as identity primary key,
  store_id               bigint not null references stores(store_id) on delete cascade,
  job_id                 bigint not null,
  evaluator_id           bigint not null references users(user_id) on delete restrict,
  evaluated_at           timestamptz not null default now(),
  prompt_version         varchar(100) not null,
  settings               jsonb not null default '{}'::jsonb,
  correct_fact_count     int check (correct_fact_count >= 0),
  evaluated_fact_count   int check (evaluated_fact_count >= 0),
  required_item_count    int check (required_item_count >= 0),
  covered_item_count     int check (covered_item_count >= 0),
  review_duration_sec    int check (review_duration_sec >= 0),
  edited_card_count      int check (edited_card_count >= 0),
  excluded_card_count    int check (excluded_card_count >= 0),
  moved_card_count       int check (moved_card_count >= 0),
  other_appropriate_count int check (other_appropriate_count >= 0),
  other_evaluated_count  int check (other_evaluated_count >= 0),
  roadmap_rating         smallint check (roadmap_rating between 1 and 5),
  notes                  text,
  comparison_group       varchar(100),
  created_at             timestamptz not null default now(),
  foreign key (store_id, job_id)
    references ingest_jobs(store_id, job_id) on delete restrict,
  check (
    correct_fact_count is null
    or evaluated_fact_count is null
    or correct_fact_count <= evaluated_fact_count
  ),
  check (
    covered_item_count is null
    or required_item_count is null
    or covered_item_count <= required_item_count
  ),
  check (
    other_appropriate_count is null
    or other_evaluated_count is null
    or other_appropriate_count <= other_evaluated_count
  )
);

create index if not exists idx_quality_evaluations_store_job
  on quality_evaluations (store_id, job_id, evaluated_at desc);

create index if not exists idx_quality_evaluations_comparison
  on quality_evaluations (store_id, comparison_group, evaluated_at desc);

-- ---------------------------------------------------------------------
-- 8. 검색은 현재 공개 버전의 승인 카드만 사용
-- ---------------------------------------------------------------------

create or replace function match_cards(
  p_store_id  bigint,
  p_embedding vector(1536),
  p_top_k     int default 5
)
returns table (card_id bigint, content text, title varchar, score float)
language sql stable
as $$
  select c.card_id,
         v.content,
         v.title,
         1 - (e.embedding <=> p_embedding) as score
  from card_embeddings e
  join knowledge_cards c
    on c.card_id = e.card_id
   and c.store_id = e.store_id
  join card_versions v
    on v.version_id = c.published_version_id
   and v.store_id = c.store_id
  where e.store_id = p_store_id
    and e.is_stale = false
    and e.version_id = c.published_version_id
    and c.review_status = 'APPROVED'
    and c.is_verified = true
  order by e.embedding <=> p_embedding
  limit p_top_k;
$$;

comment on table ingest_jobs is
  '한 번의 업로드 처리 결과 묶음. 화면 종료 뒤에도 서버에서 계속 처리한다.';
comment on table card_versions is
  '카드 본문 이력. draft_version_id와 published_version_id로 편집과 공개를 분리한다.';
comment on table reclassification_jobs is
  '카테고리 설정 버전별 기존 카드 백그라운드 재분류 작업.';
comment on table notification_events is
  '앱 내부 알림이 정본이며 Web Push 전달 상태·읽음·업무 완료는 서로 분리한다.';
comment on column knowledge_cards.needs_review_reason is
  'APPROVED를 유지하면서도 재확인 표시가 필요할 수 있다. 예: CATEGORY_DELETED.';

commit;
