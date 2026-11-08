-- 계획 7 Task 6: 충돌에서 사장님이 고르지 않은 값('틀린 값'). 사실은 지우지 않고 여기에 기억한다. 가산 변경만.
-- 기억된 사실은 다시 충돌을 열지 않고(fact_ledger._record_conflicts) 카드 조립에 들어가지 않는다(fact_assembly).
create table if not exists fact_rejections (
  store_id             bigint not null references stores(store_id) on delete cascade,
  fact_id              bigint not null,
  rejected_revision_id bigint not null,
  conflict_id          bigint,
  rejected_by          bigint references users(user_id) on delete set null,
  rejected_at          timestamptz not null default now(),
  primary key (store_id, fact_id),
  constraint fact_rejections_fact_fkey foreign key (store_id, fact_id) references knowledge_facts(store_id, fact_id) on delete cascade
);
