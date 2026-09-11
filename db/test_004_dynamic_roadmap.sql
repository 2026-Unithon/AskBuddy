-- 동적 로드맵의 항목 정체성·완료 버전 동작 테스트. 마지막에 롤백한다.
begin;

do $$
declare
  test_store_id bigint;
  test_member_id bigint;
  test_card_id bigint;
  test_item_id bigint;
  old_version_id bigint;
  new_version_id bigint;
  other_category_id bigint;
begin
  select k.store_id, k.card_id, k.published_version_id, i.item_id
  into test_store_id, test_card_id, old_version_id, test_item_id
  from knowledge_cards k
  join roadmap_items i on i.card_id = k.card_id and i.is_active = true
  where k.review_status = 'APPROVED'
  order by k.card_id
  limit 1;

  select member_id into test_member_id
  from store_members
  where store_id = test_store_id and member_role = 'STAFF'
  order by member_id
  limit 1;

  insert into learning_progress (
    member_id, item_id, status, completed_at, completed_version_id
  ) values (
    test_member_id, test_item_id, 'DONE', now(), old_version_id
  )
  on conflict (member_id, item_id) do update
  set status = 'DONE', completed_at = now(), completed_version_id = old_version_id;

  insert into card_versions (
    store_id, card_id, version_no, title, content, change_source
  )
  select test_store_id, test_card_id, max(version_no) + 1,
         '로드맵 새 버전', '재확인이 필요한 새 본문', 'OWNER_EDIT'
  from card_versions where card_id = test_card_id
  returning version_id into new_version_id;

  update knowledge_cards
  set title = '로드맵 새 버전', content = '재확인이 필요한 새 본문',
      draft_version_id = new_version_id
  where store_id = test_store_id and card_id = test_card_id;

  if (select published_version_id from roadmap_items where item_id = test_item_id)
     is distinct from old_version_id then
    raise exception '초안이 승인 전에 로드맵에 공개됨';
  end if;

  update knowledge_cards
  set published_version_id = new_version_id
  where store_id = test_store_id and card_id = test_card_id;

  if not exists (
    select 1 from roadmap_items
    where item_id = test_item_id and is_active = true
      and published_version_id = new_version_id
  ) then
    raise exception '새 공개 버전에서 기존 item_id가 유지되지 않음';
  end if;

  if not exists (
    select 1 from learning_progress
    where member_id = test_member_id and item_id = test_item_id
      and completed_version_id = old_version_id
      and completed_version_id <> new_version_id
  ) then
    raise exception '새 공개 버전의 재확인 조건이 만들어지지 않음';
  end if;

  select category_id into other_category_id
  from task_categories
  where store_id = test_store_id and is_system = true and category_name = '기타';

  update knowledge_cards set category_id = other_category_id
  where store_id = test_store_id and card_id = test_card_id;

  if not exists (
    select 1 from roadmap_items
    where item_id = test_item_id and category_id = other_category_id and is_active = true
  ) then
    raise exception '카테고리 이동에서 item_id 또는 활성 상태가 바뀜';
  end if;

  update knowledge_cards set review_status = 'EXCLUDED'
  where store_id = test_store_id and card_id = test_card_id;
  if (select is_active from roadmap_items where item_id = test_item_id) then
    raise exception '제외 카드의 로드맵 항목이 활성 상태임';
  end if;

  update knowledge_cards set review_status = 'APPROVED'
  where store_id = test_store_id and card_id = test_card_id;
  if not (select is_active from roadmap_items where item_id = test_item_id) then
    raise exception '복원 카드의 로드맵 항목이 활성화되지 않음';
  end if;
end;
$$;

select '004 dynamic roadmap behavior ok' as result;

rollback;
