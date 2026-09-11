-- 운영 데이터의 근거 답변 계약을 변경 없이 검증한다.
begin transaction read only;

do $$
declare
  match_function_definition text;
  invalid_new_answer_count int;
  invalid_citation_version_count int;
begin
  select pg_get_functiondef('match_cards(bigint,vector,integer)'::regprocedure)
  into match_function_definition;
  if match_function_definition not like '%e.is_stale = false%'
     or match_function_definition not like '%e.version_id = c.published_version_id%'
     or match_function_definition not like '%c.review_status = ''APPROVED''%'
     or match_function_definition not like '%c.is_verified = true%' then
    raise exception 'match_cards의 승인·현재 버전 검색 게이트가 불완전함';
  end if;

  select count(*) into invalid_new_answer_count
  from chat_messages m
  where m.sender_type = 'BUDDY'
    and m.created_at >= timestamp with time zone '2026-09-11 00:00:00+09'
    and m.answer_type = 'ANSWERED'
    and (m.answer_source is null or m.grounding_status is null);
  if invalid_new_answer_count <> 0 then
    raise exception '출처 또는 검증 상태가 없는 신규 답변: %', invalid_new_answer_count;
  end if;

  select count(*) into invalid_citation_version_count
  from message_citations mc
  left join card_versions v
    on v.version_id = mc.version_id and v.card_id = mc.card_id
  where mc.version_id is not null and v.version_id is null;
  if invalid_citation_version_count <> 0 then
    raise exception '카드와 버전이 일치하지 않는 citation: %', invalid_citation_version_count;
  end if;
end;
$$;

select
  count(*) filter (where answer_source = 'GROUNDED_LLM') as grounded_llm_answers,
  count(*) filter (where answer_source = 'CARD_ORIGINAL') as original_fallback_answers,
  count(*) filter (where answer_source = 'MISS') as miss_answers
from chat_messages
where sender_type = 'BUDDY';

rollback;
