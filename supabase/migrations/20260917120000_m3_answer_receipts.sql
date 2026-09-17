-- M3 v2 답변 receipt·정확한 블록 인용·문맥별 pending. v1 이력은 그대로 둔다.
begin;
alter table pending_questions add column contract_version varchar(20) not null default 'v1'
  check(contract_version in ('v1','v2'));
alter table pending_questions add column semantic_key text;
alter table pending_questions add constraint pending_semantic_contract
  check((contract_version='v1' and semantic_key is null)
     or (contract_version='v2' and semantic_key is not null));
create unique index r_pending_waiting_semantic on pending_questions(store_id,semantic_key)
  where contract_version='v2' and status='WAITING';
create unique index r_pending_store_id on pending_questions(store_id,question_id);
create unique index r_session_scope_id on chat_sessions(store_id,member_id,session_id);
create unique index r_messages_session_id on chat_messages(session_id,message_id);

create table r_answer_receipts (
  receipt_id bigint generated always as identity primary key,
  store_id bigint not null,
  member_id bigint not null,
  session_id bigint not null,
  request_id varchar(80) not null,
  body_hash text not null,
  original_question text not null,
  resolved_query jsonb not null,
  context_snapshot jsonb,
  snapshot_id bigint not null,
  knowledge_revision bigint not null,
  user_message_id bigint not null,
  buddy_message_id bigint not null,
  pending_id bigint,
  response jsonb not null,
  execution_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(store_id,member_id,request_id),
  unique(store_id,receipt_id),
  foreign key(store_id,member_id,session_id) references chat_sessions(store_id,member_id,session_id),
  foreign key(session_id,user_message_id) references chat_messages(session_id,message_id),
  foreign key(session_id,buddy_message_id) references chat_messages(session_id,message_id),
  foreign key(store_id,pending_id) references pending_questions(store_id,question_id),
  foreign key(store_id,snapshot_id) references knowledge_snapshots(store_id,snapshot_id)
);
create table r_answer_citations (
  store_id bigint not null,
  receipt_id bigint not null,
  citation_order integer not null check(citation_order>=1),
  card_id bigint not null,
  card_version_id bigint not null,
  block_id varchar(40) not null,
  fact_revision_id bigint,
  raw_span_id bigint,
  source_id bigint not null,
  primary key(store_id,receipt_id,citation_order),
  check((fact_revision_id is null) <> (raw_span_id is null)),
  foreign key(store_id,receipt_id) references r_answer_receipts(store_id,receipt_id),
  foreign key(store_id,card_version_id) references card_versions(store_id,version_id),
  foreign key(store_id,card_version_id,block_id) references card_version_blocks(store_id,card_version_id,block_id),
  foreign key(store_id,card_version_id,block_id,fact_revision_id)
    references card_block_facts(store_id,card_version_id,block_id,fact_revision_id),
  foreign key(store_id,fact_revision_id) references fact_revisions(store_id,fact_revision_id),
  foreign key(store_id,raw_span_id) references raw_spans(store_id,raw_span_id),
  foreign key(store_id,source_id) references sources(store_id,source_id)
);
create function askbuddy_answer_receipt_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'answer history is immutable';
end;
$$;
create trigger r_answer_receipt_immutable before update or delete on r_answer_receipts
  for each row execute function askbuddy_answer_receipt_immutable();
create trigger r_answer_citation_immutable before update or delete on r_answer_citations
  for each row execute function askbuddy_answer_receipt_immutable();
commit;
