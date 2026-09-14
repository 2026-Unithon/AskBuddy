-- M1 사실 판·occurrence·원문 구간·발행 manifest (C0 결정서 §3, CP-04)
--
-- 무엇이 달라지는가:
--   지금 source_facts 는 사실 하나에 값 하나다. 값을 고치면 옛 값이 사라져
--   이미 나간 답변의 인용이 말없이 바뀐다. 여기서 **판(revision)** 을 도입한다 —
--   수정은 덮어쓰기가 아니라 새 판이고, 옛 판은 그대로 남아 과거 인용이 재현된다.
--
--   occurrence 를 따로 둔다. 같은 사실이 자료 세 곳에 나오면 근거도 세 개다.
--   사실 단위로만 적으면 "세 번 나왔고 두 번은 제외했다" 가 한 줄로 뭉개진다 (RV-08).
--
-- D20 자료 삭제:
--   기존 source_facts.source_id 가 ON DELETE CASCADE 라 자료를 지우면 사실이
--   함께 사라진다. 그러면 이미 나간 답변의 근거가 통째로 없어진다.
--   여기서 보존 FK 로 바꾸고 자료는 tombstone 으로 남긴다 (RV-11).
--   적용된 migration 을 고치지 않고 제약만 교체한다.
--
-- 격리: 매장 경계를 넘는 참조를 composite FK 로 막는다. API 검증과 이중으로 건다.

begin;

-- ── 자료 tombstone ────────────────────────────────────────────────────────
alter table sources add column if not exists source_availability varchar(20)
  not null default 'AVAILABLE'
  check (source_availability in ('AVAILABLE', 'DELETED', 'UNAVAILABLE'));
alter table sources add column if not exists deleted_at timestamptz;

-- 일시 장애(UNAVAILABLE)를 삭제(DELETED)로 기록하지 않는다 (§4.4)
alter table sources drop constraint if exists sources_deleted_at_matches_state;
alter table sources add constraint sources_deleted_at_matches_state
  check ((source_availability = 'DELETED') = (deleted_at is not null));

-- 매장 경계를 넘는 참조를 막을 부모 키는 이미 있다
-- (20260910133000 의 uq_sources_store_source unique index). 아래 FK 가 그걸 쓴다.

-- RV-11 — 사실이 자료 삭제에 딸려 사라지지 않게 한다.
-- 삭제는 tombstone 서비스가 하고, 물리 삭제는 사실이 없을 때만 가능하다
alter table source_facts drop constraint if exists source_facts_source_id_fkey;
alter table source_facts add constraint source_facts_source_id_fkey
  foreign key (source_id) references sources(source_id) on delete restrict;

-- ── 사실 판 ────────────────────────────────────────────────────────────────
create table if not exists fact_revisions (
  fact_revision_id  bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  -- 판이 바뀌어도 따라다니는 사실의 정체
  fact_id           bigint not null,
  -- 어느 대상에 대한 사실인가. 카드와 같은 축이어야 재분류가 가능하다
  entity_id         bigint not null,
  -- 원문이 권위 기준이다. 공백을 정규화하지 않는다 (RV-07)
  original_assertion text  not null,
  assertion         text   not null,
  subject           text,
  predicate         text,
  variant_temperature varchar(10) check (variant_temperature in ('HOT', 'ICE')),
  variant_size      varchar(20),
  quantity_value    numeric,
  quantity_unit     varchar(20),
  value_text        text,
  polarity          varchar(10) not null default 'AFFIRM'
    check (polarity in ('AFFIRM', 'NEGATE')),
  step_order        int check (step_order >= 1),
  conditions        jsonb not null default '[]'::jsonb,
  exceptions        jsonb not null default '[]'::jsonb,
  -- 정정 이력. 새 판이 옛 판을 잇는다. 옛 판은 지우지 않는다
  supersedes_revision_id bigint references fact_revisions(fact_revision_id),
  created_by        bigint references users(user_id) on delete set null,
  created_at        timestamptz not null default now(),
  unique (store_id, fact_revision_id),
  -- 수치와 서술값을 동시에 두지 않는다 (계약과 같은 규칙)
  check (quantity_value is null or value_text is null)
);

create index if not exists idx_fact_revisions_store_fact
  on fact_revisions (store_id, fact_id);
create index if not exists idx_fact_revisions_store_entity
  on fact_revisions (store_id, entity_id);

-- 승인된 판은 불변이다. 고치려면 새 판을 넣는다
create or replace function askbuddy_fact_revision_immutable()
returns trigger language plpgsql as $$
begin
  raise exception '사실 판은 불변이다 (fact_revision_id=%). 수정은 새 판이다',
    old.fact_revision_id;
end;
$$;

drop trigger if exists trg_fact_revision_immutable on fact_revisions;
create trigger trg_fact_revision_immutable
before update or delete on fact_revisions
for each row execute function askbuddy_fact_revision_immutable();

-- 선행 관계. 순환은 API 계약이 막고, 여기서는 자기참조와 매장 이탈을 막는다
create table if not exists fact_revision_requires (
  store_id          bigint not null,
  fact_revision_id  bigint not null,
  requires_revision_id bigint not null,
  primary key (fact_revision_id, requires_revision_id),
  check (fact_revision_id <> requires_revision_id),
  foreign key (store_id, fact_revision_id)
    references fact_revisions (store_id, fact_revision_id) on delete cascade,
  foreign key (store_id, requires_revision_id)
    references fact_revisions (store_id, fact_revision_id) on delete cascade
);

-- ── occurrence ────────────────────────────────────────────────────────────
create table if not exists fact_occurrences (
  occurrence_id     bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  source_id         bigint not null,
  fact_revision_id  bigint,
  locator_type      varchar(20) not null default 'WHOLE_SOURCE'
    check (locator_type in ('PAGE', 'TIMESTAMP', 'LINE', 'BBOX', 'WHOLE_SOURCE')),
  locator           jsonb not null default '{}'::jsonb,
  -- 자료 내용의 지문. 자료를 지워도 어느 판본에서 나온 말인지 대조한다
  source_content_hash text,
  disposition       varchar(20) not null default 'REVIEW_PENDING'
    check (disposition in ('LINKED', 'REVIEW_PENDING', 'EXCLUDED')),
  reason            text,
  card_id           bigint,
  block_id          varchar(40),
  decided_by        bigint references users(user_id) on delete set null,
  decided_at        timestamptz,
  created_at        timestamptz not null default now(),
  unique (store_id, occurrence_id),
  -- 자료를 지워도 근거는 남는다 (D20)
  foreign key (store_id, source_id)
    references sources (store_id, source_id) on delete restrict,
  foreign key (store_id, fact_revision_id)
    references fact_revisions (store_id, fact_revision_id),
  -- 이유 없는 보류·제외를 남기지 않는다
  check (disposition = 'LINKED' or reason is not null),
  check (disposition <> 'LINKED'
         or (fact_revision_id is not null and card_id is not null
             and block_id is not null))
);

create index if not exists idx_fact_occurrences_store_revision
  on fact_occurrences (store_id, fact_revision_id);

-- ── 원문 구간 ──────────────────────────────────────────────────────────────
-- typed 로 쪼개지 않고 승인된 원문 그대로 (RV-05)
create table if not exists raw_spans (
  raw_span_id  bigint generated always as identity primary key,
  store_id     bigint not null references stores(store_id) on delete cascade,
  source_id    bigint not null,
  span_text    text   not null,
  locator_type varchar(20) not null default 'WHOLE_SOURCE',
  locator      jsonb  not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  unique (store_id, raw_span_id),
  foreign key (store_id, source_id)
    references sources (store_id, source_id) on delete restrict
);

-- ── 카드 버전의 블록 ───────────────────────────────────────────────────────
create table if not exists card_version_blocks (
  store_id        bigint not null references stores(store_id) on delete cascade,
  card_version_id bigint not null,
  block_id        varchar(40) not null,
  kind            varchar(20) not null
    check (kind in ('QUANTITIES', 'STEPS', 'NOTES', 'RAW')),
  -- 리스트 순서에 기대지 않는다. 순서가 바뀌면 절차가 달라진다 (RV-06)
  block_order     int not null check (block_order >= 1),
  raw_span_id     bigint,
  primary key (store_id, card_version_id, block_id),
  unique (store_id, card_version_id, block_order),
  foreign key (store_id, raw_span_id)
    references raw_spans (store_id, raw_span_id),
  -- 원문 구간은 RAW 블록에서만 쓴다
  check (raw_span_id is null or kind = 'RAW')
);

create table if not exists card_block_facts (
  store_id         bigint not null,
  card_version_id  bigint not null,
  block_id         varchar(40) not null,
  fact_revision_id bigint not null,
  position         int not null check (position >= 1),
  primary key (store_id, card_version_id, block_id, fact_revision_id),
  unique (store_id, card_version_id, block_id, position),
  foreign key (store_id, card_version_id, block_id)
    references card_version_blocks (store_id, card_version_id, block_id)
    on delete cascade,
  -- 다른 매장의 사실을 블록에 담을 수 없다. API 검증과 이중으로 건다
  foreign key (store_id, fact_revision_id)
    references fact_revisions (store_id, fact_revision_id)
);

-- ── 발행 manifest ──────────────────────────────────────────────────────────
-- 발행 경합은 이 행을 잠그고 판단한다. 잠금 순서는 publication → card → session
create table if not exists knowledge_publications (
  store_id             bigint primary key references stores(store_id) on delete cascade,
  publication_revision bigint not null default 0,
  knowledge_revision   bigint not null default 0,
  index_revision       bigint not null default 0,
  current_snapshot_id  bigint,
  updated_at           timestamptz not null default now()
);

create table if not exists knowledge_snapshots (
  snapshot_id        bigint generated always as identity primary key,
  store_id           bigint not null references stores(store_id) on delete cascade,
  knowledge_revision bigint not null,
  -- `sha256:<64 hex>`. canonical payload 로 계산한다 (§3.4)
  snapshot_hash      text   not null check (snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
  glossary_version   varchar(40) not null,
  renderer_version   varchar(40) not null,
  created_at         timestamptz not null default now(),
  unique (store_id, knowledge_revision),
  unique (store_id, snapshot_id)
);

-- 발행된 판은 불변이다. 고치면 과거 인용의 재현이 끊긴다
create or replace function askbuddy_snapshot_immutable()
returns trigger language plpgsql as $$
begin
  raise exception '발행된 snapshot 은 불변이다 (snapshot_id=%). 새 판을 발행한다',
    old.snapshot_id;
end;
$$;

drop trigger if exists trg_snapshot_immutable on knowledge_snapshots;
create trigger trg_snapshot_immutable
before update or delete on knowledge_snapshots
for each row execute function askbuddy_snapshot_immutable();

-- 어느 카드 버전이 그 판에 실렸는가
create table if not exists snapshot_card_versions (
  store_id        bigint not null,
  snapshot_id     bigint not null,
  card_id         bigint not null,
  card_version_id bigint not null,
  primary key (store_id, snapshot_id, card_id),
  foreign key (store_id, snapshot_id)
    references knowledge_snapshots (store_id, snapshot_id) on delete cascade
);

alter table knowledge_publications
  drop constraint if exists knowledge_publications_snapshot_fkey;
alter table knowledge_publications
  add constraint knowledge_publications_snapshot_fkey
  foreign key (store_id, current_snapshot_id)
  references knowledge_snapshots (store_id, snapshot_id);

comment on table fact_revisions is
  '사실의 판. 불변이며 수정은 새 판이다. 옛 판이 남아야 과거 인용이 재현된다 (M1 §3.2)';
comment on table fact_occurrences is
  '사실이 자료의 어디에 나왔는가. 판정의 주체는 occurrence 다 (M1 RV-08)';
comment on table raw_spans is
  'typed 로 쪼개지 않고 승인된 원문 구간. RAW 블록이 가리킨다 (M1 RV-05)';
comment on table knowledge_publications is
  '매장의 공개 상태. 발행 경합은 이 행을 잠그고 판단한다 (M1 §4.2)';
comment on column sources.source_availability is
  '자료를 지워도 사실·인용은 남는다. tombstone 으로 표시한다 (M1 D20)';

commit;
