-- W — 카드 판(card_versions)이 점주 답변에서 왔는지 판 단위로 남긴다.
--
-- 자료 출처 카드(knowledge_cards.source_id)에 점주 답변을 보완·정정 판으로 얹으면,
-- 카드 단위 출처만 보는 RAW 블록 고정이 그 답변 본문을 원래 자료 근거로 싣는다.
-- 판마다 점주 답변 출처를 적어 두고, 있으면 그것을 우선한다. 가산 변경만 한다.

begin;

alter table card_versions
  add column if not exists owner_answer_id bigint
    references owner_answers(answer_id) on delete restrict;

comment on column card_versions.owner_answer_id is
  '이 판의 본문이 된 점주 답변. 있으면 RAW 블록 출처는 카드 자료가 아니라 이 답변이다 (W 2026-09-27)';

-- owner_answers 에는 store_id 가 없다. 매장 일치는 pending_questions 경유로 검사한다
-- (raw_spans 의 같은 트리거와 같은 규칙, 20260927120000)
create or replace function askbuddy_card_version_owner_answer_store_check()
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
      raise exception '카드 판이 가리키는 점주 답변(answer_id=%)이 없다', new.owner_answer_id;
    end if;

    if answer_store_id <> new.store_id then
      raise exception '카드 판의 매장(%)과 점주 답변의 매장(%)이 다르다',
        new.store_id, answer_store_id;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_card_version_owner_answer_store_check on card_versions;
create trigger trg_card_version_owner_answer_store_check
before insert or update of owner_answer_id on card_versions
for each row execute function askbuddy_card_version_owner_answer_store_check();

commit;
