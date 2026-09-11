-- AskBuddy 동적 로드맵 읽기 전용 검증.
begin transaction read only;

do $$
declare
  missing_item_count int;
  invalid_active_item_count int;
  duplicate_active_item_count int;
begin
  select count(*) into missing_item_count
  from knowledge_cards k
  where k.review_status = 'APPROVED'
    and k.published_version_id is not null
    and k.category_id is not null
    and not exists (
      select 1 from roadmap_items i
      join roadmap_stages g on g.stage_id = i.stage_id
      where i.card_id = k.card_id
        and i.category_id = k.category_id
        and i.published_version_id = k.published_version_id
        and i.is_active = true
        and g.store_id = k.store_id
        and g.category_id = k.category_id
        and g.is_active = true
    );
  if missing_item_count <> 0 then
    raise exception '로드맵 항목이 없는 승인 카드: %', missing_item_count;
  end if;

  select count(*) into invalid_active_item_count
  from roadmap_items i
  join roadmap_stages g on g.stage_id = i.stage_id
  left join knowledge_cards k
    on k.store_id = g.store_id and k.card_id = i.card_id
  where i.is_active = true
    and (
      k.card_id is null or k.review_status <> 'APPROVED'
      or i.published_version_id is distinct from k.published_version_id
      or i.category_id is distinct from k.category_id
    );
  if invalid_active_item_count <> 0 then
    raise exception '현재 카드와 불일치하는 활성 항목: %', invalid_active_item_count;
  end if;

  select count(*) into duplicate_active_item_count
  from (
    select card_id from roadmap_items
    where is_active = true and card_id is not null
    group by card_id having count(*) > 1
  ) duplicate_items;
  if duplicate_active_item_count <> 0 then
    raise exception '카드당 활성 항목 중복: %', duplicate_active_item_count;
  end if;
end;
$$;

select
  (select count(*) from roadmap_stages where is_active and category_id is not null) as active_stages,
  (select count(*) from roadmap_items where is_active and card_id is not null) as active_items;

rollback;
