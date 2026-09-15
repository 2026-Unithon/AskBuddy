-- 과거 평가 행은 바꾸지 않고 새 보류 판정을 저장할 수 있게 한다.
alter table extraction_results drop constraint if exists extraction_results_verdict_check;
alter table extraction_results add constraint extraction_results_verdict_check
  check (verdict in ('COVERED', 'PARTIAL', 'MISSING', 'UNDETERMINED'));
