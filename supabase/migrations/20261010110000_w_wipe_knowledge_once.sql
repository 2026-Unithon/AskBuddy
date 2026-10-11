-- Phase A — 배포 때 한 번 도는 지식·자료 삭제 (설계 A-D5, 사용자 결정 A-U5·A-U6).
-- 지우는 것: 지식 전부 + 업로드 자료 + 답변 인용 기록(R 표 포함). R 표 구조는 바꾸지 않는다.
-- 남기는 것: 매장·계정·카테고리·근무조·질문·점주 답변·채팅 문장·비용 원장·알림·로드맵 틀·체크리스트 제출.
--   owner_answers.card_id·roadmap_items.card_id/published_version_id·learning_progress.completed_version_id·
--   access_logs.card_id 는 FK 가 SET NULL 로 끊는다.
-- 공개 포인터 행(knowledge_publications)은 남기고 current_snapshot_id 만 비운다.
--   판 번호(publication_revision·knowledge_revision)가 되돌아가지 않게 하려는 것이다.
--   첫 직원 질문에서 ensure_initial_publication 이 빈 공개판을 새로 만든다.
-- 불변 트리거는 이 트랜잭션 안에서만 끄고 다시 켠다. DDL 도 트랜잭션에 묶여 있어서 실패하면 함께 되돌아간다.
-- migration 은 버전당 한 번 적용된다. 빈 DB 에서 돌아도 지울 것이 없어 무해하다.
-- 되돌리기는 배포 워크플로의 migration 직전 DB 백업뿐이다(FACT_ONLY_ROLLOUT.md).
begin;

-- 0. 평가 기록 보호: quality_evaluations 는 ingest_jobs 를 RESTRICT 로 가리킨다.
--    행이 있으면 평가 기록을 지우거나 고치지 않고 여기서 멈춘다(사람이 정한다).
do $$
begin
  if exists (select 1 from quality_evaluations) then
    raise exception '평가 기록 quality_evaluations 행이 있어 1회 삭제를 멈춘다 — FACT_ONLY_ROLLOUT.md 참조';
  end if;
end $$;

-- 삭제·갱신을 막는 불변 트리거만 끈다. INSERT 전용 store_check 트리거는 건드리지 않는다
alter table r_answer_citations disable trigger r_answer_citation_immutable;
alter table r_answer_receipts disable trigger r_answer_receipt_immutable;
alter table knowledge_snapshots disable trigger trg_snapshot_immutable;
alter table r_index_documents disable trigger r_index_documents_immutable;
alter table r_index_preparations disable trigger r_index_content_immutable;
alter table fact_revisions disable trigger trg_fact_revision_immutable;
alter table fact_revision_meta disable trigger trg_fact_revision_meta_immutable;
alter table knowledge_entity_events disable trigger trg_entity_event_immutable;
alter table card_version_fact_provenance disable trigger trg_card_version_fact_provenance_immutable;

-- 1. 답변 인용
delete from r_answer_citations;
delete from r_answer_receipts;
delete from message_citations;
-- 2. 제안·편집
delete from knowledge_change_proposals;
delete from upload_change_proposal_facts;
delete from upload_change_proposals;
delete from card_fact_edits;
-- 3. 판 고정
delete from card_version_fact_provenance;
delete from card_block_facts;
delete from card_version_blocks;
delete from raw_spans;
-- 4. 카드 부속
delete from card_evidence;
delete from card_embeddings;
delete from facts;
delete from card_facts;
delete from card_review_events;
delete from checklist_card_shifts;
delete from checklist_cards;
delete from reclassification_results;
-- 5. 사실 원장
delete from fact_conflicts;
delete from fact_owner_answer_links;
delete from source_fact_revision_links;
delete from fact_occurrences;
delete from fact_revision_requires;
delete from fact_revision_meta;
update knowledge_facts set head_revision_id = null where head_revision_id is not null;
delete from fact_revisions;
delete from knowledge_facts;
delete from knowledge_entity_candidates;
delete from knowledge_entity_events;
delete from knowledge_entity_aliases;
update knowledge_cards set entity_id = null where entity_id is not null;
delete from knowledge_entities;
-- 6. 자료 원장
delete from source_fact_occurrences;
delete from source_facts;
-- 7. 카드 (포인터를 비우면 로드맵 동기화 트리거가 그 카드 항목을 비활성으로 돌린다)
update knowledge_cards set draft_version_id = null, published_version_id = null
 where draft_version_id is not null or published_version_id is not null;
delete from card_versions;
delete from knowledge_cards;
-- 8. 공개판·색인(R). 공개 포인터 행은 남기고 가리키는 판만 비운다
update knowledge_publications set current_snapshot_id = null
 where current_snapshot_id is not null;
delete from r_index_publications;
delete from r_index_documents;
delete from r_index_preparations;
delete from snapshot_card_versions;
delete from knowledge_snapshots;
-- 지운 공개판을 가리키는 공개 멱등 기록(r-initial-empty 포함). 남기면 같은 키 재요청이
-- 지운 snapshot 을 ALREADY_APPLIED 로 돌려준다
delete from operations where operation = 'PUBLISH';
-- 9. 작업·자료
delete from owner_answer_sources;
delete from ingest_job_sources;
delete from ingest_jobs;
delete from source_frames;
delete from source_video;
delete from source_voice;
delete from source_kakao;
delete from source_scan;
delete from sources;
-- 10. 체크리스트 체크(지워진 판을 가리킨다). 제출 기록은 남긴다
delete from checklist_check_events;
delete from checklist_checks;
-- 리셋 (카드 갱신 트리거가 다시 채웠을 수 있으므로 맨 끝에 둔다)
update stores set guide_completed_at = null where guide_completed_at is not null;

alter table r_answer_citations enable trigger r_answer_citation_immutable;
alter table r_answer_receipts enable trigger r_answer_receipt_immutable;
alter table knowledge_snapshots enable trigger trg_snapshot_immutable;
alter table r_index_documents enable trigger r_index_documents_immutable;
alter table r_index_preparations enable trigger r_index_content_immutable;
alter table fact_revisions enable trigger trg_fact_revision_immutable;
alter table fact_revision_meta enable trigger trg_fact_revision_meta_immutable;
alter table knowledge_entity_events enable trigger trg_entity_event_immutable;
alter table card_version_fact_provenance enable trigger trg_card_version_fact_provenance_immutable;

commit;
