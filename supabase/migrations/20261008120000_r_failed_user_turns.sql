-- User-authored semantic-error recovery only; never an answer or approved fact.
begin;
create table r_failed_user_turns (
  failed_turn_id bigint generated always as identity primary key,
  store_id bigint not null,
  member_id bigint not null,
  session_id bigint not null,
  request_id varchar(80) not null check (length(request_id) between 8 and 80),
  question text not null check (length(btrim(question))>0 and length(question)<=1000),
  error_code varchar(40) not null check (error_code in
    ('GENERAL_INVALID_PROPOSAL','GENERAL_VERIFICATION_REJECTED','GENERAL_MODEL_UNAVAILABLE','GENERAL_DEADLINE')),
  created_at timestamptz not null default clock_timestamp(),
  expires_at timestamptz not null default clock_timestamp()+interval '24 hours',
  unique(store_id,member_id,request_id),
  foreign key(store_id,member_id,session_id) references chat_sessions(store_id,member_id,session_id) on delete cascade
);
create index r_failed_user_turns_scope on r_failed_user_turns(store_id,member_id,session_id,failed_turn_id desc);
revoke all on r_failed_user_turns from anon,authenticated;
commit;
