-- 사실은 점주가 고칠 수 있어야 한다.
--
-- 카드에서 값이 바뀌면 사실도 같이 바뀌어야 한다. 안 그러면 원장이 거짓이 되고,
-- 사실을 검색에 쓰기 시작하면 틀린 값이 그대로 직원에게 나간다.
--
-- 다만 추출 기록과 현재 사실은 다른 것이다.
--   value           — 추출이 읽어낸 값. 바꾸지 않는다. E-O0 채점의 기준이다
--   corrected_value — 점주가 고친 값. 실제로 쓰이는 값
--
-- value 를 덮어쓰면 추출 품질을 잴 수 없게 된다 — 프롬프트를 고쳐도 좋아졌는지
-- 점주의 수정에 가려 보이지 않는다. 그래서 둘을 나란히 둔다.
-- 덤으로 "모델이 275 라 했는데 점주가 250 으로 고쳤다" 가 기록에 남아
-- 프롬프트 개선의 재료가 된다.

begin;

alter table source_facts
  add column if not exists corrected_value text,
  add column if not exists corrected_at    timestamptz,
  add column if not exists corrected_by    bigint references users(user_id),
  -- 값이 틀린 게 아니라 사실 자체가 무효인 경우 (예: 없어진 메뉴)
  add column if not exists is_superseded   boolean not null default false,
  add column if not exists superseded_at   timestamptz;

comment on column source_facts.value is
  '추출이 읽어낸 원문 값. 불변 — E-O0 채점의 기준이다';
comment on column source_facts.corrected_value is
  '점주가 고친 값. 실제로 쓰이는 값은 coalesce(corrected_value, value) 다';

-- 실제로 쓰이는 값을 한 곳에서 본다. 검색·답변은 이 뷰를 쓰고 채점은 원본을 쓴다
create or replace view effective_facts as
select
  f.fact_id, f.store_id, f.source_id,
  f.subject, f.variant, f.attribute,
  coalesce(f.corrected_value, f.value) as value,
  f.value as extracted_value,
  f.corrected_value is not null as is_corrected,
  f.is_superseded,
  f.confidence, f.locator_type, f.locator,
  f.corrected_at, f.corrected_by, f.created_at
from source_facts f
where f.is_superseded = false;

comment on view effective_facts is
  '점주 수정을 반영한 현재 사실. 검색·답변은 이걸 본다 (13.3-1)';

-- ── 불변 범위를 좁힌다 ─────────────────────────────────────────────────────
-- 추출 원문(value·subject·attribute·variant·locator)은 여전히 못 바꾼다.
-- 점주 수정(corrected_*)과 무효 표시는 허용한다.
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
    raise exception
      '추출 원문은 바꿀 수 없다 (fact_id=%). 값을 고치려면 corrected_value 를 쓴다',
      old.fact_id;
  end if;
  -- 수정·무효 시각은 자동으로 찍는다. 빠뜨리면 언제 바뀌었는지 알 수 없다
  if new.corrected_value is distinct from old.corrected_value
     and new.corrected_value is not null then
    new.corrected_at := now();
  end if;
  if new.is_superseded and not old.is_superseded then
    new.superseded_at := now();
  end if;
  new.updated_at := now();
  return new;
end;
$$;

create index if not exists idx_source_facts_corrected
  on source_facts (store_id, corrected_at desc) where corrected_value is not null;

commit;
