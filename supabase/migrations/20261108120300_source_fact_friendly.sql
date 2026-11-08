-- 2026-11-08 사용자 결정: '원문 그대로' 규칙 제거. 모델이 정리한 사람이 읽기 좋은 문장을 함께 둔다. 가산 변경만.
-- original_assertion 은 근거 원문 그대로 남는다. 서버가 숫자 검사를 통과한 문장만 사실 판의 assertion 으로 쓴다(app.ingest.friendly).
alter table source_facts add column if not exists assertion text;
