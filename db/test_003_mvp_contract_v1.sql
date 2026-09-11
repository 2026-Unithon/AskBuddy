-- AskBuddy 003 호환 동작 테스트.
-- 테스트 데이터는 트랜잭션 마지막에 모두 롤백된다.

begin;

do $$
declare
  test_owner_id bigint;
  test_store_id bigint;
  test_other_id bigint;
  test_source_id bigint;
  test_job_id bigint;
  test_card_id bigint;
  first_version_id bigint;
  second_version_id bigint;
  embedding_version_id bigint;
begin
  insert into users (name, email, password_hash, role)
  values ('003 테스트 점주', 'migration-003-test@askbuddy.local', 'not-a-login-password', 'OWNER')
  returning user_id into test_owner_id;

  insert into stores (owner_id, store_slug, store_name, business_type)
  values (test_owner_id, 'migration-003-test', '003 테스트 매장', 'CAFE')
  returning store_id into test_store_id;

  insert into store_members (store_id, user_id, member_role)
  values (test_store_id, test_owner_id, 'OWNER');

  select category_id into test_other_id
  from task_categories
  where store_id = test_store_id
    and category_name = '기타'
    and is_system = true
    and deleted_at is null;

  if test_other_id is null then
    raise exception '신규 매장 기타 자동 생성 실패';
  end if;

  begin
    update task_categories
    set is_enabled = false
    where category_id = test_other_id;
    raise exception '기타 비활성화가 허용됨';
  exception
    when check_violation then
      null;
  end;

  insert into sources (
    store_id, uploaded_by, source_type, title, file_url, status
  )
  values (
    test_store_id, test_owner_id, 'VOICE', '호환 테스트.m4a',
    'sources/test/voice.m4a', 'UPLOADED'
  )
  returning source_id into test_source_id;

  select j.job_id into test_job_id
  from ingest_jobs j
  join ingest_job_sources js
    on js.store_id = j.store_id and js.job_id = j.job_id
  where j.store_id = test_store_id and js.source_id = test_source_id;

  if test_job_id is null then
    raise exception '구 source API의 작업 자동 생성 실패';
  end if;

  update sources
  set status = 'PROCESSING'
  where store_id = test_store_id and source_id = test_source_id;

  if not exists (
    select 1 from ingest_jobs
    where store_id = test_store_id
      and job_id = test_job_id
      and status = 'EXTRACTING'
  ) then
    raise exception '구 source PROCESSING 상태 동기화 실패';
  end if;

  insert into knowledge_cards (
    store_id, category_id, source_id, title, content, confidence, is_verified
  )
  values (
    test_store_id, test_other_id, test_source_id,
    '테스트 카드', '테스트 카드의 최초 본문입니다.', 90, false
  )
  returning card_id, draft_version_id, published_version_id
  into test_card_id, first_version_id, second_version_id;

  -- AFTER INSERT에서 버전을 만들기 때문에 RETURNING에는 포인터가 아직 없다.
  select draft_version_id, published_version_id
  into first_version_id, second_version_id
  from knowledge_cards
  where store_id = test_store_id and card_id = test_card_id;

  if first_version_id is null or second_version_id is not null then
    raise exception '미승인 카드 최초 초안 버전 생성 실패';
  end if;

  if not exists (
    select 1 from card_versions
    where version_id = first_version_id and change_source = 'EXTRACTION'
  ) then
    raise exception '신규 카드 최초 버전의 출처가 EXTRACTION이 아님';
  end if;

  update knowledge_cards
  set is_verified = true
  where store_id = test_store_id and card_id = test_card_id;

  select published_version_id into first_version_id
  from knowledge_cards
  where store_id = test_store_id and card_id = test_card_id;

  if first_version_id is null then
    raise exception '구 승인 API의 초안 공개 연결 실패';
  end if;

  if not exists (
    select 1 from stores
    where store_id = test_store_id and guide_completed_at is not null
  ) then
    raise exception '최초 승인 후 가이드 완료 기록 실패';
  end if;

  insert into card_embeddings (
    card_id, store_id, chunk_index, chunk_text, embedding,
    dimension, model_name, content_hash
  )
  values (
    test_card_id, test_store_id, 0, '테스트 카드 최초 본문',
    array_fill(0::real, array[1536])::vector,
    1536, 'text-embedding-3-small', repeat('a', 64)
  );

  select version_id into embedding_version_id
  from card_embeddings
  where store_id = test_store_id and card_id = test_card_id;

  if embedding_version_id is distinct from first_version_id then
    raise exception '구 임베딩 쓰기의 공개 버전 자동 연결 실패';
  end if;

  update knowledge_cards
  set title = '수정된 테스트 카드',
      content = '승인 카드의 수정된 본문입니다.'
  where store_id = test_store_id and card_id = test_card_id;

  select published_version_id into second_version_id
  from knowledge_cards
  where store_id = test_store_id and card_id = test_card_id;

  if second_version_id is null or second_version_id = first_version_id then
    raise exception '구 수정 API의 새 공개 버전 생성 실패';
  end if;

  -- 신규 API는 초안을 명시적으로 만든다. 승인 카드여도 공개 포인터는
  -- approve 전까지 기존 버전에 머물러야 한다.
  insert into card_versions (
    store_id, card_id, version_no, title, content, change_source, created_by
  )
  select test_store_id, test_card_id, max(version_no) + 1,
         '신규 초안', '아직 공개되지 않은 본문', 'OWNER_EDIT', test_owner_id
  from card_versions
  where card_id = test_card_id
  returning version_id into embedding_version_id;

  update knowledge_cards
  set title = '신규 초안', content = '아직 공개되지 않은 본문',
      draft_version_id = embedding_version_id
  where store_id = test_store_id and card_id = test_card_id;

  if (select published_version_id from knowledge_cards
      where store_id = test_store_id and card_id = test_card_id) is distinct from second_version_id then
    raise exception '신규 초안이 승인 전에 공개됨';
  end if;

  if (select count(*) from card_versions where card_id = test_card_id
      and title = '신규 초안') <> 1 then
    raise exception '신규 초안 쓰기에서 중복 버전 생성';
  end if;

  -- 현재 upsert가 version_id를 SET하지 않아도 BEFORE UPDATE 트리거가 교정해야 한다.
  insert into card_embeddings (
    card_id, store_id, chunk_index, chunk_text, embedding,
    dimension, model_name, content_hash
  )
  values (
    test_card_id, test_store_id, 0, '수정된 테스트 카드 본문',
    array_fill(0::real, array[1536])::vector,
    1536, 'text-embedding-3-small', repeat('b', 64)
  )
  on conflict (card_id, chunk_index) do update set
    chunk_text = excluded.chunk_text,
    embedding = excluded.embedding,
    content_hash = excluded.content_hash;

  select version_id into embedding_version_id
  from card_embeddings
  where store_id = test_store_id and card_id = test_card_id;

  if embedding_version_id is distinct from second_version_id then
    raise exception '구 임베딩 upsert의 새 공개 버전 연결 실패';
  end if;

  update sources
  set status = 'DONE', processed_at = now()
  where store_id = test_store_id and source_id = test_source_id;

  if not exists (
    select 1 from ingest_jobs
    where store_id = test_store_id
      and job_id = test_job_id
      and status = 'SUCCEEDED'
      and card_count = 1
  ) then
    raise exception '구 source DONE 상태·카드 수 동기화 실패';
  end if;
end;
$$;

select '003 compatibility behavior ok' as result;

rollback;
