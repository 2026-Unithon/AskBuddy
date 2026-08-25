-- =====================================================================
-- AskBuddy — 초기 스키마 (PostgreSQL / Supabase)
-- 원천: 최종erd.xlsx (21 테이블)
-- 반영: 2026-08-25 결정사항 6건
--   D1 RLS 미도입      → 매장 격리는 API 코드 레이어에서만 수행.
--                        모든 쿼리에 store_id 를 직접 넣는다. DB 차원의 방어선 없음.
--   D2 LLM 호출 일원화 → 스키마 영향 없음 (FastAPI 단독 호출)
--   D3 신뢰도 임계 0.6 → knowledge_cards.confidence CHECK + 기본 검수 대상 판정
--   D4 임베딩 1536     → OpenAI text-embedding-3-small 고정
--   D5 is_sensitive    → 컬럼 유지, 현 단계 미사용 (예약 필드)
--   D6 폴링            → sources.status 상태머신 CHECK 제약
-- 추가: stores.store_slug (기존 FastAPI의 문자열 store_id 호환용)
--       pending_questions.miss_reason (검색 게이트 miss 사유 보존)
-- =====================================================================

create extension if not exists vector;
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------
-- 1. 사용자 · 매장
-- ---------------------------------------------------------------------

create table users (
  user_id         bigint generated always as identity primary key,
  name            varchar(50)  not null,
  phone           varchar(20),
  email           varchar(255) unique,
  password_hash   text,
  role            varchar(20)  not null
                  check (role in ('OWNER','STAFF')),
  created_at      timestamptz  not null default now()
);
-- identity.sql 인증 컬럼(email·password_hash)을 users 에 병합했다.

create table stores (
  store_id            bigint generated always as identity primary key,
  owner_id            bigint not null references users(user_id) on delete restrict,
  store_slug          varchar(50) unique,               -- 기존 API 호환 ('demo-cafe')
  store_name          varchar(100) not null,
  business_type       varchar(20)  not null
                      check (business_type in ('CAFE','RESTAURANT','BAKERY','BAR','CVS','SALON')),
  deploy_threshold    int          not null default 80,
  knowledge_coverage  numeric(5,2) not null default 0,
  dek_encrypted       bytea,                            -- D5: 예약 필드, 현 단계 미사용
  created_at          timestamptz  not null default now()
);
comment on column stores.store_slug is 'FastAPI /reg/* 의 문자열 store_id 를 BIGINT 로 해석하기 위한 별칭';
comment on column stores.dek_encrypted is 'D5 예약. 민감 지식 봉투암호화용. 현 릴리스에서는 쓰지 않음';

create table store_members (
  member_id       bigint generated always as identity primary key,
  store_id        bigint not null references stores(store_id) on delete cascade,
  user_id         bigint not null references users(user_id)  on delete cascade,
  member_role     varchar(20) not null check (member_role in ('OWNER','STAFF')),
  joined_at       timestamptz  not null default now(),
  day_count       int          not null default 0,
  progress_rate   numeric(5,2) not null default 0,
  is_deployable   boolean      not null default false,
  last_active_at  timestamptz,
  unique (store_id, user_id)
);

create table invite_codes (
  invite_id   bigint generated always as identity primary key,
  store_id    bigint not null references stores(store_id) on delete cascade,
  code        varchar(30) not null unique,
  is_used     boolean     not null default false,
  used_by     bigint references users(user_id),
  expires_at  timestamptz not null,
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 2. 업무 분류
-- ---------------------------------------------------------------------

create table task_categories (
  category_id    bigint generated always as identity primary key,
  store_id       bigint not null references stores(store_id) on delete cascade,
  category_name  varchar(50) not null,
  is_enabled     boolean not null default true,
  sort_order     int     not null default 0,
  unique (store_id, category_name)
);

-- ---------------------------------------------------------------------
-- 3. 원본 자료
-- ---------------------------------------------------------------------

create table sources (
  source_id      bigint generated always as identity primary key,
  store_id       bigint not null references stores(store_id) on delete cascade,
  uploaded_by    bigint not null references users(user_id),
  source_type    varchar(20) not null
                 check (source_type in ('VOICE','VIDEO','KAKAO','SCAN')),
  title          varchar(200),
  file_url       varchar(500),
  file_size      bigint,
  content_hash   varchar(64),                           -- 멱등 처리용
  status         varchar(20) not null default 'UPLOADED'
                 check (status in ('UPLOADED','PROCESSING','DONE','FAILED')),  -- D6
  error_message  varchar(500),
  processed_at   timestamptz,
  created_at     timestamptz not null default now()
);
comment on column sources.status is 'D6: 프론트가 2초 간격 폴링. FAILED 는 error_message 필수';
create unique index on sources (store_id, content_hash) where content_hash is not null;

create table source_voice (
  voice_id        bigint generated always as identity primary key,
  source_id       bigint not null references sources(source_id) on delete cascade,
  audio_format    varchar(10) not null check (audio_format in ('mp3','m4a','wav')),
  duration_sec    int not null,
  sample_rate     int,
  record_method   varchar(20) not null check (record_method in ('UPLOAD','DIRECT_RECORD')),
  transcript      text,
  stt_model       varchar(50),
  stt_confidence  numeric(5,2),
  is_confirmed    boolean not null default false
);

create table source_video (
  video_id        bigint generated always as identity primary key,
  source_id       bigint not null references sources(source_id) on delete cascade,
  video_format    varchar(10) not null check (video_format in ('mp4','mov')),
  duration_sec    int not null,
  resolution      varchar(20),
  fps             int,
  frame_count     int not null default 0,
  transcript      text,
  stt_confidence  numeric(5,2),
  has_prior_doc   boolean not null default false,
  prior_doc_url   varchar(500)
);

create table source_frames (
  frame_id       bigint generated always as identity primary key,
  video_id       bigint not null references source_video(video_id) on delete cascade,
  frame_index    int not null,
  timestamp_sec  int not null,
  image_url      varchar(500) not null,
  caption        text,
  landmark_desc  varchar(300),
  is_key_frame   boolean not null default false,
  unique (video_id, frame_index)
);
comment on column source_frames.landmark_desc is '주변 사물 기준 표현만 허용. 화면좌표·거리 표현 금지';

create table source_kakao (
  kakao_id         bigint generated always as identity primary key,
  source_id        bigint not null references sources(source_id) on delete cascade,
  import_type      varchar(20) not null check (import_type in ('TXT_EXPORT','SCREENSHOT')),
  room_name        varchar(100),
  message_count    int not null default 0,
  participant_cnt  int,
  period_start     timestamptz,
  period_end       timestamptz,
  parsed_text      text
);

create table source_scan (
  scan_id         bigint generated always as identity primary key,
  source_id       bigint not null references sources(source_id) on delete cascade,
  doc_type        varchar(20) not null check (doc_type in ('PDF','JPG','PNG')),
  doc_category    varchar(30) check (doc_category in ('MENU_BOARD','MANUAL','RECIPE','ETC')),
  page_count      int not null default 1,
  ocr_text        text,
  ocr_engine      varchar(50),
  ocr_confidence  numeric(5,2)
);

create table store_glossary (
  glossary_id  bigint generated always as identity primary key,
  store_id     bigint not null references stores(store_id) on delete cascade,
  term         varchar(100) not null,
  variants     varchar(300),
  description  varchar(300),
  unique (store_id, term)
);

-- ---------------------------------------------------------------------
-- 4. 지식
-- ---------------------------------------------------------------------

create table knowledge_cards (
  card_id       bigint generated always as identity primary key,
  store_id      bigint not null references stores(store_id) on delete cascade,
  category_id   bigint references task_categories(category_id) on delete set null,
  source_id     bigint references sources(source_id) on delete set null,
  title         varchar(200) not null,
  content       text not null,
  confidence    numeric(5,2) not null default 0 check (confidence between 0 and 100),
  is_verified   boolean not null default false,
  is_sensitive  boolean not null default false,          -- D5: 예약 필드
  created_at    timestamptz not null default now(),
  updated_at    timestamptz
);
comment on column knowledge_cards.is_verified is
  '검색 게이트의 approved 와 동일 의미. true 인 카드만 /reg/retrieve 대상';
comment on column knowledge_cards.confidence is
  'D3: 60 미만이면 점주 검수 화면 상단 우선 노출. 0~100 백분율';
comment on column knowledge_cards.is_sensitive is
  'D5: 컬럼만 유지. 현 릴리스는 마스킹 미적용. 향후 레시피 보호용';

create table facts (
  fact_id      bigint generated always as identity primary key,
  card_id      bigint not null references knowledge_cards(card_id) on delete cascade,
  object_name  varchar(100) not null,
  attribute    varchar(100) not null,
  value        varchar(500) not null,
  confidence   numeric(5,2) not null default 0,
  is_verified  boolean not null default false
);

create table card_embeddings (
  embedding_id     bigint generated always as identity primary key,
  card_id          bigint not null references knowledge_cards(card_id) on delete cascade,
  store_id         bigint not null references stores(store_id) on delete cascade,
  chunk_index      int not null default 0,
  chunk_text       text not null,
  chunk_tokens     int,
  chunk_start_pos  int,
  chunk_end_pos    int,
  embedding        vector(1536) not null,                -- D4
  dimension        int not null default 1536,
  model_name       varchar(50) not null default 'text-embedding-3-small',
  model_version    varchar(20),
  distance_metric  varchar(20) not null default 'cosine',
  lexical_tsv      tsvector,                             -- ERD의 TEXT → tsvector
  content_hash     varchar(64) not null,
  is_stale         boolean not null default false,
  indexed_at       timestamptz not null default now(),
  updated_at       timestamptz,
  unique (card_id, chunk_index)
);
comment on column card_embeddings.model_name is
  'D4: OpenAI text-embedding-3-small(1536) 고정. 모델 교체 시 임계값·골든셋 전면 재측정 필요';

-- ---------------------------------------------------------------------
-- 5. 로드맵 · 진행도
-- ---------------------------------------------------------------------

create table roadmap_stages (
  stage_id     bigint generated always as identity primary key,
  store_id     bigint not null references stores(store_id) on delete cascade,
  stage_name   varchar(100) not null,
  stage_order  int not null,
  unique (store_id, stage_order)
);

create table roadmap_items (
  item_id     bigint generated always as identity primary key,
  stage_id    bigint not null references roadmap_stages(stage_id) on delete cascade,
  card_id     bigint references knowledge_cards(card_id) on delete set null,
  item_name   varchar(200) not null,
  item_order  int not null default 0
);

create table learning_progress (
  progress_id   bigint generated always as identity primary key,
  member_id     bigint not null references store_members(member_id) on delete cascade,
  item_id       bigint not null references roadmap_items(item_id) on delete cascade,
  status        varchar(20) not null default 'LOCKED'
                check (status in ('LOCKED','IN_PROGRESS','DONE')),
  completed_at  timestamptz,
  unique (member_id, item_id)
);

-- ---------------------------------------------------------------------
-- 6. 채팅 · 미답변 순환
-- ---------------------------------------------------------------------

create table chat_sessions (
  session_id  bigint generated always as identity primary key,
  store_id    bigint not null references stores(store_id) on delete cascade,
  member_id   bigint not null references store_members(member_id) on delete cascade,
  started_at  timestamptz not null default now()
);

create table chat_messages (
  message_id   bigint generated always as identity primary key,
  session_id   bigint not null references chat_sessions(session_id) on delete cascade,
  sender_type  varchar(10) not null check (sender_type in ('USER','BUDDY')),
  content      text not null,
  answer_type  varchar(20) check (answer_type in ('ANSWERED','NO_ANSWER')),
  confidence   numeric(5,2),
  created_at   timestamptz not null default now()
);

create table message_citations (
  citation_id  bigint generated always as identity primary key,
  message_id   bigint not null references chat_messages(message_id) on delete cascade,
  card_id      bigint not null references knowledge_cards(card_id) on delete cascade,
  relevance    numeric(5,2) not null default 0
);
comment on table message_citations is
  'BUDDY 메시지가 ANSWERED 인데 이 행이 0건이면 계약 위반. 답변을 폐기해야 함';

create table pending_questions (
  question_id    bigint generated always as identity primary key,
  store_id       bigint not null references stores(store_id) on delete cascade,
  member_id      bigint not null references store_members(member_id) on delete cascade,
  message_id     bigint references chat_messages(message_id) on delete set null,
  category_id    bigint references task_categories(category_id) on delete set null,
  question_text  varchar(500) not null,
  miss_reason    varchar(30)
                 check (miss_reason in ('no_match','intent_mismatch','no_anchor')),
  status         varchar(20) not null default 'WAITING'
                 check (status in ('WAITING','ANSWERED')),
  created_at     timestamptz not null default now()
);
comment on column pending_questions.miss_reason is
  '검색 게이트가 반환한 miss 사유 보존. 빈 지식 알림 분류에 사용';

create table owner_answers (
  answer_id    bigint generated always as identity primary key,
  question_id  bigint not null references pending_questions(question_id) on delete cascade,
  answered_by  bigint not null references users(user_id),
  answer_text  text not null,
  card_id      bigint references knowledge_cards(card_id) on delete set null,
  answered_at  timestamptz not null default now()
);

create table access_logs (
  log_id       bigint generated always as identity primary key,
  store_id     bigint not null references stores(store_id) on delete cascade,
  user_id      bigint not null references users(user_id) on delete cascade,
  card_id      bigint references knowledge_cards(card_id) on delete set null,
  action_type  varchar(30) not null check (action_type in ('VIEW','QUERY','EXPORT')),
  accessed_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 7. 인덱스
-- ---------------------------------------------------------------------

create index on store_members     (store_id, user_id);
create index on invite_codes      (store_id) where is_used = false;
create index on task_categories   (store_id) where is_enabled = true;
create index on sources           (store_id, status);
create index on knowledge_cards   (store_id, category_id);
create index on knowledge_cards   (store_id) where is_verified = true;
create index on facts             (card_id);
create index on roadmap_items     (stage_id, item_order);
create index on learning_progress (member_id, status);
create index on chat_messages     (session_id, created_at);
create index on pending_questions (store_id, status);
create index on access_logs       (store_id, accessed_at desc);

-- 벡터 검색 (D4: cosine 고정)
create index on card_embeddings using hnsw (embedding vector_cosine_ops);
create index on card_embeddings (store_id) where is_stale = false;
create index on card_embeddings using gin (lexical_tsv);

-- ---------------------------------------------------------------------
-- 8. 검색 RPC — FastAPI 만 호출한다. 브라우저에 DB 자격증명을 두지 않는다.
--    RLS 가 없으므로 p_store_id 를 넣지 않으면 전 매장이 검색된다. 필수 인자다.
-- ---------------------------------------------------------------------

create or replace function match_cards(
  p_store_id  bigint,
  p_embedding vector(1536),
  p_top_k     int default 5
)
returns table (card_id bigint, content text, title varchar, score float)
language sql stable
as $$
  select c.card_id,
         c.content,
         c.title,
         1 - (e.embedding <=> p_embedding) as score
  from card_embeddings e
  join knowledge_cards c on c.card_id = e.card_id
  where e.store_id = p_store_id
    and e.is_stale = false
    and c.is_verified = true          -- approved 만 검색 대상
  order by e.embedding <=> p_embedding
  limit p_top_k;
$$;
