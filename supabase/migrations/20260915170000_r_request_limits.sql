-- R 독립 보안 선행: worker 사이에 공유되는 질문 유입/동시 호출 제한.
begin;
create table r_request_leases (
  request_id uuid primary key,
  store_id bigint not null references stores(store_id) on delete cascade,
  user_id bigint not null references users(user_id) on delete cascade,
  started_at timestamptz not null default clock_timestamp(),
  expires_at timestamptz not null,
  finished_at timestamptz
);
create index r_request_leases_scope on r_request_leases(store_id, started_at);
commit;
