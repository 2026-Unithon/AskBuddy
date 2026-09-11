-- 승인 카드와 카테고리를 직원 로드맵의 유일한 데이터 원천으로 동기화한다.
create or replace function askbuddy_sync_roadmap_card_values(
  p_store_id bigint,
  p_card_id bigint,
  p_review_status varchar,
  p_category_id bigint,
  p_published_version_id bigint
)
returns void
language plpgsql
as $$
declare
  target_stage_id bigint;
  target_item_id bigint;
  target_category_name varchar(100);
  target_title varchar(200);
begin
  -- 같은 매장에서 카테고리 단계가 동시에 중복 생성되지 않게 직렬화한다.
  perform pg_advisory_xact_lock(p_store_id);

  -- migration 뒤에 레거시 seed/import가 실행돼도 고정 샘플은 다시 노출하지 않는다.
  update roadmap_items i
  set is_active = false
  from roadmap_stages g
  where i.stage_id = g.stage_id
    and g.store_id = p_store_id
    and (i.card_id is null or g.category_id is null);
  update roadmap_stages
  set is_active = false
  where store_id = p_store_id and category_id is null;

  if p_review_status <> 'APPROVED'
     or p_published_version_id is null
     or p_category_id is null then
    update roadmap_items set is_active = false where card_id = p_card_id;
    update roadmap_stages g
    set is_active = exists (
      select 1 from roadmap_items i
      where i.stage_id = g.stage_id and i.is_active = true
    )
    where g.store_id = p_store_id and g.category_id is not null;
    return;
  end if;

  select category_name into target_category_name
  from task_categories
  where store_id = p_store_id and category_id = p_category_id;

  if target_category_name is null then
    update roadmap_items set is_active = false where card_id = p_card_id;
    update roadmap_stages g
    set is_active = exists (
      select 1 from roadmap_items i
      where i.stage_id = g.stage_id and i.is_active = true
    )
    where g.store_id = p_store_id and g.category_id is not null;
    return;
  end if;

  select title into target_title
  from card_versions
  where store_id = p_store_id and version_id = p_published_version_id;

  select min(stage_id) into target_stage_id
  from roadmap_stages
  where store_id = p_store_id and category_id = p_category_id;

  if target_stage_id is null then
    insert into roadmap_stages (
      store_id, stage_name, stage_order, category_id, is_active
    ) values (
      p_store_id,
      target_category_name,
      coalesce((select max(stage_order) + 1 from roadmap_stages where store_id = p_store_id), 1),
      p_category_id,
      true
    )
    returning stage_id into target_stage_id;
  else
    update roadmap_stages
    set stage_name = target_category_name, is_active = true
    where stage_id = target_stage_id;
  end if;

  select min(item_id) into target_item_id
  from roadmap_items
  where card_id = p_card_id;

  if target_item_id is null then
    insert into roadmap_items (
      stage_id, card_id, item_name, item_order,
      category_id, published_version_id, is_active
    ) values (
      target_stage_id,
      p_card_id,
      target_title,
      coalesce((select max(item_order) + 1 from roadmap_items where stage_id = target_stage_id), 1),
      p_category_id,
      p_published_version_id,
      true
    );
  else
    update roadmap_items
    set stage_id = target_stage_id,
        item_name = target_title,
        category_id = p_category_id,
        published_version_id = p_published_version_id,
        is_active = (item_id = target_item_id)
    where card_id = p_card_id;
  end if;

  update roadmap_stages g
  set is_active = exists (
    select 1 from roadmap_items i
    where i.stage_id = g.stage_id and i.is_active = true
  )
  where g.store_id = p_store_id and g.category_id is not null;
end;
$$;

create or replace function askbuddy_sync_roadmap_card()
returns trigger
language plpgsql
as $$
begin
  perform askbuddy_sync_roadmap_card_values(
    new.store_id,
    new.card_id,
    new.review_status,
    new.category_id,
    new.published_version_id
  );
  return new;
end;
$$;

drop trigger if exists trg_knowledge_cards_roadmap_sync on knowledge_cards;
create trigger trg_knowledge_cards_roadmap_sync
after insert or update of review_status, category_id, published_version_id
on knowledge_cards
for each row execute function askbuddy_sync_roadmap_card();

-- 기존 고정 샘플은 보존하되 노출하지 않는다.
update roadmap_stages set is_active = false where category_id is null;
update roadmap_items set is_active = false where card_id is null;

-- 카드 행과 updated_at을 건드리지 않고 현재 승인 카드만 백필한다.
select askbuddy_sync_roadmap_card_values(
  store_id, card_id, review_status, category_id, published_version_id
)
from knowledge_cards;

comment on function askbuddy_sync_roadmap_card_values(bigint, bigint, varchar, bigint, bigint) is
  '승인 카드의 동일 item_id를 유지하며 카테고리 단계·공개 버전·활성 상태를 동기화한다.';
