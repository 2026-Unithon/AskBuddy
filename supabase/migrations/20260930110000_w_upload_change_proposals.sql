-- W2-4 — 업로드 사실의 검수 제안(IDENTICAL|NEW|SUPPLEMENT|CONFLICT).
--
-- 새 자료의 사실이 기존 승인 카드와 어떤 관계인지 자료 × 대상 단위로 남긴다.
--
-- 규칙:
--   1. 가산 migration 이다. 기존 표·행·제약을 바꾸지 않는다.
--   2. 점주 답변 제안 표(knowledge_change_proposals)와 별개다. 그 표는 answer_id 가
--      NOT NULL UNIQUE 이고 R 경로가 answer_id 를 가정한다(설계 F13·R5). 관계 어휘와 판정
--      순서만 같게 쓴다.
--   3. 제안은 기존 카드 행을 바꾸지 않는다(컨트롤러 결정 G). 영향 카드는 계산 시점의
--      카드 id·공개 판 id·검수 상태를 matched_cards 에 고정해 둘 뿐이다. 재조립은 W3.
--   4. 충돌 제안에도 기본 선택·승자 칸이 없다(사용자 결정).
--   5. 매장 교차는 복합 FK 로 막는다.

begin;

create table if not exists upload_change_proposals (
  proposal_id bigint generated always as identity primary key,
  store_id bigint not null references stores(store_id) on delete cascade,
  source_id bigint not null,
  job_id bigint,
  entity_id bigint not null,
  relation_type varchar(20) not null
    check (relation_type in ('IDENTICAL','NEW','SUPPLEMENT','CONFLICT')),
  matched_cards jsonb not null default '[]'::jsonb
    check (jsonb_typeof(matched_cards) = 'array'),
  status varchar(20) not null default 'PENDING_REVIEW'
    check (status in ('PENDING_REVIEW','ACCEPTED','DISMISSED','SUPERSEDED')),
  decided_by bigint references users(user_id) on delete set null,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (store_id, proposal_id),
  unique (store_id, source_id, entity_id),
  foreign key (store_id, source_id) references sources(store_id, source_id),
  foreign key (store_id, entity_id) references knowledge_entities(store_id, entity_id)
);

create table if not exists upload_change_proposal_facts (
  store_id bigint not null,
  proposal_id bigint not null,
  fact_revision_id bigint not null,
  fact_id bigint not null,
  relation_type varchar(20) not null
    check (relation_type in ('IDENTICAL','NEW','SUPPLEMENT','CONFLICT')),
  conflict_fact_ids bigint[] not null default '{}',
  affected_card_ids bigint[] not null default '{}',
  primary key (store_id, proposal_id, fact_revision_id),
  foreign key (store_id, proposal_id)
    references upload_change_proposals(store_id, proposal_id) on delete cascade,
  foreign key (store_id, fact_revision_id) references fact_revisions(store_id, fact_revision_id),
  foreign key (store_id, fact_id) references knowledge_facts(store_id, fact_id)
);

create index if not exists idx_upload_proposals_pending
  on upload_change_proposals (store_id, status, created_at desc);

comment on table upload_change_proposals is
  '업로드 검수 제안 — 자료 × 대상 한 행. 기존 카드 행은 바꾸지 않는다 (W2-4, 결정 G)';
comment on column upload_change_proposals.relation_type is
  '승인 카드 없음 → NEW. 있으면 CONFLICT > SUPPLEMENT > IDENTICAL(항목이 전부 IDENTICAL 일 때만)';
comment on column upload_change_proposals.matched_cards is
  '계산 시점의 영향 승인 카드 [{card_id, published_version_id, review_status}]. 선택·승자 없음';
comment on column upload_change_proposals.status is
  '네 관계 모두 PENDING_REVIEW 로 시작한다. 자동 확정·자동 발행 없음';
comment on table upload_change_proposal_facts is
  '제안 항목 — 이 자료가 이은 사실 판마다 관계·충돌 상대 사실·영향 카드 (W2-4)';

commit;
