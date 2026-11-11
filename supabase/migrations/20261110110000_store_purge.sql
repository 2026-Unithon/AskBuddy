-- 계획 9C(2026-11-10): 사장님 탈퇴 30일 뒤 매장 파기(D22)
-- 불변 트리거의 함수 본문은 고치지 않는다. "파기 중인 매장의 행이면 발동하지 않는다"는 WHEN 만 붙인다
alter table stores alter column owner_id drop not null;
alter table stores add column if not exists closing_at timestamptz;
alter table stores add column if not exists purge_due_at timestamptz;
alter table stores add column if not exists deleted_at timestamptz;
alter table users add column if not exists deleted_at timestamptz;
alter table stores add constraint stores_purge_due_needs_closing
  check (purge_due_at is null or closing_at is not null);
create index if not exists stores_purge_due on stores (purge_due_at) where purge_due_at is not null and deleted_at is null;

-- 파기 중인가. 설정만으로는 참이 되지 않는다: 그 매장의 기한이 지나 있어야 한다
create or replace function askbuddy_purging(p_store_id bigint) returns boolean
language plpgsql stable as $$
declare
  target text := current_setting('askbuddy.purge_store_id', true);
begin
  if target is null or target = '' or p_store_id is null or target <> p_store_id::text then
    return false;
  end if;
  return exists (
    select 1 from stores
    where store_id = p_store_id and deleted_at is null
      and purge_due_at is not null and purge_due_at <= now());
end $$;

-- owner_answers 에는 store_id 가 없어 질문을 거쳐 매장을 찾는다
create or replace function askbuddy_purging_question(p_question_id bigint) returns boolean
language sql stable as $$
  select coalesce((select askbuddy_purging(q.store_id) from pending_questions q where q.question_id = p_question_id), false)
$$;

-- 장부(ai_usage_attempts.trg_usage_attempt_freeze)는 건드리지 않는다

drop trigger trg_evaluation_results_append_only on evaluation_results;
create trigger trg_evaluation_results_append_only before update or delete on evaluation_results
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_evaluation_results_append_only();

drop trigger trg_evaluation_runs_freeze on evaluation_runs;
create trigger trg_evaluation_runs_freeze before update or delete on evaluation_runs
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_evaluation_runs_freeze();

drop trigger trg_extraction_results_append_only on extraction_results;
create trigger trg_extraction_results_append_only before update or delete on extraction_results
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_extraction_results_append_only();

drop trigger trg_extraction_runs_freeze on extraction_runs;
create trigger trg_extraction_runs_freeze before update or delete on extraction_runs
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_extraction_runs_freeze();

drop trigger trg_fact_revision_meta_immutable on fact_revision_meta;
create trigger trg_fact_revision_meta_immutable before update or delete on fact_revision_meta
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_fact_revision_meta_immutable();

drop trigger trg_fact_revision_immutable on fact_revisions;
create trigger trg_fact_revision_immutable before update or delete on fact_revisions
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_fact_revision_immutable();

drop trigger trg_entity_event_immutable on knowledge_entity_events;
create trigger trg_entity_event_immutable before update or delete on knowledge_entity_events
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_entity_event_immutable();

drop trigger trg_snapshot_immutable on knowledge_snapshots;
create trigger trg_snapshot_immutable before update or delete on knowledge_snapshots
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_snapshot_immutable();

drop trigger r_answer_citation_immutable on r_answer_citations;
create trigger r_answer_citation_immutable before update or delete on r_answer_citations
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_answer_receipt_immutable();

drop trigger r_answer_receipt_immutable on r_answer_receipts;
create trigger r_answer_receipt_immutable before update or delete on r_answer_receipts
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_answer_receipt_immutable();

drop trigger r_owner_delivery_immutable on r_owner_answer_deliveries;
create trigger r_owner_delivery_immutable before update or delete on r_owner_answer_deliveries
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_answer_receipt_immutable();

drop trigger r_owner_revision_immutable on r_owner_answer_revisions;
create trigger r_owner_revision_immutable before update or delete on r_owner_answer_revisions
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_answer_receipt_immutable();

drop trigger r_search_lexicon_immutable on r_search_lexicons;
create trigger r_search_lexicon_immutable before update or delete on r_search_lexicons
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_answer_receipt_immutable();

drop trigger trg_task_categories_protect_system on task_categories;
create trigger trg_task_categories_protect_system before update or delete on task_categories
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_protect_system_category();

-- owner_answers: store_id 가 없다
drop trigger r_owner_original_immutable on owner_answers;
create trigger r_owner_original_immutable before update or delete on owner_answers
  for each row when (not askbuddy_purging_question(old.question_id)) execute function askbuddy_owner_original_immutable();

-- r_index_documents: insert 도 같은 함수가 본다. insert 에는 old 가 없어 트리거를 둘로 나눈다
drop trigger r_index_documents_immutable on r_index_documents;
create trigger r_index_documents_immutable_insert before insert on r_index_documents
  for each row execute function askbuddy_index_documents_immutable();
create trigger r_index_documents_immutable before update or delete on r_index_documents
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_index_documents_immutable();
