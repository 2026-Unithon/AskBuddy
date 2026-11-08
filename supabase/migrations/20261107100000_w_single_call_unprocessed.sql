-- 한 번 호출 추출(2026-11-07, W_SINGLE_CALL_EXTRACT_DESIGN S9·S10) — 가산형.
-- 3번 시도 뒤에도 처리하지 못한 입력 줄 범위를 작업 자료 행에 남긴다. 뽑힌 사실은 그대로 성공으로 반영하고,
-- 이 범위만 사장님께 위치·사유와 함께 보여 준다.
-- 원소: {"from_line": int, "to_line": int, "reason": "TRUNCATED"|"CALL_FAILED"|"EMPTY",
--        "first_line": text, "attempts": int, "owner_retry_used": bool}
-- 줄 번호가 없는 자료(사진 등)는 from_line = to_line = 0 이다.
alter table ingest_job_sources
    add column if not exists unprocessed_ranges jsonb;

comment on column ingest_job_sources.unprocessed_ranges is
    '한 번 호출 추출이 끝내 처리하지 못한 입력 줄 범위 목록(S9). null 이면 없음. owner_retry_used 는 사장님 다시 시도를 쓴 범위(S10)';
