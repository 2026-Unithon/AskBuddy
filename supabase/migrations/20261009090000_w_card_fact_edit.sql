-- W3b — 점주 카드 사실 편집 기반.
--
-- 목적: 카드 화면에서 점주가 사실 한 줄을 고치거나 더한 기록과 출처를 남길 자리를 만든다.
--   1. fact_revision_meta.change_kind 에 'OWNER_ADD' (점주가 새로 더한 사실) 를 허용한다.
--   2. sources.source_type 에 'OWNER_TEXT' (점주 직접 입력, 파일 없음) 를 허용한다.
--   3. OWNER_TEXT 자료는 추출 작업(ingest_jobs)을 만들지 않도록 레거시 작업 생성 트리거 함수에 분기를 더한다.
--   4. card_fact_edits: 편집 요청 한 건의 멱등 기록(불변).
--   5. fact_occurrences 의 카드별 조회 인덱스.
--
-- 규칙:
--   - 가산 migration 이다. check 는 넓히기만 하고 기존 허용값을 모두 유지한다.
--   - 트리거 함수는 OWNER_TEXT 분기만 추가한다. 나머지 본문은 20260910133000_mvp_contract_v1.sql 과 같다.
--     트리거 정의는 다시 만들지 않는다.
--   - 다시 적용해도 안전하다.
--   - 제약 이름은 재구축 DB 의 pg_constraint 로 확인했다
--     (fact_revision_meta_change_kind_check, sources_source_type_check).
--
-- 배포 순서: 이 migration 을 서버보다 먼저 적용한다. 서버가 먼저 나가면 OWNER_ADD·OWNER_TEXT 쓰기가 check 에 막힌다.

begin;

-- ── 1. change_kind 넓히기 ──────────────────────────────────────────────────
alter table fact_revision_meta drop constraint if exists fact_revision_meta_change_kind_check;
alter table fact_revision_meta add constraint fact_revision_meta_change_kind_check
  check (change_kind in
    ('EXTRACTION', 'OWNER_CORRECTION', 'OWNER_ANSWER', 'RELINK', 'LEGACY_CORRECTION', 'OWNER_ADD'));

-- ── 2. source_type 넓히기 ──────────────────────────────────────────────────
alter table sources drop constraint if exists sources_source_type_check;
alter table sources add constraint sources_source_type_check
  check (source_type in ('VOICE', 'VIDEO', 'KAKAO', 'SCAN', 'OWNER_TEXT'));

-- ── 3. 레거시 작업 생성 트리거 함수: OWNER_TEXT 는 작업을 만들지 않는다 ───────────
create or replace function askbuddy_create_legacy_ingest_job()
returns trigger
language plpgsql
as $$
declare
  new_job_id bigint;
  current_category_version int;
begin
  -- 점주가 카드 화면에서 직접 적은 글은 파일이 아니므로 추출 작업을 만들지 않는다
  if new.source_type = 'OWNER_TEXT' then
    return new;
  end if;

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

-- ── 4. 카드 사실 편집 기록 ─────────────────────────────────────────────────
create table if not exists card_fact_edits (
  edit_id              bigint generated always as identity primary key,
  store_id             bigint not null references stores(store_id) on delete cascade,
  card_id              bigint not null,
  idempotency_key      varchar(80) not null,
  request_hash         varchar(64) not null,
  from_version_id      bigint not null,
  to_version_id        bigint,
  changed              boolean not null,
  owner_text_source_id bigint,
  owner_text           text,
  result               jsonb not null check (jsonb_typeof(result) = 'object'),
  actor_id             bigint not null references users(user_id) on delete restrict,
  created_at           timestamptz not null default now(),
  constraint uq_card_fact_edits_key unique (store_id, card_id, idempotency_key),
  constraint card_fact_edits_card_fkey foreign key (store_id, card_id)
    references knowledge_cards(store_id, card_id) on delete cascade,
  constraint card_fact_edits_from_fkey foreign key (store_id, from_version_id)
    references card_versions(store_id, version_id) on delete cascade,
  constraint card_fact_edits_to_fkey foreign key (store_id, to_version_id)
    references card_versions(store_id, version_id) on delete cascade,
  -- D20: 자료 FK 에 cascade 를 두지 않는다
  constraint card_fact_edits_source_fkey foreign key (store_id, owner_text_source_id)
    references sources(store_id, source_id),
  constraint card_fact_edits_changed_check check (changed = (to_version_id is not null)),
  constraint card_fact_edits_text_check check ((owner_text_source_id is null) = (owner_text is null))
);

comment on table card_fact_edits is '점주가 카드 화면에서 사실을 고친 요청 한 건의 기록. 같은 멱등 키 재요청에는 저장한 결과를 그대로 돌려준다. 수정 불가.';
comment on column card_fact_edits.idempotency_key is '화면이 요청마다 만든 키. 같은 매장·카드에서 유일';
comment on column card_fact_edits.request_hash is '요청 본문(키 제외)의 SHA-256. 같은 키에 다른 본문이 오면 거절하는 데 쓴다';
comment on column card_fact_edits.from_version_id is '편집 전 초안 판';
comment on column card_fact_edits.to_version_id is '편집 뒤 새 초안 판. 바뀐 것이 없으면 null';
comment on column card_fact_edits.changed is '새 판이 만들어졌는지';
comment on column card_fact_edits.owner_text_source_id is '점주 직접 입력 자료(OWNER_TEXT). 새·고친 사실이 없으면 null';
comment on column card_fact_edits.owner_text is '점주 직접 입력 자료의 전문(새·고친 문장을 줄마다)';
comment on column card_fact_edits.result is '응답 본문. 재요청 때 그대로 돌려준다';

create or replace function askbuddy_card_fact_edits_immutable()
returns trigger language plpgsql as $$
begin
  raise exception '카드 사실 편집 기록은 불변이다 (edit_id=%)', old.edit_id;
end;
$$;

drop trigger if exists trg_card_fact_edits_immutable on card_fact_edits;
create trigger trg_card_fact_edits_immutable
before update on card_fact_edits
for each row execute function askbuddy_card_fact_edits_immutable();

-- ── 5. 카드별 연결된 occurrence 조회 ────────────────────────────────────────
create index if not exists idx_fact_occurrences_store_card_linked
  on fact_occurrences (store_id, card_id) where disposition = 'LINKED';

commit;
