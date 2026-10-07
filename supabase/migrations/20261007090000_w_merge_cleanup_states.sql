-- W3-0 §3-3 — 대상 병합 뒤 정리 상태·이력 어휘를 더한다.
--
-- 규칙:
--   1. 가산 migration 이다. 기존 CHECK 의 허용 값을 넓히기만 한다. 기존 행·값·다른 제약은 그대로다.
--      제약 이름은 20260930090000_w_knowledge_entities.sql 의 열 CHECK 가 받은 기본 이름이다.
--   2. knowledge_entity_candidates.status 'MERGED' — 병합된 대상이 낀 PENDING 후보를 merge_entities 가
--      닫을 때 쓴다(점주의 '기각'·'다른 대상' 결정과 구별한다). decided_at·decided_by 가 함께 찬다.
--   3. knowledge_entity_events.action 'CANDIDATE_MOVED'(후보를 남은 대상 쪽으로 옮기거나 닫음),
--      'PROPOSAL_MOVED'(병합된 대상의 PENDING 업로드 제안을 살아 있는 대상으로 옮기거나 SUPERSEDED).
--      이력은 그대로 append-only 다.

begin;

alter table knowledge_entity_candidates
  drop constraint if exists knowledge_entity_candidates_status_check;
alter table knowledge_entity_candidates
  add constraint knowledge_entity_candidates_status_check
  check (status in ('PENDING', 'CONFIRMED_SAME', 'CONFIRMED_DIFFERENT', 'DISMISSED', 'MERGED'));

alter table knowledge_entity_events
  drop constraint if exists knowledge_entity_events_action_check;
alter table knowledge_entity_events
  add constraint knowledge_entity_events_action_check
  check (action in ('CREATE', 'ALIAS_ADD', 'ALIAS_RETIRE', 'MERGE', 'SPLIT', 'RELINK_FACT',
                    'CANDIDATE_DECIDED', 'CANDIDATE_MOVED', 'PROPOSAL_MOVED'));

comment on column knowledge_entity_candidates.status is
  'PENDING · CONFIRMED_SAME · CONFIRMED_DIFFERENT · DISMISSED · MERGED(병합된 대상이 끼어 merge_entities 가 닫음, W3-0)';

commit;
