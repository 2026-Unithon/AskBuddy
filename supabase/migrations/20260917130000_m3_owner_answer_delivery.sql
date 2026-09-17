-- R5 원문 revision, 직원 전달, W 지식화 상태는 서로 다른 원장이다.
begin;
create unique index r_owner_answer_question_id on owner_answers(question_id,answer_id);
create table r_owner_answer_revisions (
  store_id bigint not null,
  question_id bigint not null,
  owner_answer_id bigint not null,
  revision_no integer not null check(revision_no>0),
  supersedes_answer_id bigint,
  created_at timestamptz not null default now(),
  primary key(store_id,owner_answer_id),
  unique(store_id,question_id,revision_no),
  foreign key(store_id,question_id) references pending_questions(store_id,question_id),
  foreign key(question_id,owner_answer_id) references owner_answers(question_id,answer_id),
  foreign key(question_id,supersedes_answer_id) references owner_answers(question_id,answer_id),
  check((revision_no=1)=(supersedes_answer_id is null))
);
create table r_owner_knowledge_states (
  store_id bigint not null,
  owner_answer_id bigint not null,
  status varchar(20) not null default 'PENDING'
    check(status in ('PENDING','LINKED','REVIEW','PUBLISHED','FAILED')),
  result jsonb,
  updated_at timestamptz not null default now(),
  primary key(store_id,owner_answer_id),
  foreign key(store_id,owner_answer_id) references r_owner_answer_revisions(store_id,owner_answer_id)
);
create table r_owner_answer_deliveries (
  store_id bigint not null,
  owner_answer_id bigint not null,
  member_id bigint not null,
  session_id bigint not null,
  message_id bigint not null,
  primary key(store_id,owner_answer_id,session_id),
  foreign key(store_id,owner_answer_id) references r_owner_answer_revisions(store_id,owner_answer_id),
  foreign key(store_id,member_id,session_id) references chat_sessions(store_id,member_id,session_id),
  foreign key(session_id,message_id) references chat_messages(session_id,message_id)
);
create trigger r_owner_revision_immutable before update or delete on r_owner_answer_revisions
  for each row execute function askbuddy_answer_receipt_immutable();
create trigger r_owner_delivery_immutable before update or delete on r_owner_answer_deliveries
  for each row execute function askbuddy_answer_receipt_immutable();
create function askbuddy_owner_original_immutable() returns trigger language plpgsql as $$
begin
  if exists(select 1 from r_owner_answer_revisions where owner_answer_id=old.answer_id) then
    if tg_op='DELETE' then raise exception 'owner original is immutable'; end if;
    if (new.answer_id,new.question_id,new.answered_by,new.answer_text,new.answered_at)
       is distinct from (old.answer_id,old.question_id,old.answered_by,old.answer_text,old.answered_at)
    then raise exception 'owner original is immutable'; end if;
  end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end;
$$;
create trigger r_owner_original_immutable before update or delete on owner_answers
  for each row execute function askbuddy_owner_original_immutable();
alter table notification_events drop constraint notification_events_destination_check;
alter table notification_events add constraint notification_events_destination_check
  check(destination ~ '^/(owner|staff)/[A-Za-z0-9_/?=&.-]*$');
alter table notification_events drop constraint notification_events_event_type_check;
alter table notification_events add constraint notification_events_event_type_check
  check(event_type in ('INGEST_COMPLETED','PENDING_QUESTION','OWNER_ANSWER'));
alter table notification_events drop constraint notification_events_aggregate_type_check;
alter table notification_events add constraint notification_events_aggregate_type_check
  check(aggregate_type in ('INGEST_JOB','PENDING_QUESTION','OWNER_ANSWER'));
commit;
