begin;
create table r_search_lexicons (
  store_id bigint not null,
  version varchar(40) not null,
  content_hash text not null,
  entries jsonb not null,
  approved_by bigint not null,
  approved_at timestamptz not null default now(),
  primary key(store_id,version),
  unique(store_id,content_hash),
  foreign key(store_id,approved_by) references store_members(store_id,user_id)
);
create trigger r_search_lexicon_immutable before update or delete on r_search_lexicons
  for each row execute function askbuddy_answer_receipt_immutable();
commit;
