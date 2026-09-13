-- 13.1 평가 하네스 — 골든셋 문항, 평가 실행 이력, 문항별 결과.
--
-- 원칙: 이전 평가 결과를 덮어쓰지 않는다 (DEV_TODO 13.1).
--   · evaluation_results 는 INSERT 만 허용한다. UPDATE·DELETE 를 트리거가 막는다.
--   · evaluation_runs 는 RUNNING 동안만 갱신 가능하고, 종료되면 동결된다.
--   · 실행 삭제를 막기 위해 결과의 FK 는 cascade 가 아니라 restrict 다.
-- 격리: RLS 를 쓰지 않으므로(D1) 세 테이블 모두 store_id 를 필수로 갖는다.

begin;

-- ── 골든셋 문항 ────────────────────────────────────────────────────────────
create table if not exists evaluation_cases (
  case_id             bigint generated always as identity primary key,
  store_id            bigint      not null references stores(store_id) on delete cascade,
  case_key            varchar(80) not null,
  question            text        not null,
  -- HIT: 근거 기반 답변 기대 / MISS: 미등록 지식 / REFUSE: 답하면 안 되는 질문
  -- SAFE_ROUTE: 안전·위생·응급. 추측 금지하고 직접 확인 경로로 보내야 한다
  expected_kind       varchar(20) not null
    check (expected_kind in ('HIT', 'MISS', 'REFUSE', 'SAFE_ROUTE')),
  expected_card_ids   bigint[]    not null default '{}',
  expected_facts      text[]      not null default '{}',
  expected_category   varchar(100),
  expected_miss_reason varchar(40),
  -- 같은 사실을 어떤 말로 묻는가. 13.2 에서 표현 변형 커버리지를 세는 축이다
  question_style      varchar(30) not null default 'CANONICAL'
    check (question_style in (
      'CANONICAL', 'SYNONYM', 'SLANG', 'ABBREVIATION',
      'TYPO', 'STT_VARIANT', 'FOLLOW_UP'
    )),
  qa_relation         varchar(20)
    check (qa_relation in ('IDENTICAL', 'NEW', 'SUPPLEMENT', 'CONFLICT')),
  notes               text,
  is_active           boolean     not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (store_id, case_key),
  -- 기대 카드 없이 HIT 를 기대할 수 없다. 채점 기준이 없는 문항을 막는다
  constraint evaluation_cases_hit_needs_cards
    check (expected_kind <> 'HIT' or cardinality(expected_card_ids) > 0)
);

create index if not exists idx_evaluation_cases_store_active
  on evaluation_cases (store_id, is_active, case_key);

-- ── 평가 실행 ──────────────────────────────────────────────────────────────
create table if not exists evaluation_runs (
  run_id                 bigint generated always as identity primary key,
  store_id               bigint       not null references stores(store_id) on delete restrict,
  label                  varchar(120) not null,
  status                 varchar(20)  not null default 'RUNNING'
    check (status in ('RUNNING', 'SUCCEEDED', 'FAILED')),
  started_at             timestamptz  not null default now(),
  finished_at            timestamptz,
  -- 재현에 필요한 스냅샷. 하나라도 비면 나중에 결과를 해석할 수 없다
  code_version           varchar(80)  not null,
  prompt_version         varchar(100) not null,
  answer_model           varchar(100) not null,
  embedding_model        varchar(100) not null,
  answer_mode            varchar(20)  not null,
  retrieval_threshold    numeric(6,4) not null,
  retrieval_strong_score numeric(6,4) not null,
  feature_flags          jsonb        not null default '{}'::jsonb,
  settings               jsonb        not null default '{}'::jsonb,
  metrics                jsonb        not null default '{}'::jsonb,
  case_count             int          not null default 0 check (case_count >= 0),
  notes                  text,
  created_by             bigint       references users(user_id),
  created_at             timestamptz  not null default now()
);

create index if not exists idx_evaluation_runs_store_started
  on evaluation_runs (store_id, started_at desc);
create index if not exists idx_evaluation_runs_store_label
  on evaluation_runs (store_id, label, started_at desc);

-- ── 문항별 결과 ────────────────────────────────────────────────────────────
create table if not exists evaluation_results (
  result_id           bigint generated always as identity primary key,
  run_id              bigint      not null references evaluation_runs(run_id) on delete restrict,
  store_id            bigint      not null references stores(store_id) on delete restrict,
  case_id             bigint      not null references evaluation_cases(case_id) on delete restrict,
  -- 문항이 나중에 수정돼도 이 실행이 무엇을 물었는지는 남아야 한다
  case_key            varchar(80) not null,
  question            text        not null,
  expected_kind       varchar(20) not null,
  actual_kind         varchar(20) not null
    check (actual_kind in ('HIT', 'MISS', 'ERROR')),
  kind_correct        boolean     not null,
  miss_reason         varchar(40),
  expected_card_ids   bigint[]    not null default '{}',
  retrieved_card_ids  bigint[]    not null default '{}',
  citation_card_ids   bigint[]    not null default '{}',
  expected_hit_rank   int         check (expected_hit_rank is null or expected_hit_rank >= 1),
  top_card_id         bigint,
  wrong_card          boolean     not null default false,
  answer_source       varchar(20),
  grounding_status    varchar(20),
  answer_text         text,
  citation_count      int         not null default 0 check (citation_count >= 0),
  citation_precision  numeric(6,4) check (citation_precision between 0 and 1),
  fact_coverage       numeric(6,4) check (fact_coverage between 0 and 1),
  -- 근거 없는 답변. 목표 0 (MVP 정본 20-4)
  ungrounded          boolean     not null default false,
  retrieve_latency_ms int         check (retrieve_latency_ms >= 0),
  answer_latency_ms   int         check (answer_latency_ms >= 0),
  total_latency_ms    int         check (total_latency_ms >= 0),
  prompt_tokens       int         check (prompt_tokens >= 0),
  completion_tokens   int         check (completion_tokens >= 0),
  cost_usd            numeric(12,6) check (cost_usd >= 0),
  passed              boolean     not null,
  failure_kind        varchar(40),
  error               text,
  created_at          timestamptz not null default now(),
  unique (run_id, case_id)
);

create index if not exists idx_evaluation_results_run
  on evaluation_results (run_id, case_id);
create index if not exists idx_evaluation_results_run_failed
  on evaluation_results (run_id, passed);
create index if not exists idx_evaluation_results_store
  on evaluation_results (store_id, created_at desc);

-- ── 이력 동결 ──────────────────────────────────────────────────────────────
create or replace function askbuddy_evaluation_results_append_only()
returns trigger
language plpgsql
as $$
begin
  raise exception '평가 결과는 추가만 가능하다 (run_id=%, case_key=%)',
    old.run_id, old.case_key;
end;
$$;

drop trigger if exists trg_evaluation_results_append_only on evaluation_results;
create trigger trg_evaluation_results_append_only
before update or delete on evaluation_results
for each row execute function askbuddy_evaluation_results_append_only();

create or replace function askbuddy_evaluation_runs_freeze()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' then
    raise exception '평가 실행 이력은 삭제하지 않는다 (run_id=%)', old.run_id;
  end if;
  if old.status <> 'RUNNING' then
    raise exception '종료된 평가 실행은 변경할 수 없다 (run_id=%, status=%)',
      old.run_id, old.status;
  end if;
  if new.run_id <> old.run_id or new.store_id <> old.store_id
     or new.started_at <> old.started_at or new.code_version <> old.code_version then
    raise exception '평가 실행의 재현 정보는 변경할 수 없다 (run_id=%)', old.run_id;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_evaluation_runs_freeze on evaluation_runs;
create trigger trg_evaluation_runs_freeze
before update or delete on evaluation_runs
for each row execute function askbuddy_evaluation_runs_freeze();

create or replace function askbuddy_evaluation_cases_touch()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_evaluation_cases_touch on evaluation_cases;
create trigger trg_evaluation_cases_touch
before update on evaluation_cases
for each row execute function askbuddy_evaluation_cases_touch();

-- ── 기존 검수 품질 설문과 실행 이력 연결 ───────────────────────────────────
-- quality_evaluations 는 사람이 매기는 검수 품질 설문이다. 자동 평가 실행과
-- 같은 표에 섞지 않고, 같은 시점을 비교할 수 있게 포인터만 둔다.
alter table quality_evaluations
  add column if not exists evaluation_run_id bigint references evaluation_runs(run_id);

create index if not exists idx_quality_evaluations_run
  on quality_evaluations (evaluation_run_id);

commit;
