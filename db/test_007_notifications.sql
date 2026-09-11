-- 앱 내부 알림 정본, 멱등성, 읽음/업무 상태 분리를 검증한다.
begin;

do $$
declare
  v_store bigint;
  v_owner bigint;
  v_question bigint;
  v_notification bigint;
  v_duplicate bigint;
begin
  select s.store_id, s.owner_id into v_store, v_owner
  from stores s order by s.store_id limit 1;
  select question_id into v_question
  from pending_questions where store_id = v_store order by question_id limit 1;

  insert into notification_events (
    store_id, recipient_user_id, event_type, aggregate_type, aggregate_id,
    dedupe_key, title, body, destination
  ) values (
    v_store, v_owner, 'PENDING_QUESTION', 'PENDING_QUESTION', v_question,
    'test-notification-007', '새 질문', '질문 내용',
    '/owner/questions?question_id=' || v_question
  ) returning notification_id into v_notification;

  insert into notification_events (
    store_id, recipient_user_id, event_type, aggregate_type, aggregate_id,
    dedupe_key, title, body, destination
  ) values (
    v_store, v_owner, 'PENDING_QUESTION', 'PENDING_QUESTION', v_question,
    'test-notification-007', '새 질문', '질문 내용',
    '/owner/questions?question_id=' || v_question
  ) on conflict (recipient_user_id, dedupe_key) do nothing
  returning notification_id into v_duplicate;

  if v_duplicate is not null then
    raise exception 'dedupe key created a duplicate notification';
  end if;

  update notification_events set read_at = now()
  where notification_id = v_notification;

  if not exists (
    select 1 from notification_events
    where notification_id = v_notification
      and read_at is not null and status = 'PENDING'
  ) then
    raise exception 'read state changed push delivery state';
  end if;

  begin
    update notification_events set body = '변조' where notification_id = v_notification;
    raise exception 'notification immutable content was updated';
  exception when others then
    if sqlerrm = 'notification immutable content was updated' then
      raise;
    end if;
  end;

  raise notice '007 notification behavior ok';
end $$;

select '007 notification contract ok' as result;
rollback;
