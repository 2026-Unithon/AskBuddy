-- 운영 점주 답변 지식 순환 계약을 변경 없이 검증한다.
begin transaction read only;

do $$
declare
  invalid_proposal_count int;
  invalid_published_count int;
begin
  select count(*) into invalid_proposal_count
  from knowledge_change_proposals p
  left join owner_answers a on a.answer_id = p.answer_id
  where a.answer_id is null
     or (p.relation_type <> 'NEW' and p.target_card_id is null)
     or (p.target_card_id is null) <> (p.target_version_id is null);
  if invalid_proposal_count <> 0 then
    raise exception '대상 또는 원문이 잘못 연결된 지식 제안: %', invalid_proposal_count;
  end if;

  select count(*) into invalid_published_count
  from knowledge_change_proposals p
  left join knowledge_cards k
    on k.store_id = p.store_id and k.card_id = p.result_card_id
  where p.status = 'PUBLISHED'
    and (
      p.result_card_id is null or p.result_version_id is null
      or k.review_status <> 'APPROVED'
      or k.published_version_id <> p.result_version_id
    );
  if invalid_published_count <> 0 then
    raise exception '공개 결과가 현재 승인 카드와 불일치: %', invalid_published_count;
  end if;
end;
$$;

select
  count(*) filter (where status = 'LINKED') as linked,
  count(*) filter (where status = 'PENDING_REVIEW') as pending_review,
  count(*) filter (where status = 'PUBLISHED') as published,
  count(*) filter (where status = 'FAILED') as failed
from knowledge_change_proposals;

rollback;
