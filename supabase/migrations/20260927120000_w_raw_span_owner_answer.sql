-- W — 승인된 원문 구간(raw_spans)이 자료뿐 아니라 점주 답변도 출처로 가진다.
--
-- 지금까지 raw_spans 는 항상 자료(sources)에서 나왔다. 그런데 점주가 채팅에서
-- 직접 답한 원문(owner_answers)도 그대로 카드에 실을 필요가 생겼다. 자료 출처와
-- 점주 답변 출처를 같은 컬럼에 밀어 넣으면 어느 쪽에서 왔는지 구분할 수 없고,
-- 자료 삭제 시 tombstone·인용 끊김 판정(D20)이 점주 답변에도 잘못 적용된다.
-- 그래서 origin 을 나누고 "정확히 하나만" 있도록 강제한다.

begin;

alter table raw_spans alter column source_id drop not null;

alter table raw_spans
  add column if not exists owner_answer_id bigint
    references owner_answers(answer_id) on delete restrict;

alter table raw_spans
  add constraint raw_spans_one_origin_check
  check ((source_id is null) <> (owner_answer_id is null));

comment on column raw_spans.owner_answer_id is
  '점주 답변이 출처인 승인 원문. 자료 출처와 동시에 두지 않는다 (W 2026-09-27)';

-- owner_answers 에는 store_id 가 없다 (질문자·질문에만 매장이 붙는다). 매장 일치는
-- pending_questions 경유로 여기서 검사한다 — API 검증만으로는 매장 격리 불변식
-- (CLAUDE.md 4) 을 DB 계층에서 보장할 수 없다
create or replace function askbuddy_raw_span_owner_answer_store_check()
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
      raise exception '원문 구간이 가리키는 점주 답변(answer_id=%)이 없다', new.owner_answer_id;
    end if;

    if answer_store_id <> new.store_id then
      raise exception '원문 구간의 매장(%)과 점주 답변의 매장(%)이 다르다',
        new.store_id, answer_store_id;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_raw_span_owner_answer_store_check on raw_spans;
create trigger trg_raw_span_owner_answer_store_check
before insert or update on raw_spans
for each row execute function askbuddy_raw_span_owner_answer_store_check();

commit;
