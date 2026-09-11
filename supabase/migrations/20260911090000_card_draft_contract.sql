-- 신규 카드 API는 버전을 먼저 만든 뒤 호환 컬럼(title/content)과
-- draft_version_id를 한 번에 갱신한다. 이 경우 레거시 호환 트리거가
-- 중복 버전을 만들거나 승인 카드의 초안을 즉시 공개하면 안 된다.
create or replace function askbuddy_version_legacy_card_write()
returns trigger
language plpgsql
as $$
declare
  new_version_id bigint;
  next_version_no int;
begin
  if tg_op = 'UPDATE'
     and new.title is not distinct from old.title
     and new.content is not distinct from old.content then
    return new;
  end if;

  -- 신규 API가 명시적으로 만든 버전을 가리키는 쓰기다.
  if tg_op = 'UPDATE'
     and new.draft_version_id is distinct from old.draft_version_id then
    return new;
  end if;

  select coalesce(max(version_no), 0) + 1 into next_version_no
  from card_versions
  where card_id = new.card_id;

  insert into card_versions (
    store_id, card_id, version_no, title, content, change_source, created_at
  )
  values (
    new.store_id, new.card_id, next_version_no, new.title, new.content,
    case when tg_op = 'INSERT' then 'EXTRACTION' else 'OWNER_EDIT' end,
    coalesce(new.updated_at, new.created_at, now())
  )
  returning version_id into new_version_id;

  update knowledge_cards
  set draft_version_id = new_version_id,
      published_version_id = case
        when review_status = 'APPROVED' then new_version_id
        else published_version_id
      end
  where card_id = new.card_id and store_id = new.store_id;

  return new;
end;
$$;
