-- 기존 파일 인용은 그대로 두고 점주 답변 RAW 출처를 별도로 보존한다.
begin;
alter table r_answer_citations alter column source_id drop not null;
alter table r_answer_citations add column owner_answer_id bigint;
alter table r_answer_citations add constraint r_citation_one_origin
  check ((source_id is null) <> (owner_answer_id is null));
alter table r_answer_citations add constraint r_citation_owner_is_raw
  check (owner_answer_id is null or raw_span_id is not null);

-- 답변 ID의 존재뿐 아니라 같은 매장·원문 구간의 실제 출처인지 확인한다.
-- raw_spans의 기존 출처 FK/매장 trigger와 함께 파일 없는 레거시 답변도 보존한다.
alter table raw_spans add constraint raw_span_owner_origin_key
  unique (store_id, raw_span_id, owner_answer_id);
alter table r_answer_citations add constraint r_citation_owner_origin_fk
  foreign key (store_id, raw_span_id, owner_answer_id)
  references raw_spans(store_id, raw_span_id, owner_answer_id);
commit;
