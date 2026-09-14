-- 평가 실행에 PARTIAL 상태를 추가한다 (W0)
--
-- 왜:
--   자료 5건 중 5건이 처리에 실패했는데도 실행이 SUCCEEDED 로 닫혔다. 그 빈 실행
--   둘을 비교한 결과가 "차이 없음" 이었다 — 아무것도 안 한 두 실행이 일치한 것이다.
--   일부만 실패한 실행은 분모가 달라진 측정이라 성공과 같은 칸에 두면 안 된다.
--
--   `SUCCEEDED` 만 집계하는 비교 스크립트가 PARTIAL 을 자동으로 제외하고,
--   변동폭 리포트는 실패 횟수를 따로 보고한다. 실패는 그 설정의 성질이다.

begin;

alter table extraction_runs drop constraint if exists extraction_runs_status_check;
alter table extraction_runs add constraint extraction_runs_status_check
  check (status in ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED'));

comment on column extraction_runs.status is
  'RUNNING / SUCCEEDED / PARTIAL(일부 자료 실패) / FAILED. PARTIAL 은 분모가 달라진 '
  '측정이므로 성공 실행과 함께 집계하지 않는다';

commit;
