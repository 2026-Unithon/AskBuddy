-- 추출 손실을 map(뽑기)과 assembly(조립)로 가른다.
--
-- 지금까지 채점은 "카드 본문에 값이 있나" 하나만 봤다. 그래서 손실이 나와도
-- 모델이 사실을 못 뽑은 것인지, 뽑았는데 카드에 안 실린 것인지 구분할 수 없었다.
-- 원장(source_facts)이 생겼으므로 둘을 갈라 본다.
--
--   원장 O / 카드 O  → 정상
--   원장 O / 카드 X  → 조립 손실 (뽑았는데 카드에 안 실림)
--   원장 X / 카드 O  → 카드 본문에 녹아 있으나 사실로는 안 뽑힘
--   원장 X / 카드 X  → 추출 손실 (애초에 못 뽑음)
--
-- 이 구분이 13.4 의 2패스가 어디를 고쳐야 하는지 정한다.

begin;

alter table extraction_results
  add column if not exists in_ledger boolean not null default false,
  add column if not exists ledger_fact_id bigint,
  -- 위 2x2 를 한 글자로 요약한다. 집계와 리포트가 이걸 쓴다
  add column if not exists loss_stage varchar(20)
    check (loss_stage is null or loss_stage in ('OK', 'ASSEMBLY', 'CARD_ONLY', 'EXTRACTION'));

comment on column extraction_results.in_ledger is
  '추출이 이 사실을 source_facts 에 뽑아냈는가';
comment on column extraction_results.loss_stage is
  'OK=정상 · ASSEMBLY=뽑았으나 카드에 없음 · CARD_ONLY=카드에만 · EXTRACTION=아예 못 뽑음';

create index if not exists idx_extraction_results_loss_stage
  on extraction_results (run_id, loss_stage);

commit;
