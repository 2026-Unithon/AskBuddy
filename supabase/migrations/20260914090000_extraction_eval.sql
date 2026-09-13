-- 13.2 추출 평가 — 쓰기 경로(자료 → 카드)의 품질 이력.
--
-- 읽기 경로(evaluation_runs)와 표를 나눈다. 재는 대상도 지표도 다르고,
-- 13단계(쓰기)와 14단계(읽기)의 책임 분리를 스키마에서도 지킨다.
--
-- 이력 동결 규칙은 읽기 쪽과 같다. 이전 결과를 덮어쓰지 않는다.

begin;

create table if not exists extraction_runs (
  run_id          bigint generated always as identity primary key,
  store_id        bigint       not null references stores(store_id) on delete restrict,
  label           varchar(120) not null,
  status          varchar(20)  not null default 'RUNNING'
    check (status in ('RUNNING', 'SUCCEEDED', 'FAILED')),
  started_at      timestamptz  not null default now(),
  finished_at     timestamptz,
  -- 재현 정보
  code_version    varchar(80)  not null,
  prompt_version  varchar(100) not null,
  extract_model   varchar(100) not null,
  stt_model       varchar(100) not null,
  ingest_mode     varchar(20)  not null,
  feature_flags   jsonb        not null default '{}'::jsonb,
  settings        jsonb        not null default '{}'::jsonb,
  metrics         jsonb        not null default '{}'::jsonb,
  -- 정답지가 점주 확인인지 팀 자체 판정인지. 수치 해석이 달라진다
  truth_confidence varchar(20) not null default 'TEST'
    check (truth_confidence in ('OWNER', 'TEST')),
  source_count    int          not null default 0 check (source_count >= 0),
  fact_count      int          not null default 0 check (fact_count >= 0),
  card_count      int          not null default 0 check (card_count >= 0),
  notes           text,
  created_by      bigint       references users(user_id),
  created_at      timestamptz  not null default now()
);

create index if not exists idx_extraction_runs_store_started
  on extraction_runs (store_id, started_at desc);
create index if not exists idx_extraction_runs_store_label
  on extraction_runs (store_id, label, started_at desc);

create table if not exists extraction_results (
  result_id     bigint generated always as identity primary key,
  run_id        bigint      not null references extraction_runs(run_id) on delete restrict,
  store_id      bigint      not null references stores(store_id) on delete restrict,
  -- 정답지의 fact_id. 정답지가 나중에 바뀌어도 이 실행이 무엇을 쟀는지는 남아야 한다
  fact_id       varchar(40) not null,
  subject       text        not null,
  variant       varchar(20),
  attribute     text        not null,
  value         text        not null,
  must_have     boolean     not null default false,
  source_key    varchar(80) not null,
  source_type   varchar(20) not null,
  verdict       varchar(20) not null
    check (verdict in ('COVERED', 'PARTIAL', 'MISSING')),
  card_id       bigint,
  score         numeric(6,4) check (score between 0 and 1),
  reason        text,
  subject_hit   boolean not null default false,
  value_hit     boolean not null default false,
  variant_hit   boolean not null default false,
  created_at    timestamptz not null default now(),
  unique (run_id, fact_id)
);

create index if not exists idx_extraction_results_run
  on extraction_results (run_id, verdict);
create index if not exists idx_extraction_results_store
  on extraction_results (store_id, created_at desc);

-- ── 이력 동결 ──────────────────────────────────────────────────────────────
create or replace function askbuddy_extraction_results_append_only()
returns trigger
language plpgsql
as $$
begin
  raise exception '추출 평가 결과는 추가만 가능하다 (run_id=%, fact_id=%)',
    old.run_id, old.fact_id;
end;
$$;

drop trigger if exists trg_extraction_results_append_only on extraction_results;
create trigger trg_extraction_results_append_only
before update or delete on extraction_results
for each row execute function askbuddy_extraction_results_append_only();

create or replace function askbuddy_extraction_runs_freeze()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' then
    raise exception '추출 평가 실행 이력은 삭제하지 않는다 (run_id=%)', old.run_id;
  end if;
  if old.status <> 'RUNNING' then
    raise exception '종료된 추출 평가 실행은 변경할 수 없다 (run_id=%, status=%)',
      old.run_id, old.status;
  end if;
  if new.run_id <> old.run_id or new.store_id <> old.store_id
     or new.started_at <> old.started_at or new.code_version <> old.code_version then
    raise exception '추출 평가 실행의 재현 정보는 변경할 수 없다 (run_id=%)', old.run_id;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_extraction_runs_freeze on extraction_runs;
create trigger trg_extraction_runs_freeze
before update or delete on extraction_runs
for each row execute function askbuddy_extraction_runs_freeze();

commit;
