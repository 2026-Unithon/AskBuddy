-- W3a — 사실 카드 판의 블록·근거 고정 (대상 단위 사실 조립).
--
-- 사실 카드 판(card_versions)은 블록(card_version_blocks)·블록 사실(card_block_facts)을 고정한다.
-- 여기서는 그 판이 검수한 사실 판마다 "그때의 근거"(파일 occurrence 또는 점주 답변)를
-- 판과 함께 얼리는 표를 더한다. 뒤에 occurrence 처분이 바뀌어도 판의 근거는 바뀌지 않는다.
--
-- 규칙:
--   1. 가산 migration 이다. 기존 표·행·제약을 바꾸거나 완화하지 않는다.
--   2. 근거 행은 불변이다. UPDATE 를 막는다. 삭제는 카드 판 cascade 를 위해 막지 않는다.
--   3. 매장 경계는 복합 FK 로 막는다(RLS 미사용, D1). owner_answers 에는 store_id 가 없으므로
--      점주 답변 매장 일치는 트리거로 검사한다(20260930100000 fact_owner_answer_links 와 같은 방식).

begin;

create table if not exists card_version_fact_provenance (
  provenance_id    bigint generated always as identity primary key,
  store_id         bigint not null references stores(store_id) on delete cascade,
  card_version_id  bigint not null,
  fact_revision_id bigint not null,
  occurrence_id    bigint,
  owner_answer_id  bigint references owner_answers(answer_id) on delete restrict,
  created_at       timestamptz not null default now(),
  -- 근거는 파일 occurrence 또는 점주 답변 둘 중 정확히 하나다
  constraint card_version_fact_provenance_one_origin
    check ((occurrence_id is null) <> (owner_answer_id is null)),
  constraint card_version_fact_provenance_version_fkey
    foreign key (store_id, card_version_id) references card_versions(store_id, version_id)
    on delete cascade,
  constraint card_version_fact_provenance_revision_fkey
    foreign key (store_id, fact_revision_id) references fact_revisions(store_id, fact_revision_id),
  constraint card_version_fact_provenance_occurrence_fkey
    foreign key (store_id, occurrence_id) references fact_occurrences(store_id, occurrence_id)
);

create unique index if not exists uq_cvfp_occurrence on card_version_fact_provenance
  (store_id, card_version_id, fact_revision_id, occurrence_id) where occurrence_id is not null;
create unique index if not exists uq_cvfp_owner on card_version_fact_provenance
  (store_id, card_version_id, fact_revision_id, owner_answer_id) where owner_answer_id is not null;

-- 판과 함께 얼린다. 고치려면 새 카드 판을 만든다
create or replace function askbuddy_card_version_fact_provenance_immutable()
returns trigger language plpgsql as $$
begin
  raise exception '카드 판 근거는 불변이다 (provenance_id=%). 수정은 새 카드 판이다',
    old.provenance_id;
end;
$$;

drop trigger if exists trg_card_version_fact_provenance_immutable on card_version_fact_provenance;
create trigger trg_card_version_fact_provenance_immutable
before update on card_version_fact_provenance
for each row execute function askbuddy_card_version_fact_provenance_immutable();

-- 점주 답변 매장 일치 (owner_answers → pending_questions.store_id)
create or replace function askbuddy_card_version_fact_provenance_owner_store_check()
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
      raise exception '카드 판 근거가 가리키는 점주 답변(answer_id=%)이 없다', new.owner_answer_id;
    end if;

    if answer_store_id <> new.store_id then
      raise exception '카드 판 근거의 매장(%)과 점주 답변의 매장(%)이 다르다',
        new.store_id, answer_store_id;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_card_version_fact_provenance_owner_store_check
  on card_version_fact_provenance;
create trigger trg_card_version_fact_provenance_owner_store_check
before insert on card_version_fact_provenance
for each row execute function askbuddy_card_version_fact_provenance_owner_store_check();

-- 자료별 처분 집계·사실 판별 블록 조회
create index if not exists idx_fact_occurrences_store_source
  on fact_occurrences (store_id, source_id);
create index if not exists idx_card_block_facts_store_revision
  on card_block_facts (store_id, fact_revision_id);

comment on table card_version_fact_provenance is
  '사실 카드 판이 검수한 사실 판마다 그때의 근거(occurrence 또는 점주 답변). 판과 함께 얼린다 (W3a)';

commit;
