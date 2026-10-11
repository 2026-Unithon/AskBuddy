-- Phase A — 점주 답변을 사실로 바꾸기 위한 파일 없는 자료(OWNER_TEXT) 연결.
-- 답변 하나에 자료 하나. 근거는 그 자료의 occurrence(source_id + occurrence_id)로 공개된다.
-- 가산 변경만 한다.
create table if not exists owner_answer_sources (
  store_id bigint not null references stores(store_id),
  owner_answer_id bigint not null references owner_answers(answer_id) on delete restrict,
  source_id bigint not null references sources(source_id) on delete restrict,
  created_at timestamptz not null default now(),
  primary key (store_id, owner_answer_id),
  unique (source_id)
);

create or replace function askbuddy_owner_answer_source_store_check()
returns trigger language plpgsql as $$
begin
  -- 답변·자료가 모두 이 매장 것이어야 한다(D1). owner_answers 는 store_id 가 없어 질문을 거친다
  if not exists (select 1 from owner_answers oa join pending_questions pq on pq.question_id = oa.question_id
                 where oa.answer_id = new.owner_answer_id and pq.store_id = new.store_id)
     or not exists (select 1 from sources s where s.source_id = new.source_id
                    and s.store_id = new.store_id and s.source_type = 'OWNER_TEXT') then
    raise exception '점주 답변 자료 연결의 매장이 맞지 않는다 (store=%, answer=%, source=%)',
      new.store_id, new.owner_answer_id, new.source_id;
  end if;
  return new;
end $$;

drop trigger if exists trg_owner_answer_source_store_check on owner_answer_sources;
create trigger trg_owner_answer_source_store_check
before insert or update on owner_answer_sources
for each row execute function askbuddy_owner_answer_source_store_check();

comment on table owner_answer_sources is '점주 답변 → 사실 수집용 OWNER_TEXT 자료 (Phase A)';
