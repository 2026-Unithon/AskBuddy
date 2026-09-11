-- 점주 답변 원문 보존, 제안 검토, 기존 공개본 보호 계약. 마지막에 롤백한다.
begin;

do $$
declare
  test_store_id bigint;
  test_owner_id bigint;
  test_member_id bigint;
  test_card_id bigint;
  test_version_id bigint;
  test_category_id bigint;
  test_question_id bigint;
  test_answer_id bigint;
  test_proposal_id bigint;
  mutation_blocked boolean := false;
begin
  select k.store_id, k.card_id, k.published_version_id, k.category_id
  into test_store_id, test_card_id, test_version_id, test_category_id
  from knowledge_cards k
  where k.review_status = 'APPROVED' and k.published_version_id is not null
  order by k.card_id limit 1;

  select s.owner_id into test_owner_id from stores s where s.store_id = test_store_id;
  select member_id into test_member_id
  from store_members where store_id = test_store_id and member_role = 'STAFF'
  order by member_id limit 1;

  insert into pending_questions (
    store_id, member_id, question_text, miss_reason, status
  ) values (
    test_store_id, test_member_id, '  우유는   어디에 둬요?  ', 'no_match', 'WAITING'
  ) returning question_id into test_question_id;

  if (select normalized_question from pending_questions where question_id = test_question_id)
     <> '우유는 어디에 둬요?' then
    raise exception '질문 정규화 실패';
  end if;

  insert into pending_question_occurrences (question_id, member_id)
  values (test_question_id, test_member_id);
  if (select count(*) from pending_question_occurrences where question_id = test_question_id) <> 1 then
    raise exception '대기 질문 발생 기록 실패';
  end if;

  insert into owner_answers (question_id, answered_by, answer_text)
  values (test_question_id, test_owner_id, '점주 원문 답변')
  returning answer_id into test_answer_id;

  begin
    update owner_answers set answer_text = '변조된 답변' where answer_id = test_answer_id;
  exception when others then
    mutation_blocked := true;
  end;
  if not mutation_blocked then
    raise exception '점주 원문 답변 수정이 차단되지 않음';
  end if;

  insert into knowledge_change_proposals (
    store_id, answer_id, relation_type, target_card_id, target_version_id,
    category_id, proposed_title, proposed_content, reason, status
  ) values (
    test_store_id, test_answer_id, 'SUPPLEMENT', test_card_id, test_version_id,
    test_category_id, '보완 제안', '기존 본문과 점주 답변', '테스트', 'PENDING_REVIEW'
  ) returning proposal_id into test_proposal_id;

  update knowledge_cards
  set needs_review_reason = 'OWNER_ANSWER_SUPPLEMENT'
  where store_id = test_store_id and card_id = test_card_id;

  if not exists (
    select 1 from knowledge_cards
    where store_id = test_store_id and card_id = test_card_id
      and review_status = 'APPROVED' and is_verified = true
      and published_version_id = test_version_id
      and needs_review_reason = 'OWNER_ANSWER_SUPPLEMENT'
  ) then
    raise exception '보완 검토 중 기존 공개본이 보존되지 않음';
  end if;
end;
$$;

select '006 owner answer knowledge loop ok' as result;

rollback;
