begin;

-- 알림 수신자는 반드시 같은 매장의 구성원이어야 한다.
alter table notification_events
  drop constraint if exists notification_events_store_recipient_fkey;
alter table notification_events
  add constraint notification_events_store_recipient_fkey
  foreign key (store_id, recipient_user_id)
  references store_members(store_id, user_id) on delete cascade;

alter table notification_events
  drop constraint if exists notification_events_destination_check;
alter table notification_events
  add constraint notification_events_destination_check
  check (destination ~ '^/owner/[A-Za-z0-9_/?=&.-]*$');

create or replace function askbuddy_protect_notification_event()
returns trigger
language plpgsql
as $$
begin
  if new.store_id is distinct from old.store_id
     or new.recipient_user_id is distinct from old.recipient_user_id
     or new.event_type is distinct from old.event_type
     or new.aggregate_type is distinct from old.aggregate_type
     or new.aggregate_id is distinct from old.aggregate_id
     or new.dedupe_key is distinct from old.dedupe_key
     or new.title is distinct from old.title
     or new.body is distinct from old.body
     or new.destination is distinct from old.destination
     or new.created_at is distinct from old.created_at then
    raise exception 'notification event identity and content are immutable';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_notification_events_protect on notification_events;
create trigger trg_notification_events_protect
before update on notification_events
for each row execute function askbuddy_protect_notification_event();

comment on constraint notification_events_store_recipient_fkey
  on notification_events is
  '다른 매장 사용자에게 알림 이벤트를 연결할 수 없게 한다.';
comment on column notification_events.status is
  'Web Push 전달 요청의 집계 상태. 앱 내 읽음과 실제 업무 완료 상태가 아니다.';

commit;
