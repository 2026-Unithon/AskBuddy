-- 순위 품질 지표를 문항별로 보존한다.
--
-- '기대 카드가 1위인가' 만 보면 1위→3위 저하가 통과율에 안 잡힌다.
-- MRR(역순위)과 nDCG 를 문항 단위로 남겨야 나중에 실행끼리 다시 집계할 수 있다.
-- 13.2 기준선을 찍기 전에 넣는다. 기준선 이후에 추가하면 그 기준선과 비교가 불가능하다.
--
-- ALTER TABLE 은 DDL 이라 evaluation_results 의 append-only 트리거(행 단위)를 건드리지 않는다.

begin;

alter table evaluation_results
  add column if not exists reciprocal_rank numeric(6,4)
    check (reciprocal_rank is null or reciprocal_rank between 0 and 1),
  add column if not exists ndcg numeric(6,4)
    check (ndcg is null or ndcg between 0 and 1),
  -- 검색 깊이(top_k)보다 큰 k 는 의미가 없다. 어떤 k 로 쟀는지 함께 남긴다
  add column if not exists ndcg_k int
    check (ndcg_k is null or ndcg_k >= 1);

comment on column evaluation_results.reciprocal_rank is
  '기대 카드 최초 등장 순위의 역수. 후보에 없으면 0. HIT 기대 문항에서만 채운다';
comment on column evaluation_results.ndcg is
  '이진 관련도 nDCG@ndcg_k. HIT 기대 문항에서만 채운다';

commit;
