-- W2-1 — 대상(entity) 도입.
--
-- 사실이 "무엇에 대한" 것인지를 모델이 아니라 서버가 정한다. 대상은 매장마다 따로 있다.
--
-- 규칙:
--   1. 가산 migration 이다. 기존 표·행을 바꾸지 않는다. knowledge_cards.entity_id 는 새 열이며
--      W2 는 새로 만든 카드에만 채운다(기존 카드 이관은 범위 밖).
--   2. 자동 병합은 정규화한 이름이 정확히 같거나 매장 별칭이 같을 때만(서비스 코드). 비슷한 이름은
--      knowledge_entity_candidates 에 PENDING 후보로만 남긴다. 점주가 확정하기 전에는 합치지 않는다.
--   3. 매장 경계 — 모든 참조는 (store_id, entity_id) 복합 FK 다. 다른 매장의 대상을 가리키지 못한다.
--      별칭 유일성도 매장 안에서만이다(같은 이름이 다른 매장에 있어도 무관). RLS 미사용(D1).
--   4. 이력(knowledge_entity_events)은 append-only 다. UPDATE/DELETE 를 트리거가 막는다.
--      fact_revisions 와 같이 매장 cascade 삭제도 막힌다 — 매장 삭제 절차는 W2 범위 밖(C-2 R8).
--   5. 대상 이름·별칭에는 규격(HOT/ICE·사이즈) 낱말을 넣지 않는다. 규격은 사실의 variant 다(D19).

begin;

-- ── 대상 ───────────────────────────────────────────────────────────────────
create table if not exists knowledge_entities (
  entity_id       bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  -- 보이는 이름. 규격 낱말만 뺀 원문
  canonical_name  text   not null check (length(btrim(canonical_name)) > 0),
  -- 만들 때의 정규화 이름(조회는 별칭으로 한다)
  name_norm       text   not null check (name_norm <> ''),
  kind            varchar(20) not null default 'UNKNOWN'
    check (kind in ('MENU', 'INGREDIENT', 'EQUIPMENT', 'TASK', 'POLICY', 'OTHER', 'UNKNOWN')),
  status          varchar(20) not null default 'ACTIVE' check (status in ('ACTIVE', 'MERGED')),
  -- 병합됐으면 살아남은 대상. 같은 매장 안에서만
  merged_into_entity_id bigint,
  created_by      bigint references users(user_id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint uq_knowledge_entities_store_entity unique (store_id, entity_id),
  constraint knowledge_entities_merged_fkey
    foreign key (store_id, merged_into_entity_id) references knowledge_entities(store_id, entity_id),
  constraint knowledge_entities_merged_check
    check ((status = 'MERGED') = (merged_into_entity_id is not null)),
  constraint knowledge_entities_merged_self_check
    check (merged_into_entity_id is null or merged_into_entity_id <> entity_id)
);

-- ── 별칭 ───────────────────────────────────────────────────────────────────
create table if not exists knowledge_entity_aliases (
  alias_id        bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  entity_id       bigint not null,
  -- 조회 열쇠(normalize_subject 결과). 규격 낱말이 없다
  alias_norm      text   not null check (alias_norm <> ''),
  -- 처음 들어온 표기 그대로(되짚기용)
  alias_raw       text   not null,
  -- SYSTEM: 추출 사실에서 자동 생성 · OWNER: 점주가 직접 단 별칭
  origin          varchar(10) not null check (origin in ('SYSTEM', 'OWNER')),
  created_by      bigint references users(user_id) on delete set null,
  created_at      timestamptz not null default now(),
  -- 옮기거나 폐기한 별칭. 행은 지우지 않는다
  retired_at      timestamptz,
  constraint knowledge_entity_aliases_entity_fkey
    foreign key (store_id, entity_id) references knowledge_entities(store_id, entity_id)
);

-- 매장 안에서만 유일, 다른 매장과 무관. 폐기한 별칭은 다시 쓸 수 있다
create unique index if not exists uq_entity_alias_active
  on knowledge_entity_aliases (store_id, alias_norm) where retired_at is null;
create index if not exists idx_entity_alias_entity
  on knowledge_entity_aliases (store_id, entity_id);

-- ── 같은 대상 후보 ──────────────────────────────────────────────────────────
-- "같은 대상일 수 있음" 제안. 자동 병합 금지 — 점주가 확정한다
create table if not exists knowledge_entity_candidates (
  candidate_id    bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  -- 쌍은 작은 id 가 앞. 같은 쌍은 한 행(결정이 난 쌍은 다시 생기지 않는다)
  entity_id_low   bigint not null,
  entity_id_high  bigint not null,
  -- EDIT1: 한 글자 차이 · CONTAINS: 한쪽 이름이 다른 쪽에 포함 · SPLIT: 분리로 생긴 쌍
  reason          varchar(20) not null check (reason in ('EDIT1', 'CONTAINS', 'SPLIT')),
  evidence        jsonb  not null default '{}'::jsonb check (jsonb_typeof(evidence) = 'object'),
  status          varchar(20) not null default 'PENDING'
    check (status in ('PENDING', 'CONFIRMED_SAME', 'CONFIRMED_DIFFERENT', 'DISMISSED')),
  decided_by      bigint references users(user_id) on delete set null,
  decided_at      timestamptz,
  created_at      timestamptz not null default now(),
  constraint uq_knowledge_entity_candidates_pair unique (store_id, entity_id_low, entity_id_high),
  constraint knowledge_entity_candidates_order_check check (entity_id_low < entity_id_high),
  constraint knowledge_entity_candidates_decided_check
    check ((status = 'PENDING') = (decided_at is null)),
  constraint knowledge_entity_candidates_low_fkey
    foreign key (store_id, entity_id_low) references knowledge_entities(store_id, entity_id),
  constraint knowledge_entity_candidates_high_fkey
    foreign key (store_id, entity_id_high) references knowledge_entities(store_id, entity_id)
);

create index if not exists idx_entity_candidates_pending
  on knowledge_entity_candidates (store_id, status, created_at desc);

-- ── 이력 (append-only) ──────────────────────────────────────────────────────
create table if not exists knowledge_entity_events (
  event_id        bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  action          varchar(20) not null check (action in
    ('CREATE', 'ALIAS_ADD', 'ALIAS_RETIRE', 'MERGE', 'SPLIT', 'RELINK_FACT', 'CANDIDATE_DECIDED')),
  entity_id       bigint not null,
  -- 병합·분리·재연결의 상대 대상
  other_entity_id bigint,
  -- 재연결한 사실·판 (표는 W2 ledger migration 에 있다. 여기서는 FK 를 걸지 않는다)
  fact_id         bigint,
  fact_revision_id bigint,
  actor_id        bigint references users(user_id) on delete set null,
  payload         jsonb  not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  constraint knowledge_entity_events_entity_fkey
    foreign key (store_id, entity_id) references knowledge_entities(store_id, entity_id),
  constraint knowledge_entity_events_other_fkey
    foreign key (store_id, other_entity_id) references knowledge_entities(store_id, entity_id)
);

create index if not exists idx_entity_events_store_entity
  on knowledge_entity_events (store_id, entity_id, event_id);

create or replace function askbuddy_entity_event_immutable()
returns trigger language plpgsql as $$
begin
  raise exception '대상 이력은 불변이다 (event_id=%). 새 이력을 더한다', old.event_id;
end;
$$;

drop trigger if exists trg_entity_event_immutable on knowledge_entity_events;
create trigger trg_entity_event_immutable
before update or delete on knowledge_entity_events
for each row execute function askbuddy_entity_event_immutable();

-- ── 카드의 대상 ─────────────────────────────────────────────────────────────
-- 새로 만든 카드에만 채운다. null = 아직 대상이 정해지지 않은 카드(기존 카드 전부)
alter table knowledge_cards add column if not exists entity_id bigint;
alter table knowledge_cards drop constraint if exists knowledge_cards_entity_fkey;
alter table knowledge_cards add constraint knowledge_cards_entity_fkey
  foreign key (store_id, entity_id) references knowledge_entities(store_id, entity_id);
create index if not exists idx_knowledge_cards_store_entity
  on knowledge_cards (store_id, entity_id) where entity_id is not null;

comment on table knowledge_entities is
  '매장별 대상(메뉴·재료·장비·업무). 서버가 이름 규칙으로 정한다 (W2-1)';
comment on table knowledge_entity_aliases is
  '대상 별칭. 활성 별칭은 매장 안에서 유일. 규격 낱말 없음 (W2-1)';
comment on table knowledge_entity_candidates is
  '같은 대상일 수 있는 쌍. 자동 병합하지 않고 점주가 확정한다 (W2-1)';
comment on table knowledge_entity_events is
  '대상 생성·별칭·병합·분리·재연결 이력. append-only (W2-1)';
comment on column knowledge_cards.entity_id is
  '카드가 다루는 대상 (W2). 새 카드에만 채우며 기존 카드는 null';

commit;
