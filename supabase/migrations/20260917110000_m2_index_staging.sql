-- M2: 준비 내용은 durable하지만 공개 포인터와 결합되기 전 검색에 노출되지 않는다.
begin;
create table r_index_preparations (
  prepared_id bigint generated always as identity primary key,
  store_id bigint not null references stores(store_id),
  member_id bigint not null references store_members(member_id),
  idempotency_key varchar(80) not null,
  request_hash text not null,
  content_hash text not null,
  content jsonb not null,
  expected_publication_revision bigint not null check (expected_publication_revision >= 0),
  embedding_model text not null,
  index_config_version text not null,
  state text not null check(state in ('PREPARING','PREPARED','FAILED','CONSUMED')),
  claim_id uuid not null,
  attempt_no integer not null default 1 check(attempt_no >= 1),
  lease_expires_at timestamptz not null,
  expires_at timestamptz not null,
  error_code text,
  created_at timestamptz not null default now(),
  unique(store_id,member_id,idempotency_key),
  unique(store_id,prepared_id)
);
create table r_index_documents (
  store_id bigint not null,
  prepared_id bigint not null,
  card_id bigint not null,
  card_version_id bigint not null,
  block_id varchar(40) not null,
  approved_text text not null,
  retrieval_text text not null,
  embedding vector(1536) not null,
  lexical_tsv tsvector generated always as (to_tsvector('simple', retrieval_text)) stored,
  primary key(store_id,prepared_id,card_id,block_id),
  foreign key(store_id,prepared_id) references r_index_preparations(store_id,prepared_id)
);
create index r_index_documents_lexical on r_index_documents using gin(lexical_tsv);
create table r_index_publications (
  store_id bigint not null,
  snapshot_id bigint not null,
  prepared_id bigint not null,
  primary key(store_id,snapshot_id),
  foreign key(store_id,snapshot_id) references knowledge_snapshots(store_id,snapshot_id),
  foreign key(store_id,prepared_id) references r_index_preparations(store_id,prepared_id),
  unique(store_id,prepared_id)
);
create function askbuddy_index_content_immutable() returns trigger language plpgsql as $$
begin
  if (new.store_id,new.member_id,new.idempotency_key,new.request_hash,new.content_hash,
      new.content,new.expected_publication_revision,new.embedding_model,new.index_config_version,new.expires_at)
     is distinct from
     (old.store_id,old.member_id,old.idempotency_key,old.request_hash,old.content_hash,
      old.content,old.expected_publication_revision,old.embedding_model,old.index_config_version,old.expires_at) then
    raise exception 'index preparation content is immutable';
  end if;
  if (old.state in ('CONSUMED','FAILED') and new.state <> old.state)
     or (old.state='PREPARED' and new.state not in ('PREPARED','CONSUMED')) then
    raise exception 'index preparation cannot move backwards';
  end if;
  return new;
end;
$$;
create trigger r_index_content_immutable before update on r_index_preparations
  for each row execute function askbuddy_index_content_immutable();
create function askbuddy_index_documents_immutable() returns trigger language plpgsql as $$
declare preparation_state text;
begin
  if TG_OP <> 'INSERT' then
    raise exception 'prepared index documents are append-only';
  end if;
  select state into preparation_state from r_index_preparations
    where store_id=new.store_id and prepared_id=new.prepared_id for share;
  if preparation_state is distinct from 'PREPARING' then
    raise exception 'cannot append documents after preparation';
  end if;
  return new;
end;
$$;
create trigger r_index_documents_immutable before insert or update or delete on r_index_documents
  for each row execute function askbuddy_index_documents_immutable();
commit;
