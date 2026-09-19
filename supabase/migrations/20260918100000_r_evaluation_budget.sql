-- Evaluation-only admission ledger. No grants to browser roles; reservations never refunded.
begin;
create table r_evaluation_budgets (
  store_id bigint not null references stores(store_id),
  campaign_id uuid not null,
  policy_hash text not null,
  policy jsonb not null,
  max_calls integer not null check(max_calls > 0),
  max_units bigint not null check(max_units > 0),
  reserved_calls integer not null default 0 check(reserved_calls >= 0 and reserved_calls <= max_calls),
  reserved_units bigint not null default 0 check(reserved_units >= 0 and reserved_units <= max_units),
  halted boolean not null default false,
  primary key(store_id,campaign_id)
);
create table r_evaluation_reservations (
  store_id bigint not null,
  campaign_id uuid not null,
  call_key text not null,
  evaluation_run_id bigint not null references evaluation_runs(run_id),
  reserved_units bigint not null check(reserved_units > 0),
  status text not null default 'RESERVED' check(status in ('RESERVED','OBSERVED','UNKNOWN','EXCEEDED')),
  observation_hash text,
  created_at timestamptz not null default now(),
  primary key(store_id,campaign_id,call_key),
  foreign key(store_id,campaign_id) references r_evaluation_budgets(store_id,campaign_id)
);
revoke all on r_evaluation_budgets,r_evaluation_reservations from public,anon,authenticated;
commit;
