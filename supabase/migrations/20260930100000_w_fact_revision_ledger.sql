-- W2-2 — 원장 사실을 대상·불변 판(fact_revisions)·occurrence 로 잇는다.
--
-- 지금까지 fact_revisions 에는 사실 정체(fact_id)를 발급하는 곳이 없었고, 수집 파이프라인은
-- source_facts(원장)만 썼다. 여기서 사실 정체와 현재 판 포인터, 판마다의 열쇠, 원장↔판 연결,
-- 충돌 표를 더한다.
--
-- 규칙:
--   1. 가산 migration 이다. 기존 표·행·제약을 바꾸거나 완화하지 않는다.
--      fact_occurrences.source_id NOT NULL 은 그대로 둔다(컨트롤러 결정 F). 점주 답변에서 온 판의
--      출처는 fact_revision_meta.owner_answer_id(change_kind=OWNER_ANSWER)에만 남고,
--      fact_occurrences 행은 만들지 않는다. 점주 답변 → 사실 출처는 fact_owner_answer_links 에
--      남는다(결정 H) — 답변이 이미 있는 같은 사실에 이어질 때도 한 행이다.
--   2. fact_revisions.fact_id·entity_id 에는 FK 를 걸지 않는다. R 검증 스크립트가 임의 id 로 판을
--      넣는다(설계 C-2 R1). W 서비스가 같은 트랜잭션에서 knowledge_facts·fact_revision_meta 를
--      함께 써서 짝을 지키고, 검증 스크립트가 짝을 검사한다.
--   3. 같은 사실 = 같은 매장·같은 identity_key. identity_key 는 유일 제약이 아니다 — 정정 뒤 두
--      사실의 값이 같아질 수 있고 그때도 둘 다 남는다(가장 작은 fact_id 로 잇는다).
--   4. 충돌은 두 사실을 모두 남기고 쌍만 적는다. 기본 선택·승자 칸이 없다. 해소는 점주 행동뿐이다.
--   5. 판의 메타(fact_revision_meta)는 판과 같이 불변이다. 매장 경계는 복합 FK 로 막는다(RLS 미사용, D1).
--      owner_answers 에는 store_id 가 없으므로 점주 답변 매장 일치는 트리거로 검사한다
--      (20260927120000 raw_spans 와 같은 방식).

begin;

-- ── 사실 정체 + 현재 판 포인터 (가변) ───────────────────────────────────────
create table if not exists knowledge_facts (
  fact_id           bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  entity_id         bigint not null,
  -- 첫 판을 넣은 직후 같은 트랜잭션에서 채운다. 이후 CAS 로만 옮긴다
  head_revision_id  bigint,
  identity_key      varchar(64) not null,
  slot_key          varchar(64) not null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint uq_knowledge_facts_store_fact unique (store_id, fact_id),
  constraint knowledge_facts_entity_fkey
    foreign key (store_id, entity_id) references knowledge_entities(store_id, entity_id),
  constraint knowledge_facts_head_fkey
    foreign key (store_id, head_revision_id) references fact_revisions(store_id, fact_revision_id)
);

create index if not exists idx_knowledge_facts_identity on knowledge_facts (store_id, identity_key);
create index if not exists idx_knowledge_facts_slot on knowledge_facts (store_id, slot_key);
create index if not exists idx_knowledge_facts_entity on knowledge_facts (store_id, entity_id);

-- ── 판마다 한 행 (불변) ────────────────────────────────────────────────────
create table if not exists fact_revision_meta (
  fact_revision_id  bigint primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  fact_id           bigint not null,
  change_kind       varchar(20) not null check (change_kind in
    ('EXTRACTION', 'OWNER_CORRECTION', 'OWNER_ANSWER', 'RELINK', 'LEGACY_CORRECTION')),
  identity_key      varchar(64) not null,
  slot_key          varchar(64) not null,
  -- 알 수 없는 규격 낱말. 공개 판 필드가 없어 slot 열쇠에만 쓴다
  variant_other     text,
  -- 적용 시점(정정이 효력을 갖는 때). created_at 과 구분한다
  applied_at        timestamptz not null default now(),
  reason            text,
  -- 점주 답변에서 온 판의 출처. 파일 출처(fact_occurrences)는 만들지 않는다
  owner_answer_id   bigint references owner_answers(answer_id) on delete restrict,
  -- LEGACY_CORRECTION 의 이관 입력(source_facts.fact_id)
  legacy_source_fact_id bigint,
  created_at        timestamptz not null default now(),
  constraint fact_revision_meta_revision_fkey
    foreign key (store_id, fact_revision_id) references fact_revisions(store_id, fact_revision_id),
  constraint fact_revision_meta_fact_fkey
    foreign key (store_id, fact_id) references knowledge_facts(store_id, fact_id)
);

create unique index if not exists uq_fact_revision_meta_legacy
  on fact_revision_meta (store_id, legacy_source_fact_id)
  where legacy_source_fact_id is not null;
create index if not exists idx_fact_revision_meta_fact
  on fact_revision_meta (store_id, fact_id);

create or replace function askbuddy_fact_revision_meta_immutable()
returns trigger language plpgsql as $$
begin
  raise exception '사실 판 메타는 불변이다 (fact_revision_id=%). 수정은 새 판이다',
    old.fact_revision_id;
end;
$$;

drop trigger if exists trg_fact_revision_meta_immutable on fact_revision_meta;
create trigger trg_fact_revision_meta_immutable
before update or delete on fact_revision_meta
for each row execute function askbuddy_fact_revision_meta_immutable();

-- 점주 답변 매장 일치 (owner_answers → pending_questions.store_id)
create or replace function askbuddy_fact_revision_meta_owner_answer_store_check()
returns trigger language plpgsql as $$
declare
  answer_store_id bigint;
begin
  if new.owner_answer_id is not null then
    select pq.store_id into answer_store_id
    from owner_answers oa
    join pending_questions pq on pq.question_id = oa.question_id
    where oa.answer_id = new.owner_answer_id;

    if answer_store_id is null then
      raise exception '판 메타가 가리키는 점주 답변(answer_id=%)이 없다', new.owner_answer_id;
    end if;

    if answer_store_id <> new.store_id then
      raise exception '판 메타의 매장(%)과 점주 답변의 매장(%)이 다르다',
        new.store_id, answer_store_id;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_fact_revision_meta_owner_answer_store_check on fact_revision_meta;
create trigger trg_fact_revision_meta_owner_answer_store_check
before insert on fact_revision_meta
for each row execute function askbuddy_fact_revision_meta_owner_answer_store_check();

-- ── 점주 답변 → 사실 출처 연결 (컨트롤러 결정 H) ─────────────────────────────
-- 점주 답변이 새 사실을 만들 때도, 이미 있는 같은 사실에 이어질 때도 한 행을 남긴다.
-- fact_occurrences 는 파일 출처 전용으로 두고(결정 F) 점주 출처는 여기에만 있다
create table if not exists fact_owner_answer_links (
  link_id           bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  fact_id           bigint not null,
  -- 이을 때의 판(새 사실이면 그 첫 판, 같은 사실이면 그때의 head)
  fact_revision_id  bigint not null,
  owner_answer_id   bigint not null references owner_answers(answer_id) on delete restrict,
  created_at        timestamptz not null default now(),
  constraint uq_fact_owner_answer_links unique (store_id, fact_id, owner_answer_id),
  constraint fact_owner_answer_links_fact_fkey
    foreign key (store_id, fact_id) references knowledge_facts(store_id, fact_id),
  constraint fact_owner_answer_links_revision_fkey
    foreign key (store_id, fact_revision_id) references fact_revisions(store_id, fact_revision_id)
);

create index if not exists idx_fact_owner_answer_links_answer
  on fact_owner_answer_links (store_id, owner_answer_id);

-- owner_answers 에는 store_id 가 없다. 매장 일치는 pending_questions 경유로 검사한다
create or replace function askbuddy_fact_owner_answer_link_store_check()
returns trigger language plpgsql as $$
declare
  answer_store_id bigint;
begin
  select pq.store_id into answer_store_id
  from owner_answers oa
  join pending_questions pq on pq.question_id = oa.question_id
  where oa.answer_id = new.owner_answer_id;

  if answer_store_id is null then
    raise exception '사실 출처가 가리키는 점주 답변(answer_id=%)이 없다', new.owner_answer_id;
  end if;

  if answer_store_id <> new.store_id then
    raise exception '사실 출처의 매장(%)과 점주 답변의 매장(%)이 다르다',
      new.store_id, answer_store_id;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_fact_owner_answer_link_store_check on fact_owner_answer_links;
create trigger trg_fact_owner_answer_link_store_check
before insert or update on fact_owner_answer_links
for each row execute function askbuddy_fact_owner_answer_link_store_check();

-- ── 원장 ↔ 판 연결 (원장 사실 하나 = 연결 하나)─────────────────────────────
create table if not exists source_fact_revision_links (
  store_id          bigint not null references stores(store_id) on delete cascade,
  source_fact_id    bigint not null,
  fact_id           bigint not null,
  fact_revision_id  bigint not null,
  entity_id         bigint not null,
  -- CREATED: 이 원장 사실이 판을 만들었다 · MATCHED: 이미 있던 같은 사실에 이었다
  link_kind         varchar(10) not null check (link_kind in ('CREATED', 'MATCHED')),
  created_at        timestamptz not null default now(),
  primary key (store_id, source_fact_id),
  constraint source_fact_revision_links_source_fact_fkey
    foreign key (store_id, source_fact_id) references source_facts(store_id, fact_id)
    on delete cascade,
  constraint source_fact_revision_links_fact_fkey
    foreign key (store_id, fact_id) references knowledge_facts(store_id, fact_id),
  constraint source_fact_revision_links_revision_fkey
    foreign key (store_id, fact_revision_id) references fact_revisions(store_id, fact_revision_id)
);

create index if not exists idx_sf_revision_links_fact
  on source_fact_revision_links (store_id, fact_id);

-- ── 충돌 (같은 slot, 다른 identity) ─────────────────────────────────────────
create table if not exists fact_conflicts (
  conflict_id       bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  entity_id         bigint not null,
  slot_key          varchar(64) not null,
  fact_id_low       bigint not null,
  fact_id_high      bigint not null,
  value_kind        varchar(10) not null check (value_kind in ('NUMERIC', 'TEXT', 'MIXED')),
  status            varchar(20) not null default 'OPEN'
    check (status in ('OPEN', 'RESOLVED', 'DISMISSED', 'OBSOLETE')),
  resolution        jsonb,
  decided_by        bigint references users(user_id) on delete set null,
  detected_at       timestamptz not null default now(),
  decided_at        timestamptz,
  constraint fact_conflicts_order_check check (fact_id_low < fact_id_high),
  constraint fact_conflicts_low_fkey
    foreign key (store_id, fact_id_low) references knowledge_facts(store_id, fact_id),
  constraint fact_conflicts_high_fkey
    foreign key (store_id, fact_id_high) references knowledge_facts(store_id, fact_id),
  constraint fact_conflicts_entity_fkey
    foreign key (store_id, entity_id) references knowledge_entities(store_id, entity_id)
);

create index if not exists idx_fact_conflicts_open
  on fact_conflicts (store_id, entity_id, slot_key) where status = 'OPEN';
-- 한 쌍의 OPEN 충돌은 하나뿐이다. 결정된 행(RESOLVED·DISMISSED·OBSOLETE)은 이력으로 남고,
-- 정정(W2-3)으로 두 값이 다시 갈라지면 같은 쌍에 새 OPEN 행이 생긴다
create unique index if not exists uq_fact_conflicts_open_pair
  on fact_conflicts (store_id, fact_id_low, fact_id_high) where status = 'OPEN';
create index if not exists idx_fact_conflicts_pair
  on fact_conflicts (store_id, fact_id_low, fact_id_high);

-- ── M1 fact_occurrences 가산 확장 ──────────────────────────────────────────
-- 복합 FK 의 부모 키. occurrence_id 가 이미 PK 라 값의 뜻은 바뀌지 않는다
create unique index if not exists uq_source_fact_occurrences_store_occ
  on source_fact_occurrences (store_id, occurrence_id);

-- 원장 위치 한 행 → 판 occurrence 한 행. 재처리해도 늘지 않게 하는 열쇠다
alter table fact_occurrences add column if not exists source_fact_occurrence_id bigint;
alter table fact_occurrences drop constraint if exists fact_occurrences_sfo_fkey;
alter table fact_occurrences add constraint fact_occurrences_sfo_fkey
  foreign key (store_id, source_fact_occurrence_id)
  references source_fact_occurrences(store_id, occurrence_id)
  on delete set null (source_fact_occurrence_id);
create unique index if not exists uq_fact_occurrences_sfo
  on fact_occurrences (store_id, source_fact_occurrence_id)
  where source_fact_occurrence_id is not null;

comment on table knowledge_facts is
  '사실 정체(fact_id 발급) + 현재 판 포인터. 같은 사실 = 같은 identity_key (W2-2)';
comment on table fact_revision_meta is
  '판마다 한 행. 변경 종류·열쇠·미상 규격·점주 답변 출처. 불변 (W2-2)';
comment on table fact_owner_answer_links is
  '점주 답변 → 사실 출처. 새 사실·같은 사실 모두 한 행 (W2-2, 결정 H)';
comment on table source_fact_revision_links is
  '원장 사실 → 판 연결. CREATED/MATCHED (W2-2)';
comment on table fact_conflicts is
  '같은 slot 의 다른 값 쌍. 두 사실 모두 남기며 기본 선택이 없다 (W2-2)';
comment on column fact_occurrences.source_fact_occurrence_id is
  '이 occurrence 를 만든 원장 위치(source_fact_occurrences). 재처리 중복 방지 (W2-2)';

commit;
