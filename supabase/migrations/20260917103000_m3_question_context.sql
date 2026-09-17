-- M3 첫 단위: v1/v2 session 경계와 서버 소유 되묻기 문맥.
-- 인용/답변 요청 멱등성/owner answer revision은 이 migration의 완료 범위가 아니다.
begin;

alter table chat_sessions add column if not exists contract_version varchar(20)
  not null default 'v1' check (contract_version in ('v1', 'v2'));
create unique index if not exists uq_chat_sessions_context_scope
  on chat_sessions(store_id, member_id, session_id, contract_version);

create or replace function askbuddy_session_scope_immutable()
returns trigger language plpgsql as $$
begin
  if (new.store_id, new.member_id, new.contract_version)
     is distinct from (old.store_id, old.member_id, old.contract_version) then
    raise exception 'session scope and contract version are immutable';
  end if;
  return new;
end;
$$;
create trigger trg_session_scope_immutable before update on chat_sessions
  for each row execute function askbuddy_session_scope_immutable();

create table r_question_contexts (
  context_id uuid primary key,
  store_id bigint not null,
  member_id bigint not null,
  chat_session_id bigint not null,
  contract_version varchar(20) not null default 'v2' check (contract_version = 'v2'),
  original_question text not null check (length(original_question) between 1 and 1000),
  confirmed_slots jsonb not null default '{}' check (jsonb_typeof(confirmed_slots) = 'object'),
  proposed_slots jsonb not null default '{}' check (jsonb_typeof(proposed_slots) = 'object'),
  knowledge_revision bigint not null check (knowledge_revision >= 0),
  clarify_turns integer not null check (clarify_turns between 1 and 2),
  offered_slot text,
  offered_options jsonb not null default '[]' check (jsonb_typeof(offered_options) = 'array'),
  state_revision bigint not null default 1 check (state_revision >= 1),
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (store_id, member_id, chat_session_id, context_id),
  foreign key (store_id, member_id, chat_session_id, contract_version)
    references chat_sessions(store_id, member_id, session_id, contract_version) on delete cascade,
  check ((offered_slot is null and jsonb_array_length(offered_options) = 0)
      or (offered_slot is not null and length(trim(offered_slot)) between 1 and 60
          and jsonb_array_length(offered_options) between 1 and 10))
);
create index idx_r_question_contexts_expiry on r_question_contexts(store_id, expires_at);
commit;
