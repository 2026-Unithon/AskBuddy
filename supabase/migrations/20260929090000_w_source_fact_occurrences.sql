-- 배포 순서 (2026-09-29): 이 migration 을 **먼저 적용한 뒤** 이 브랜치 코드를 배포한다.
--   mock·real 수집 모두 extraction_raw_responses(20260928090000)와
--   source_fact_occurrences(20260929090000)에 쓴다. 표가 없으면 수집이 실패한다.
--
-- W1-4 — 근거 위치(occurrence) 보존.
--
-- 원장(source_facts)은 unique(source_id, content_hash) 로 같은 사실을 한 행으로 합친다.
-- 그래서 같은 사실이 한 자료의 두 쪽·두 메시지·두 시각에 나오면 두 번째 자리가 사라졌다.
-- 이 표는 자리마다 한 행을 남긴다. source_facts.locator 는 처음 적힌 위치 그대로 둔다.
--
-- 규칙:
--   1. 가산 표다. W2 가 fact_revisions 기준의 fact_occurrences(M1)로 옮긴다. 지금 W 수집은
--      fact_revisions·fact_occurrences 에 쓰지 않는다.
--   2. 같은 사실의 같은 자리는 한 번만 — unique(fact_id, occurrence_hash). 같은 작업을 다시
--      돌려도 늘지 않는다. hash 는 부모 구간·위치 종류·위치로 만든다(이름표·응답 ID 제외).
--   3. 매장 경계 — (store_id, fact_id) 와 (store_id, source_id) 복합 FK 로 다른 매장의
--      사실·자료를 가리키지 못한다. RLS 미사용(D1), 조회 격리는 API 코드가 store_id 로 한다.
--   4. 보관(D20) — 자료 FK 에 cascade 를 두지 않는다. tombstone 은 자료 행을 지우지 않고,
--      물리 삭제는 원장 사실이 남아 있으면 이미 막힌다(source_facts restrict). 위치는 사실에
--      딸려 있다 — 사실을 물리적으로 지우는 절차(평가 매장 초기화·개인정보 삭제)에서만
--      함께 지워진다(fact FK cascade).
--   5. 원래 응답 ID 는 선택이다. 기록하지 않은 호출·복구본은 null 이다. 원래 응답은 지우지
--      않지만(W1-1) 물리 삭제 절차가 생기면 위치는 남고 참조만 비운다(set null).

begin;

-- 복합 FK 의 부모 키. fact_id 가 이미 PK 라 값의 뜻은 바뀌지 않는다
create unique index if not exists uq_source_facts_store_fact
  on source_facts (store_id, fact_id);

create table if not exists source_fact_occurrences (
  occurrence_id    bigint generated always as identity primary key,
  store_id         bigint      not null references stores(store_id) on delete cascade,
  fact_id          bigint      not null,
  source_id        bigint      not null,
  -- 부모 구간(seg3). 구간 없는 자료는 null
  segment_id       varchar(80),
  -- 그 실행 안의 이름표(seg3.2:f1). 되짚기용이며 열쇠가 아니다
  local_ref        varchar(80),
  locator_type     varchar(20) not null default 'WHOLE_SOURCE'
    check (locator_type in ('PAGE', 'TIMESTAMP', 'LINE', 'WHOLE_SOURCE')),
  locator          jsonb       not null default '{}'::jsonb
    check (jsonb_typeof(locator) = 'object'),
  raw_response_id  bigint      references extraction_raw_responses(raw_response_id)
    on delete set null,
  occurrence_hash  varchar(64) not null,
  -- 서버 검사 판정(W1-4). [{"field","verdict","value"}]. verdict:
  --   UNGROUNDED_TEXT(글에서 확인 안 됨, 값 남김) · NEEDS_IMAGE_CHECK(첨부 확인 필요, 값 남김)
  --   · CLEARED(플래그로 비움) · REMOVED(없는 requires 참조를 뺌). occurrence_hash 에 넣지 않는다
  check_flags      jsonb       not null default '[]'::jsonb
    check (jsonb_typeof(check_flags) = 'array'),
  created_at       timestamptz not null default now(),

  constraint source_fact_occurrences_fact_fkey
    foreign key (store_id, fact_id) references source_facts(store_id, fact_id)
    on delete cascade,
  -- 규칙 4 — cascade 없음. 삭제 판정은 문장 끝에서 한다(no action)
  constraint source_fact_occurrences_source_fkey
    foreign key (store_id, source_id) references sources(store_id, source_id),
  constraint source_fact_occurrences_unique unique (fact_id, occurrence_hash)
);

create index if not exists idx_source_fact_occurrences_store_source
  on source_fact_occurrences (store_id, source_id, occurrence_id);
create index if not exists idx_source_fact_occurrences_store_fact
  on source_fact_occurrences (store_id, fact_id);

comment on table source_fact_occurrences is
  '사실의 근거 위치 (W1-4). 같은 사실의 자리마다 한 행. W2 가 fact_occurrences 로 이관';
comment on column source_fact_occurrences.check_flags is
  '서버 검사 판정 목록 (UNGROUNDED_TEXT/NEEDS_IMAGE_CHECK/CLEARED/REMOVED). 재시도 열쇠가 아니다';
comment on column source_fact_occurrences.occurrence_hash is
  'sha256([segment_id, locator_type, locator]) — 재실행 중복 방지 열쇠';

commit;
