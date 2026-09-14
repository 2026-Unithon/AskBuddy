-- 13.3-1 사실 원장 분리 — 사실의 소유자를 카드에서 자료로 옮긴다.
--
-- 왜:
--   지금은 facts.card_id → knowledge_cards ON DELETE CASCADE 라서 사실이 카드에
--   종속돼 있다. 카드를 다시 만들면 사실도 사라지고, 그래서 '재조립' 이 곧 '전면 교체'
--   가 된다. 점주가 자료를 하나씩 추가할 때마다 승인·수정한 카드가 날아간다.
--
--   사실을 자료 소유로 두면 카드는 사실들의 '현재 조립본(파생물)' 이 된다.
--   새 자료가 와도 영향받는 대상(subject)의 카드만 다시 조립하면 되고,
--   1차 자료의 사실은 원장에 그대로 남는다.
--
-- 하위 호환:
--   기존 facts 테이블을 지우지 않는다 (21-2 — 스키마는 먼저 하위 호환 형태로 적용).
--   코드가 새 표로 옮겨간 뒤 별도 migration 으로 정리한다.
--
-- 격리: RLS 를 쓰지 않으므로(D1) 두 표 모두 store_id 를 필수로 갖는다.

begin;

-- ── 사실 원장 ──────────────────────────────────────────────────────────────
create table if not exists source_facts (
  fact_id       bigint generated always as identity primary key,
  store_id      bigint      not null references stores(store_id) on delete cascade,
  -- 사실의 소유자는 자료다. 자료가 사라지면 사실도 사라지지만, 카드가 사라져도 남는다
  source_id     bigint      not null references sources(source_id) on delete cascade,
  subject       text        not null,
  -- 같은 이름 다른 규격을 가른다. HOT 275ml 와 ICE 225ml 는 다른 사실이다
  variant       varchar(20),
  attribute     text        not null,
  value         text        not null,
  confidence    numeric(5,2) not null default 0
    check (confidence >= 0 and confidence <= 100),
  -- 근거 위치. 영상·음성은 TIMESTAMP, 문서는 PAGE
  locator_type  varchar(20) not null default 'WHOLE_SOURCE'
    check (locator_type in ('PAGE', 'TIMESTAMP', 'LINE', 'WHOLE_SOURCE')),
  locator       jsonb       not null default '{}'::jsonb,
  -- 같은 자료를 다시 넣어도 사실이 중복 적재되지 않게 하는 열쇠
  content_hash  text        not null,
  -- 어느 추출이 만들었나. 프롬프트를 바꾼 뒤 무엇이 달라졌는지 되짚는다
  extract_version varchar(120),
  is_verified   boolean     not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (source_id, content_hash)
);

-- 증분 재조립은 "이 대상을 다루는 사실" 을 찾는 것에서 시작한다
create index if not exists idx_source_facts_store_subject
  on source_facts (store_id, subject);
create index if not exists idx_source_facts_store_source
  on source_facts (store_id, source_id);

-- ── 카드 ↔ 사실 ────────────────────────────────────────────────────────────
-- 카드를 지워도 사실은 남는다. 링크만 끊긴다
create table if not exists card_facts (
  card_id  bigint not null references knowledge_cards(card_id) on delete cascade,
  fact_id  bigint not null references source_facts(fact_id) on delete cascade,
  store_id bigint not null references stores(store_id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (card_id, fact_id)
);

create index if not exists idx_card_facts_store_fact
  on card_facts (store_id, fact_id);

-- ── 사실 내용은 불변 ───────────────────────────────────────────────────────
-- 추출된 사실의 내용은 바뀌지 않는다. 다시 뽑으면 새 행이거나 중복(unique)이다.
-- 검수 표시(is_verified)만 바뀔 수 있다.
create or replace function askbuddy_source_facts_immutable()
returns trigger
language plpgsql
as $$
begin
  if new.subject is distinct from old.subject
     or new.attribute is distinct from old.attribute
     or new.value is distinct from old.value
     or new.variant is distinct from old.variant
     or new.source_id is distinct from old.source_id
     or new.locator is distinct from old.locator then
    raise exception '추출된 사실의 내용은 바꿀 수 없다 (fact_id=%). 다시 뽑으면 새 행이다',
      old.fact_id;
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_source_facts_immutable on source_facts;
create trigger trg_source_facts_immutable
before update on source_facts
for each row execute function askbuddy_source_facts_immutable();

-- ── 기존 facts 이관 ────────────────────────────────────────────────────────
-- card_id 로만 매달려 있던 사실을 source_id 기준으로 옮긴다.
-- 카드에 source_id 가 없는 경우(점주 답변에서 만들어진 카드 등)는 옮기지 않는다 —
-- 원천 자료가 없는 사실이라 원장의 전제를 만족하지 못한다.
insert into source_facts (
  store_id, source_id, subject, attribute, value, confidence,
  locator_type, locator, content_hash, extract_version, is_verified, created_at
)
select
  c.store_id,
  c.source_id,
  f.object_name,
  f.attribute,
  f.value,
  f.confidence,
  'WHOLE_SOURCE',
  '{}'::jsonb,
  encode(sha256(convert_to(
    f.object_name || '|' || f.attribute || '|' || f.value, 'UTF8')), 'hex'),
  'migrated-from-facts',
  f.is_verified,
  coalesce(c.created_at, now())
from facts f
join knowledge_cards c on c.card_id = f.card_id
where c.source_id is not null
on conflict (source_id, content_hash) do nothing;

-- 옮긴 사실과 원래 카드를 잇는다
insert into card_facts (card_id, fact_id, store_id)
select distinct c.card_id, sf.fact_id, c.store_id
from facts f
join knowledge_cards c on c.card_id = f.card_id
join source_facts sf
  on sf.source_id = c.source_id
 and sf.content_hash = encode(sha256(convert_to(
       f.object_name || '|' || f.attribute || '|' || f.value, 'UTF8')), 'hex')
where c.source_id is not null
on conflict (card_id, fact_id) do nothing;

comment on table source_facts is
  '사실 원장. 소유자는 자료이며 카드는 이 사실들의 현재 조립본이다. 13.3-1';
comment on table card_facts is
  '카드가 담은 사실. 카드를 지워도 사실은 남는다. 13.3-1';
comment on table facts is
  'LEGACY — source_facts 로 대체됐다. 코드 이전 후 별도 migration 으로 정리한다 (13.3-1)';

commit;
