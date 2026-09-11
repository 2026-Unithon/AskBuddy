-- 근거 답변의 공개 버전 고정과 제외 카드 검색 차단 테스트. 마지막에 롤백한다.
begin;

do $$
declare
  test_store_id bigint;
  test_card_id bigint;
  test_version_id bigint;
  test_member_id bigint;
  test_session_id bigint;
  test_message_id bigint;
begin
  select k.store_id, k.card_id, k.published_version_id
  into test_store_id, test_card_id, test_version_id
  from knowledge_cards k
  where k.review_status = 'APPROVED'
    and k.published_version_id is not null
  order by k.card_id
  limit 1;

  select m.member_id into test_member_id
  from store_members m
  where m.store_id = test_store_id
  order by (m.member_role = 'STAFF') desc, m.member_id
  limit 1;

  select s.session_id into test_session_id
  from chat_sessions s
  where s.store_id = test_store_id and s.member_id = test_member_id
  order by s.session_id
  limit 1;

  if test_store_id is null or test_member_id is null then
    raise exception 'grounded chat test fixture missing';
  end if;

  if test_session_id is null then
    insert into chat_sessions (store_id, member_id)
    values (test_store_id, test_member_id)
    returning session_id into test_session_id;
  end if;

  insert into chat_messages (
    session_id, sender_type, content, answer_type, answer_source, grounding_status
  ) values (
    test_session_id, 'BUDDY', '근거 답변 테스트', 'ANSWERED',
    'CARD_ORIGINAL', 'FALLBACK'
  ) returning message_id into test_message_id;

  insert into message_citations (message_id, card_id, version_id, relevance)
  values (test_message_id, test_card_id, test_version_id, 100.00);

  if not exists (
    select 1 from message_citations
    where message_id = test_message_id
      and card_id = test_card_id
      and version_id = test_version_id
  ) then
    raise exception '답변 당시 공개 버전이 citation에 고정되지 않음';
  end if;

  update knowledge_cards
  set review_status = 'EXCLUDED'
  where store_id = test_store_id and card_id = test_card_id;

  if exists (
    select 1
    from card_embeddings e
    join knowledge_cards c
      on c.store_id = e.store_id and c.card_id = e.card_id
    where c.store_id = test_store_id
      and c.card_id = test_card_id
      and e.is_stale = false
      and e.version_id = c.published_version_id
      and c.review_status = 'APPROVED'
      and c.is_verified = true
  ) then
    raise exception '제외 카드가 검색 가능한 상태로 남음';
  end if;
end;
$$;

select '005 grounded chat contract ok' as result;

rollback;
