-- MC0 (CP-00A) — 유료 호출 원장.
--
-- D21(매장당 월 3,000원)은 잴 수 없으면 집행할 수 없는 약속이다.
-- 지금은 읽기 경로만 토큰을 남기고 추출·STT·임베딩·Storage 는 전혀 안 잰다.
-- 등록 원가의 대부분이 그쪽인데 보이지 않는다.
--
-- 규칙 셋:
--   1. 결측과 0 을 구분한다. 무상 항목만 0 이고 못 잰 것은 null 이다.
--      0 으로 채우면 총액이 사실보다 싸 보이고 그 수치로 D21 통과를 선언하게 된다.
--   2. 호출 1회 = 1행. 한 호출이 여러 자료를 조립해도 receipt 는 하나다.
--   3. 확정 행은 불변. 늦은 정산·요율 재계산은 append 로 남긴다 —
--      과거 보고서를 조용히 바꾸면 무엇을 보고 판단했는지 되짚을 수 없다.

begin;

create table if not exists ai_usage_attempts (
  usage_attempt_id bigint generated always as identity primary key,
  -- 매장 귀속 없는 비용은 D21 계산에 쓸 수 없다 (D1 과 같은 취지)
  store_id      bigint      not null references stores(store_id) on delete restrict,

  cost_phase    varchar(20) not null check (cost_phase in ('REGISTRATION', 'OPERATING')),
  -- 평가·개발 호출을 고객 월 비용에 합산하면 D21 이 거짓으로 실패한다
  cost_purpose  varchar(20) not null default 'PRODUCT'
    check (cost_purpose in ('PRODUCT', 'EVALUATION', 'DEVELOPMENT')),
  stage         varchar(20) not null check (stage in (
    'STT','EXTRACT','ASSEMBLE','CLASSIFY','RELATION',
    'EMBED','QUERY','RERANK','ANSWER','VALIDATE')),

  -- 같은 논리 호출의 재시도를 하나로 묶는다. 재시도를 새 호출로 세면 원가가 부풀려진다
  logical_call_id varchar(80) not null,
  attempt_no      int         not null default 1 check (attempt_no >= 1),

  registration_campaign_id varchar(80),
  operation_id             varchar(80),
  job_id            bigint,
  source_id         bigint,
  segment_id        varchar(80),
  question_id       bigint,
  extraction_run_id bigint,
  evaluation_run_id bigint,

  status        varchar(20) not null default 'STARTED'
    check (status in ('STARTED','SUCCEEDED','FAILED','UNKNOWN')),
  requested_model varchar(100) not null,
  reported_model  varchar(100),
  provider_request_id varchar(200),
  -- mock 실행을 원가로 집계하지 않는다 (D10)
  mode          varchar(10) not null default 'real' check (mode in ('real','mock')),
  prompt_hash   varchar(80),
  config_hash   varchar(80),
  rate_card_version varchar(40),

  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  latency_ms    int check (latency_ms >= 0),
  error_code    varchar(80),
  cache_state   varchar(40),

  -- 공급자가 보고한 과금 단위. 못 받은 값은 null 이다
  prompt_tokens     bigint check (prompt_tokens >= 0),
  completion_tokens bigint check (completion_tokens >= 0),
  cached_tokens     bigint check (cached_tokens >= 0),
  thought_tokens    bigint check (thought_tokens >= 0),
  billable_units    numeric(18,6) check (billable_units >= 0),
  billable_unit_name varchar(40),
  -- 공급자 응답 원형. 새 과금 항목이 생겨도 과거 호출을 다시 해석할 수 있다
  raw_usage     jsonb,

  input_bytes        bigint check (input_bytes >= 0),
  media_duration_sec numeric(12,3) check (media_duration_sec >= 0),
  page_count         int check (page_count >= 0),
  frame_count        int check (frame_count >= 0),

  usage_status  varchar(20) not null default 'UNKNOWN'
    check (usage_status in ('COMPLETE','PARTIAL','UNKNOWN','NOT_BILLABLE')),
  missing_reason varchar(200),

  currency      varchar(8) not null default 'USD',
  known_cost_usd numeric(18,8) check (known_cost_usd >= 0),
  -- 관측이 불완전하면 총액을 내지 않는다. null 이 정직한 값이다
  cost_usd       numeric(18,8) check (cost_usd >= 0),
  price_status  varchar(20) not null default 'NO_RATE'
    check (price_status in ('PRICED','NO_RATE','UNKNOWN_UNITS')),

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  -- 같은 논리 호출의 같은 시도를 두 번 세지 않는다
  unique (store_id, logical_call_id, attempt_no),
  -- 관측이 불완전한데 총액이 있으면 그 총액은 거짓이다
  constraint ai_usage_attempts_cost_needs_complete
    check (cost_usd is null or usage_status in ('COMPLETE','NOT_BILLABLE'))
);

create index if not exists idx_usage_store_phase
  on ai_usage_attempts (store_id, cost_phase, started_at desc);
create index if not exists idx_usage_store_purpose_month
  on ai_usage_attempts (store_id, cost_purpose, started_at);
create index if not exists idx_usage_extraction_run
  on ai_usage_attempts (extraction_run_id) where extraction_run_id is not null;

-- ── 확정 후 불변 ───────────────────────────────────────────────────────────
-- STARTED 인 동안만 갱신할 수 있다. 확정된 비용을 나중에 고치면
-- 그때 무엇을 보고 판단했는지 되짚을 수 없다.
create or replace function askbuddy_usage_attempt_freeze()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'DELETE' then
    raise exception '원가 원장은 삭제하지 않는다 (usage_attempt_id=%)', old.usage_attempt_id;
  end if;
  if old.status <> 'STARTED' then
    raise exception
      '확정된 호출 기록은 변경할 수 없다 (usage_attempt_id=%, status=%). 정산은 append 로 남긴다',
      old.usage_attempt_id, old.status;
  end if;
  if new.store_id <> old.store_id
     or new.logical_call_id <> old.logical_call_id
     or new.attempt_no <> old.attempt_no
     or new.started_at <> old.started_at then
    raise exception '귀속·식별 정보는 변경할 수 없다 (usage_attempt_id=%)', old.usage_attempt_id;
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_usage_attempt_freeze on ai_usage_attempts;
create trigger trg_usage_attempt_freeze
before update or delete on ai_usage_attempts
for each row execute function askbuddy_usage_attempt_freeze();

-- ── 늦은 정산·요율 재계산 ──────────────────────────────────────────────────
-- 원장을 고치지 않고 여기에 쌓는다. 언제 무슨 근거로 금액이 바뀌었는지 남는다.
create table if not exists cost_assessments (
  assessment_id bigint generated always as identity primary key,
  usage_attempt_id bigint not null references ai_usage_attempts(usage_attempt_id) on delete restrict,
  store_id      bigint not null references stores(store_id) on delete restrict,
  rate_card_version varchar(40) not null,
  known_cost_usd numeric(18,8),
  cost_usd       numeric(18,8),
  price_status   varchar(20) not null,
  reason        varchar(200) not null,
  created_at    timestamptz not null default now()
);

create index if not exists idx_cost_assessments_attempt
  on cost_assessments (usage_attempt_id, created_at desc);

-- ── extraction_runs summary ────────────────────────────────────────────────
-- 원장에서 만들어 넣는 가산형 컬럼. 부분 관측은 known_cost 로만 더하고
-- 전체 미확정이면 cost_usd 는 null 이다.
alter table extraction_runs
  add column if not exists prompt_tokens       bigint check (prompt_tokens >= 0),
  add column if not exists completion_tokens   bigint check (completion_tokens >= 0),
  -- 원본 고유 bytes 와 실제 전송량은 다르다. 재시도가 있으면 전송량이 더 크다
  add column if not exists input_bytes         bigint check (input_bytes >= 0),
  add column if not exists submitted_input_bytes bigint check (submitted_input_bytes >= 0),
  add column if not exists media_duration_sec  numeric(12,3),
  add column if not exists document_pages      int,
  add column if not exists ai_attempt_count    int check (ai_attempt_count >= 0),
  add column if not exists retry_count         int check (retry_count >= 0),
  add column if not exists unknown_attempt_count int check (unknown_attempt_count >= 0),
  add column if not exists known_cost_usd      numeric(18,8),
  add column if not exists cost_usd            numeric(18,8),
  add column if not exists cost_status         varchar(20)
    check (cost_status is null or cost_status in ('COMPLETE','PARTIAL','UNKNOWN','NOT_BILLABLE')),
  add column if not exists cost_phase          varchar(20)
    check (cost_phase is null or cost_phase in ('REGISTRATION','OPERATING')),
  add column if not exists cost_report_id      bigint;

comment on table ai_usage_attempts is
  '유료 호출 원장. 호출 1회 = 1행. 결측과 0 을 구분한다 (CP-00A)';
comment on column ai_usage_attempts.cost_usd is
  '전부 관측·가격 책정됐을 때만 값이다. 하나라도 비면 null — 0 으로 채우면 총액이 사실보다 싸 보인다';
comment on table cost_assessments is
  '늦은 정산·요율 재계산. 원장을 고치지 않고 append 한다 (CP-00A)';

commit;
