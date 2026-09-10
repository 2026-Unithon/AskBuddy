-- AskBuddy 003 마이그레이션 읽기 전용 검증.
-- 001 -> 002 -> 003 적용 후 실행한다. 실패하면 예외로 종료한다.

begin transaction read only;

do $$
declare
  missing_other_count int;
  duplicate_other_count int;
  approved_without_version_count int;
  pending_mismatch_count int;
  embedding_without_version_count int;
  completed_without_version_count int;
  legacy_source_without_job_count int;
begin
  select count(*) into missing_other_count
  from stores s
  where not exists (
    select 1
    from task_categories c
    where c.store_id = s.store_id
      and c.category_name = '기타'
      and c.is_system = true
      and c.deleted_at is null
      and c.is_enabled = true
  );
  if missing_other_count <> 0 then
    raise exception '기타가 없는 매장: %', missing_other_count;
  end if;

  select count(*) into duplicate_other_count
  from (
    select store_id
    from task_categories
    where category_name = '기타' and is_system = true
    group by store_id
    having count(*) <> 1
  ) d;
  if duplicate_other_count <> 0 then
    raise exception '기타 개수가 1이 아닌 매장: %', duplicate_other_count;
  end if;

  select count(*) into approved_without_version_count
  from knowledge_cards
  where review_status = 'APPROVED'
    and (published_version_id is null or draft_version_id is null or is_verified is false);
  if approved_without_version_count <> 0 then
    raise exception '공개 버전이 없는 승인 카드: %', approved_without_version_count;
  end if;

  select count(*) into pending_mismatch_count
  from knowledge_cards
  where is_verified is true and review_status <> 'APPROVED';
  if pending_mismatch_count <> 0 then
    raise exception '기존 is_verified와 새 상태 불일치: %', pending_mismatch_count;
  end if;

  select count(*) into embedding_without_version_count
  from card_embeddings e
  join knowledge_cards c
    on c.store_id = e.store_id and c.card_id = e.card_id
  where c.review_status = 'APPROVED'
    and e.version_id is distinct from c.published_version_id;
  if embedding_without_version_count <> 0 then
    raise exception '공개 버전에 연결되지 않은 기존 임베딩: %', embedding_without_version_count;
  end if;

  select count(*) into completed_without_version_count
  from learning_progress p
  join roadmap_items i on i.item_id = p.item_id
  where p.status = 'DONE'
    and i.card_id is not null
    and i.published_version_id is not null
    and p.completed_version_id is null;
  if completed_without_version_count <> 0 then
    raise exception '버전 연결이 누락된 완료 이력: %', completed_without_version_count;
  end if;

  select count(*) into legacy_source_without_job_count
  from sources s
  where not exists (
    select 1
    from ingest_job_sources js
    where js.store_id = s.store_id and js.source_id = s.source_id
  );
  if legacy_source_without_job_count <> 0 then
    raise exception '작업으로 백필되지 않은 기존 자료: %', legacy_source_without_job_count;
  end if;
end;
$$;

-- 아래 SELECT는 사람이 백필 결과를 빠르게 확인하기 위한 요약이다.
select
  (select count(*) from stores) as stores,
  (select count(*) from task_categories where is_system and category_name = '기타') as other_categories,
  (select count(*) from ingest_jobs) as ingest_jobs,
  (select count(*) from card_versions) as card_versions,
  (select count(*) from knowledge_cards where review_status = 'APPROVED') as approved_cards,
  (select count(*) from notification_events) as notifications,
  (select count(*) from quality_evaluations) as evaluations;

rollback;
