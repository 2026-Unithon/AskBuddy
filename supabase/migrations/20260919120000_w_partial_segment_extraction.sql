-- W1 — 구간 일부가 실패한 자료를 성공으로 적지 않는다.
--
-- 지금까지는 10구간 중 3구간을 잃어도 성공한 구간만 합쳐 자료가 DONE 으로 끝났고,
-- 작업 자료 행은 카드가 하나라도 있으면 SUCCEEDED 였다. 점주는 빠진 내용을 모른다.
-- 잃은 구간을 기록하고 상태에 PARTIAL 을 허용한다.

begin;

alter table ingest_job_sources
  add column if not exists segments_total int,
  add column if not exists segments_failed int,
  add column if not exists failed_segment_ids text[];

alter table ingest_job_sources
  drop constraint if exists ingest_job_sources_status_check;

alter table ingest_job_sources
  add constraint ingest_job_sources_status_check
  check (status in (
    'QUEUED', 'EXTRACTING', 'CLASSIFYING',
    'SUCCEEDED', 'PARTIAL', 'NO_RESULT', 'FAILED'
  ));

alter table ingest_job_sources
  drop constraint if exists ingest_job_sources_segments_check;

alter table ingest_job_sources
  add constraint ingest_job_sources_segments_check
  check (
    segments_failed is null
    or (segments_total is not null
        and segments_failed >= 0
        and segments_failed <= segments_total)
  );

comment on column ingest_job_sources.segments_failed is
  '추출에서 잃은 구간 수. 0 보다 크면 자료 상태는 PARTIAL 이다 (W1)';
comment on column ingest_job_sources.failed_segment_ids is
  '잃은 구간 이름. 해당 구간만 다시 돌리기 위한 근거 (W1)';

commit;
