-- 운영 적용 후 읽기 전용 검증. 마지막에 롤백한다.
begin;

do $$
begin
  if to_regclass('public.notification_events') is null
     or to_regclass('public.notification_deliveries') is null
     or to_regclass('public.push_subscriptions') is null then
    raise exception 'notification tables are missing';
  end if;
  if not exists (
    select 1 from pg_trigger
    where tgname = 'trg_notification_events_protect' and not tgisinternal
  ) then
    raise exception 'notification protection trigger is missing';
  end if;
end $$;

select
  count(*) filter (where read_at is null) as unread,
  count(*) filter (where status = 'REQUESTED') as push_requested,
  count(*) filter (where status = 'FAILED') as push_failed
from notification_events;

rollback;
