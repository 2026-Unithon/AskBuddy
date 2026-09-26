-- W 재시도: 검증한 입력 지문과 조립 대기 추출을 작업 자료에 보존한다.
begin;
alter table ingest_job_sources add column recovery_state jsonb;
alter table ingest_job_sources add constraint ingest_job_sources_recovery_check check (
  recovery_state is null or coalesce((
    jsonb_typeof(recovery_state) = 'object'
    and recovery_state->>'version' = '1'
    and recovery_state->>'phase' in ('EXTRACTED', 'COMMITTED')
    and recovery_state->>'layout_hash' ~ '^[0-9a-f]{64}$'
    and recovery_state ?& array['version','phase','layout_hash','outcome','ledger_ids']
    and jsonb_typeof(recovery_state->'outcome') = 'object'
    and jsonb_typeof(recovery_state->'ledger_ids') = 'object'
  ), false)
);
comment on column ingest_job_sources.recovery_state is
  '비공개 작업 복구본: 입력 지문, 조립 대기 사실과 원장 ID. 카드/구간 완료와 원자 커밋';
commit;
