-- 배포 순서 (2026-09-29): 이 migration 을 **먼저 적용한 뒤** 이 브랜치 코드를 배포한다.
--   mock·real 수집 모두 extraction_raw_responses(20260928090000)와
--   source_fact_occurrences(20260929090000)에 쓴다. 표가 없으면 수집이 실패한다.
--
-- W1-1 — 모델 원래 응답 보존.
--
-- 추출 결과가 이상할 때 "모델이 실제로 뭐라고 답했나" 를 되짚으려면 응답 원문이 남아야
-- 한다. 지금까지는 JSON 파싱이 실패하면 응답이 그대로 사라져, 잘린 출력(MAX_TOKENS)인지
-- 형식 오류인지 프롬프트 문제인지 가를 수 없었다.
--
-- 규칙:
--   1. 파싱 **전에** 한 행을 남긴다. 파싱 결과(parsed_ok·error)는 뒤에 한 번만 적는다.
--      parsed_ok 가 null 이면 미판정(프로세스가 파싱 전에 죽었거나 표시 저장 실패)이다.
--   2. 보관 — 자료 tombstone(D20)과 같은 보존 원칙. 자료를 지워도 이 기록은 지우지 않는다.
--      자료·작업·평가 실행 FK 를 두지 않는다 (ai_usage_attempts 와 같다). FK 를 두면
--      cascade 는 기록을 지우고, restrict 는 자료 물리 삭제·평가 매장 초기화를 막는다.
--      매장 FK 는 restrict — 매장 귀속 없는 행은 만들지 않는다 (D1).
--      물리 삭제는 개인정보 삭제 절차(별도 운영 절차)로만 한다. 이번 범위가 아니다.
--   3. 원문은 불변이다. 트리거가 파싱 결과·재사용 키를 null 에서 한 번 채우는 것만 허용한다.
--   4. reuse_key 는 W1-3 이 채우고 조회한다. 지금은 열과 부분 인덱스만 둔다.
--   5. RLS 미사용(D1). 매장 격리는 API 코드가 store_id 로 한다.

begin;

create table if not exists extraction_raw_responses (
  raw_response_id   bigint generated always as identity primary key,
  store_id          bigint      not null references stores(store_id) on delete restrict,

  -- 어느 자료·작업·실행·구간의 호출인가. FK 없음 — 규칙 2
  source_id         bigint,
  job_id            bigint,
  extraction_run_id bigint,
  -- 같은 작업을 다시 돌린 실행을 가르는 표지 (job_worker 의 run_tag)
  run_tag           bigint,
  segment_id        varchar(80),
  -- 원가 원장(ai_usage_attempts.logical_call_id)과 잇는 열쇠
  logical_call_id   varchar(80),

  stage             varchar(20) not null check (stage in ('EXTRACT', 'ASSEMBLE')),
  model             varchar(100) not null,
  -- mock 응답을 모델 성능으로 집계하지 않는다 (D10)
  mode              varchar(10) not null check (mode in ('real', 'mock')),
  prompt_hash       varchar(80),
  schema_version    varchar(120),
  reuse_key         varchar(200),
  -- 공급자가 응답을 멈춘 이유 (STOP·MAX_TOKENS …). SDK enum 이면 이름 문자열
  finish_reason     varchar(40),
  response_text     text        not null,
  usage             jsonb       not null default '{}'::jsonb
    check (jsonb_typeof(usage) = 'object'),

  parsed_ok         boolean,
  error             text,
  created_at        timestamptz not null default now(),

  -- 파싱 실패면 사유가 있어야 하고, 성공이면 사유가 없어야 한다
  constraint extraction_raw_responses_error_check check (
    (parsed_ok is null)
    or (parsed_ok and error is null)
    or (not parsed_ok and error is not null)
  )
);

create index if not exists idx_raw_responses_store_source
  on extraction_raw_responses (store_id, source_id, raw_response_id);
create index if not exists idx_raw_responses_store_run
  on extraction_raw_responses (store_id, extraction_run_id)
  where extraction_run_id is not null;
-- 재사용 조회 (W1-3). 파싱에 성공한 응답만 재사용 후보다
create index if not exists idx_raw_responses_reuse
  on extraction_raw_responses (store_id, reuse_key)
  where parsed_ok;

-- 원문 불변. 파싱 결과와 재사용 키만 null 에서 한 번 채울 수 있다
create or replace function askbuddy_raw_response_guard()
returns trigger language plpgsql as $$
begin
  if (new.raw_response_id, new.store_id, new.source_id, new.job_id,
      new.extraction_run_id, new.run_tag, new.segment_id, new.logical_call_id,
      new.stage, new.model, new.mode, new.prompt_hash, new.schema_version,
      new.finish_reason, new.response_text, new.usage, new.created_at)
     is distinct from
     (old.raw_response_id, old.store_id, old.source_id, old.job_id,
      old.extraction_run_id, old.run_tag, old.segment_id, old.logical_call_id,
      old.stage, old.model, old.mode, old.prompt_hash, old.schema_version,
      old.finish_reason, old.response_text, old.usage, old.created_at) then
    raise exception '원래 응답(raw_response_id=%)은 바꿀 수 없다', old.raw_response_id;
  end if;
  if old.parsed_ok is not null
     and (new.parsed_ok, new.error) is distinct from (old.parsed_ok, old.error) then
    raise exception '원래 응답(raw_response_id=%)의 파싱 결과는 이미 적혔다', old.raw_response_id;
  end if;
  if old.reuse_key is not null and new.reuse_key is distinct from old.reuse_key then
    raise exception '원래 응답(raw_response_id=%)의 재사용 키는 이미 적혔다', old.raw_response_id;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_raw_response_guard on extraction_raw_responses;
create trigger trg_raw_response_guard
before update on extraction_raw_responses
for each row execute function askbuddy_raw_response_guard();

comment on table extraction_raw_responses is
  '모델 원래 응답 (W1-1). 파싱 전에 저장, 자료 삭제로 지우지 않음, 물리 삭제는 개인정보 삭제 절차만';
comment on column extraction_raw_responses.parsed_ok is
  'null=미판정, true=응답 스키마 파싱 성공, false=실패(error 필수)';
comment on column extraction_raw_responses.reuse_key is
  '같은 입력 재실행 시 재사용 조회 열쇠 (W1-3 이 채운다)';

commit;
