set local check_function_bodies = off;
alter default privileges for role "postgres" in schema "public" revoke all on sequences from "anon";

alter default privileges for role "postgres" in schema "public" revoke all on sequences from "authenticated";

alter default privileges for role "postgres" in schema "public" revoke all on sequences from "service_role";

alter default privileges for role "postgres" in schema "public" revoke all on tables from "anon";

alter default privileges for role "postgres" in schema "public" revoke all on tables from "authenticated";

alter default privileges for role "postgres" in schema "public" revoke all on tables from "service_role";

create extension "pg_trgm" schema "public";

create extension "vector" schema "public";

create table "public"."access_logs" (
  "log_id"      bigint                   generated always as identity not null,
  "store_id"    bigint                   not null,
  "user_id"     bigint                   not null,
  "card_id"     bigint,
  "action_type" character varying(30)    not null,
  "accessed_at" timestamp with time zone not null default now(),
  constraint "access_logs_action_type_check"
    check (((action_type)::text = ANY ((ARRAY['VIEW'::character varying, 'QUERY'::character varying, 'EXPORT'::character varying])::text[]))),
  constraint "access_logs_pkey" primary key (log_id)
);

create table "public"."card_embeddings" (
  "embedding_id"    bigint                   generated always as identity not null,
  "card_id"         bigint                   not null,
  "store_id"        bigint                   not null,
  "chunk_index"     integer                  not null default 0,
  "chunk_text"      text                     not null,
  "chunk_tokens"    integer,
  "chunk_start_pos" integer,
  "chunk_end_pos"   integer,
  "embedding"       public.vector(1536)      not null,
  "dimension"       integer                  not null default 1536,
  "model_name"      character varying(50)    not null default 'text-embedding-3-small'::character varying,
  "model_version"   character varying(20),
  "distance_metric" character varying(20)    not null default 'cosine'::character varying,
  "lexical_tsv"     tsvector,
  "content_hash"    character varying(64)    not null,
  "is_stale"        boolean                  not null default false,
  "indexed_at"      timestamp with time zone not null default now(),
  "updated_at"      timestamp with time zone,
  constraint "card_embeddings_card_id_chunk_index_key" unique (card_id, chunk_index),
  constraint "card_embeddings_pkey" primary key (embedding_id)
);

create table "public"."chat_messages" (
  "message_id"  bigint                   generated always as identity not null,
  "session_id"  bigint                   not null,
  "sender_type" character varying(10)    not null,
  "content"     text                     not null,
  "answer_type" character varying(20),
  "confidence"  numeric(5,2),
  "created_at"  timestamp with time zone not null default now(),
  constraint "chat_messages_answer_type_check" check (((answer_type)::text = ANY ((ARRAY['ANSWERED'::character varying, 'NO_ANSWER'::character varying])::text[]))),
  constraint "chat_messages_pkey" primary key (message_id),
  constraint "chat_messages_sender_type_check" check (((sender_type)::text = ANY ((ARRAY['USER'::character varying, 'BUDDY'::character varying])::text[])))
);

create table "public"."chat_sessions" (
  "session_id" bigint                   generated always as identity not null,
  "store_id"   bigint                   not null,
  "member_id"  bigint                   not null,
  "started_at" timestamp with time zone not null default now(),
  constraint "chat_sessions_pkey" primary key (session_id)
);

create table "public"."facts" (
  "fact_id"     bigint                 generated always as identity not null,
  "card_id"     bigint                 not null,
  "object_name" character varying(100) not null,
  "attribute"   character varying(100) not null,
  "value"       character varying(500) not null,
  "confidence"  numeric(5,2)           not null default 0,
  "is_verified" boolean                not null default false,
  constraint "facts_pkey" primary key (fact_id)
);

create table "public"."invite_codes" (
  "invite_id"  bigint                   generated always as identity not null,
  "store_id"   bigint                   not null,
  "code"       character varying(30)    not null,
  "is_used"    boolean                  not null default false,
  "used_by"    bigint,
  "expires_at" timestamp with time zone not null,
  "created_at" timestamp with time zone not null default now(),
  constraint "invite_codes_code_key" unique (code),
  constraint "invite_codes_pkey" primary key (invite_id)
);

create table "public"."knowledge_cards" (
  "card_id"      bigint                   generated always as identity not null,
  "store_id"     bigint                   not null,
  "category_id"  bigint,
  "source_id"    bigint,
  "title"        character varying(200)   not null,
  "content"      text                     not null,
  "confidence"   numeric(5,2)             not null default 0,
  "is_verified"  boolean                  not null default false,
  "is_sensitive" boolean                  not null default false,
  "created_at"   timestamp with time zone not null default now(),
  "updated_at"   timestamp with time zone,
  constraint "knowledge_cards_confidence_check" check (((confidence >= (0)::numeric) AND (confidence <= (100)::numeric))),
  constraint "knowledge_cards_pkey" primary key (card_id)
);

create table "public"."learning_progress" (
  "progress_id"  bigint                   generated always as identity not null,
  "member_id"    bigint                   not null,
  "item_id"      bigint                   not null,
  "status"       character varying(20)    not null default 'LOCKED'::character varying,
  "completed_at" timestamp with time zone,
  constraint "learning_progress_member_id_item_id_key" unique (member_id, item_id),
  constraint "learning_progress_pkey" primary key (progress_id),
  constraint "learning_progress_status_check"
    check (((status)::text = ANY ((ARRAY['LOCKED'::character varying, 'IN_PROGRESS'::character varying, 'DONE'::character varying])::text[])))
);

create table "public"."message_citations" (
  "citation_id" bigint       generated always as identity not null,
  "message_id"  bigint       not null,
  "card_id"     bigint       not null,
  "relevance"   numeric(5,2) not null default 0,
  constraint "message_citations_pkey" primary key (citation_id)
);

create table "public"."owner_answers" (
  "answer_id"   bigint                   generated always as identity not null,
  "question_id" bigint                   not null,
  "answered_by" bigint                   not null,
  "answer_text" text                     not null,
  "card_id"     bigint,
  "answered_at" timestamp with time zone not null default now(),
  constraint "owner_answers_pkey" primary key (answer_id)
);

create table "public"."pending_questions" (
  "question_id"   bigint                   generated always as identity not null,
  "store_id"      bigint                   not null,
  "member_id"     bigint                   not null,
  "message_id"    bigint,
  "category_id"   bigint,
  "question_text" character varying(500)   not null,
  "miss_reason"   character varying(30),
  "status"        character varying(20)    not null default 'WAITING'::character varying,
  "created_at"    timestamp with time zone not null default now(),
  constraint "pending_questions_miss_reason_check"
    check (((miss_reason)::text = ANY ((ARRAY['no_match'::character varying, 'intent_mismatch'::character varying, 'no_anchor'::character varying])::text[]))),
  constraint "pending_questions_pkey" primary key (question_id),
  constraint "pending_questions_status_check" check (((status)::text = ANY ((ARRAY['WAITING'::character varying, 'ANSWERED'::character varying])::text[])))
);

create table "public"."roadmap_items" (
  "item_id"    bigint                 generated always as identity not null,
  "stage_id"   bigint                 not null,
  "card_id"    bigint,
  "item_name"  character varying(200) not null,
  "item_order" integer                not null default 0,
  constraint "roadmap_items_pkey" primary key (item_id)
);

create table "public"."roadmap_stages" (
  "stage_id"    bigint                 generated always as identity not null,
  "store_id"    bigint                 not null,
  "stage_name"  character varying(100) not null,
  "stage_order" integer                not null,
  constraint "roadmap_stages_pkey" primary key (stage_id),
  constraint "roadmap_stages_store_id_stage_order_key" unique (store_id, stage_order)
);

create table "public"."source_frames" (
  "frame_id"      bigint                 generated always as identity not null,
  "video_id"      bigint                 not null,
  "frame_index"   integer                not null,
  "timestamp_sec" integer                not null,
  "image_url"     character varying(500) not null,
  "caption"       text,
  "landmark_desc" character varying(300),
  "is_key_frame"  boolean                not null default false,
  constraint "source_frames_pkey" primary key (frame_id),
  constraint "source_frames_video_id_frame_index_key" unique (video_id, frame_index)
);

create table "public"."source_kakao" (
  "kakao_id"        bigint                   generated always as identity not null,
  "source_id"       bigint                   not null,
  "import_type"     character varying(20)    not null,
  "room_name"       character varying(100),
  "message_count"   integer                  not null default 0,
  "participant_cnt" integer,
  "period_start"    timestamp with time zone,
  "period_end"      timestamp with time zone,
  "parsed_text"     text,
  constraint "source_kakao_import_type_check" check (((import_type)::text = ANY ((ARRAY['TXT_EXPORT'::character varying, 'SCREENSHOT'::character varying])::text[]))),
  constraint "source_kakao_pkey" primary key (kakao_id)
);

create table "public"."source_scan" (
  "scan_id"        bigint                generated always as identity not null,
  "source_id"      bigint                not null,
  "doc_type"       character varying(20) not null,
  "doc_category"   character varying(30),
  "page_count"     integer               not null default 1,
  "ocr_text"       text,
  "ocr_engine"     character varying(50),
  "ocr_confidence" numeric(5,2),
  constraint "source_scan_doc_category_check"
    check (((doc_category)::text = ANY ((ARRAY['MENU_BOARD'::character varying, 'MANUAL'::character varying, 'RECIPE'::character varying, 'ETC'::character varying])::text[]))),
  constraint "source_scan_doc_type_check" check (((doc_type)::text = ANY ((ARRAY['PDF'::character varying, 'JPG'::character varying, 'PNG'::character varying])::text[]))),
  constraint "source_scan_pkey" primary key (scan_id)
);

create table "public"."source_video" (
  "video_id"       bigint                 generated always as identity not null,
  "source_id"      bigint                 not null,
  "video_format"   character varying(10)  not null,
  "duration_sec"   integer                not null,
  "resolution"     character varying(20),
  "fps"            integer,
  "frame_count"    integer                not null default 0,
  "transcript"     text,
  "stt_confidence" numeric(5,2),
  "has_prior_doc"  boolean                not null default false,
  "prior_doc_url"  character varying(500),
  constraint "source_video_pkey" primary key (video_id),
  constraint "source_video_video_format_check" check (((video_format)::text = ANY ((ARRAY['mp4'::character varying, 'mov'::character varying])::text[])))
);

create table "public"."source_voice" (
  "voice_id"       bigint                generated always as identity not null,
  "source_id"      bigint                not null,
  "audio_format"   character varying(10) not null,
  "duration_sec"   integer               not null,
  "sample_rate"    integer,
  "record_method"  character varying(20) not null,
  "transcript"     text,
  "stt_model"      character varying(50),
  "stt_confidence" numeric(5,2),
  "is_confirmed"   boolean               not null default false,
  constraint "source_voice_audio_format_check" check (((audio_format)::text = ANY ((ARRAY['mp3'::character varying, 'm4a'::character varying, 'wav'::character varying])::text[]))),
  constraint "source_voice_pkey" primary key (voice_id),
  constraint "source_voice_record_method_check" check (((record_method)::text = ANY ((ARRAY['UPLOAD'::character varying, 'DIRECT_RECORD'::character varying])::text[])))
);

create table "public"."sources" (
  "source_id"     bigint                   generated always as identity not null,
  "store_id"      bigint                   not null,
  "uploaded_by"   bigint                   not null,
  "source_type"   character varying(20)    not null,
  "title"         character varying(200),
  "file_url"      character varying(500),
  "file_size"     bigint,
  "content_hash"  character varying(64),
  "status"        character varying(20)    not null default 'UPLOADED'::character varying,
  "error_message" character varying(500),
  "processed_at"  timestamp with time zone,
  "created_at"    timestamp with time zone not null default now(),
  constraint "sources_pkey" primary key (source_id),
  constraint "sources_source_type_check"
    check (((source_type)::text = ANY ((ARRAY['VOICE'::character varying, 'VIDEO'::character varying, 'KAKAO'::character varying, 'SCAN'::character varying])::text[]))),
  constraint "sources_status_check"
    check (((status)::text = ANY ((ARRAY['UPLOADED'::character varying, 'PROCESSING'::character varying, 'DONE'::character varying, 'FAILED'::character varying])::text[])))
);

create table "public"."store_glossary" (
  "glossary_id" bigint                 generated always as identity not null,
  "store_id"    bigint                 not null,
  "term"        character varying(100) not null,
  "variants"    character varying(300),
  "description" character varying(300),
  constraint "store_glossary_pkey" primary key (glossary_id),
  constraint "store_glossary_store_id_term_key" unique (store_id, term)
);

create table "public"."store_members" (
  "member_id"      bigint                   generated always as identity not null,
  "store_id"       bigint                   not null,
  "user_id"        bigint                   not null,
  "member_role"    character varying(20)    not null,
  "joined_at"      timestamp with time zone not null default now(),
  "day_count"      integer                  not null default 0,
  "progress_rate"  numeric(5,2)             not null default 0,
  "is_deployable"  boolean                  not null default false,
  "last_active_at" timestamp with time zone,
  constraint "store_members_member_role_check" check (((member_role)::text = ANY ((ARRAY['OWNER'::character varying, 'STAFF'::character varying])::text[]))),
  constraint "store_members_pkey" primary key (member_id),
  constraint "store_members_store_id_user_id_key" unique (store_id, user_id)
);

create table "public"."stores" (
  "store_id"           bigint                   generated always as identity not null,
  "owner_id"           bigint                   not null,
  "store_slug"         character varying(50),
  "store_name"         character varying(100)   not null,
  "business_type"      character varying(20)    not null,
  "deploy_threshold"   integer                  not null default 80,
  "knowledge_coverage" numeric(5,2)             not null default 0,
  "dek_encrypted"      bytea,
  "created_at"         timestamp with time zone not null default now(),
  constraint "stores_business_type_check"
    check
    (((business_type)::text = ANY ((ARRAY['CAFE'::character varying, 'RESTAURANT'::character varying, 'BAKERY'::character varying, 'BAR'::character varying, 'CVS'::character
    varying, 'SALON'::character varying])::text[]))),
  constraint "stores_pkey" primary key (store_id),
  constraint "stores_store_slug_key" unique (store_slug)
);

create table "public"."task_categories" (
  "category_id"   bigint                generated always as identity not null,
  "store_id"      bigint                not null,
  "category_name" character varying(50) not null,
  "is_enabled"    boolean               not null default true,
  "sort_order"    integer               not null default 0,
  constraint "task_categories_pkey" primary key (category_id),
  constraint "task_categories_store_id_category_name_key" unique (store_id, category_name)
);

create table "public"."users" (
  "user_id"       bigint                   generated always as identity not null,
  "name"          character varying(50)    not null,
  "phone"         character varying(20),
  "email"         character varying(255),
  "password_hash" text,
  "role"          character varying(20)    not null,
  "created_at"    timestamp with time zone not null default now(),
  constraint "users_email_key" unique (email),
  constraint "users_pkey" primary key (user_id),
  constraint "users_role_check" check (((role)::text = ANY ((ARRAY['OWNER'::character varying, 'STAFF'::character varying])::text[])))
);

create or replace function public.match_cards (
  p_store_id  bigint,
  p_embedding public.vector,
  p_top_k     integer       default 5
)
  returns table (
    card_id bigint,
    content text,
    title   character varying,
    score   double precision
  )
  language sql
  stable
  AS $function$
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
$function$;

alter table "public"."chat_messages"
  add constraint "chat_messages_session_id_fkey" foreign key (session_id) references public.chat_sessions(session_id) on delete cascade;

alter table "public"."access_logs"
  add constraint "access_logs_card_id_fkey" foreign key (card_id) references public.knowledge_cards(card_id) on delete set null;

alter table "public"."card_embeddings"
  add constraint "card_embeddings_card_id_fkey" foreign key (card_id) references public.knowledge_cards(card_id) on delete cascade;

alter table "public"."facts"
  add constraint "facts_card_id_fkey" foreign key (card_id) references public.knowledge_cards(card_id) on delete cascade;

alter table "public"."message_citations"
  add constraint "message_citations_card_id_fkey" foreign key (card_id) references public.knowledge_cards(card_id) on delete cascade;

alter table "public"."message_citations"
  add constraint "message_citations_message_id_fkey" foreign key (message_id) references public.chat_messages(message_id) on delete cascade;

alter table "public"."owner_answers"
  add constraint "owner_answers_card_id_fkey" foreign key (card_id) references public.knowledge_cards(card_id) on delete set null;

alter table "public"."pending_questions"
  add constraint "pending_questions_message_id_fkey" foreign key (message_id) references public.chat_messages(message_id) on delete set null;

alter table "public"."owner_answers"
  add constraint "owner_answers_question_id_fkey" foreign key (question_id) references public.pending_questions(question_id) on delete cascade;

alter table "public"."roadmap_items"
  add constraint "roadmap_items_card_id_fkey" foreign key (card_id) references public.knowledge_cards(card_id) on delete set null;

alter table "public"."learning_progress"
  add constraint "learning_progress_item_id_fkey" foreign key (item_id) references public.roadmap_items(item_id) on delete cascade;

alter table "public"."roadmap_items"
  add constraint "roadmap_items_stage_id_fkey" foreign key (stage_id) references public.roadmap_stages(stage_id) on delete cascade;

alter table "public"."source_frames"
  add constraint "source_frames_video_id_fkey" foreign key (video_id) references public.source_video(video_id) on delete cascade;

alter table "public"."knowledge_cards"
  add constraint "knowledge_cards_source_id_fkey" foreign key (source_id) references public.sources(source_id) on delete set null;

alter table "public"."source_kakao"
  add constraint "source_kakao_source_id_fkey" foreign key (source_id) references public.sources(source_id) on delete cascade;

alter table "public"."source_scan"
  add constraint "source_scan_source_id_fkey" foreign key (source_id) references public.sources(source_id) on delete cascade;

alter table "public"."source_video"
  add constraint "source_video_source_id_fkey" foreign key (source_id) references public.sources(source_id) on delete cascade;

alter table "public"."source_voice"
  add constraint "source_voice_source_id_fkey" foreign key (source_id) references public.sources(source_id) on delete cascade;

alter table "public"."chat_sessions"
  add constraint "chat_sessions_member_id_fkey" foreign key (member_id) references public.store_members(member_id) on delete cascade;

alter table "public"."learning_progress"
  add constraint "learning_progress_member_id_fkey" foreign key (member_id) references public.store_members(member_id) on delete cascade;

alter table "public"."pending_questions"
  add constraint "pending_questions_member_id_fkey" foreign key (member_id) references public.store_members(member_id) on delete cascade;

alter table "public"."access_logs"
  add constraint "access_logs_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."card_embeddings"
  add constraint "card_embeddings_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."chat_sessions"
  add constraint "chat_sessions_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."invite_codes"
  add constraint "invite_codes_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."knowledge_cards"
  add constraint "knowledge_cards_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."pending_questions"
  add constraint "pending_questions_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."roadmap_stages"
  add constraint "roadmap_stages_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."sources"
  add constraint "sources_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."store_glossary"
  add constraint "store_glossary_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."store_members"
  add constraint "store_members_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."knowledge_cards"
  add constraint "knowledge_cards_category_id_fkey" foreign key (category_id) references public.task_categories(category_id) on delete set null;

alter table "public"."pending_questions"
  add constraint "pending_questions_category_id_fkey" foreign key (category_id) references public.task_categories(category_id) on delete set null;

alter table "public"."task_categories"
  add constraint "task_categories_store_id_fkey" foreign key (store_id) references public.stores(store_id) on delete cascade;

alter table "public"."access_logs"
  add constraint "access_logs_user_id_fkey" foreign key (user_id) references public.users(user_id) on delete cascade;

alter table "public"."invite_codes"
  add constraint "invite_codes_used_by_fkey" foreign key (used_by) references public.users(user_id);

alter table "public"."owner_answers"
  add constraint "owner_answers_answered_by_fkey" foreign key (answered_by) references public.users(user_id);

alter table "public"."sources"
  add constraint "sources_uploaded_by_fkey" foreign key (uploaded_by) references public.users(user_id);

alter table "public"."store_members"
  add constraint "store_members_user_id_fkey" foreign key (user_id) references public.users(user_id) on delete cascade;

alter table "public"."stores"
  add constraint "stores_owner_id_fkey" foreign key (owner_id) references public.users(user_id) on delete restrict;

create index access_logs_store_id_accessed_at_idx on public.access_logs using btree (store_id, accessed_at desc);

create index card_embeddings_embedding_idx on public.card_embeddings using hnsw (embedding public.vector_cosine_ops);

create index card_embeddings_lexical_tsv_idx on public.card_embeddings using gin (lexical_tsv);

create index card_embeddings_store_id_idx on public.card_embeddings using btree (store_id)
  where (is_stale = false);

create index chat_messages_session_id_created_at_idx on public.chat_messages using btree (session_id, created_at);

create index facts_card_id_idx on public.facts using btree (card_id);

create index invite_codes_store_id_idx on public.invite_codes using btree (store_id)
  where (is_used = false);

create index knowledge_cards_store_id_category_id_idx on public.knowledge_cards using btree (store_id, category_id);

create index knowledge_cards_store_id_idx on public.knowledge_cards using btree (store_id)
  where (is_verified = true);

create index learning_progress_member_id_status_idx on public.learning_progress using btree (member_id, status);

create index pending_questions_store_id_status_idx on public.pending_questions using btree (store_id, status);

create index roadmap_items_stage_id_item_order_idx on public.roadmap_items using btree (stage_id, item_order);

create unique index sources_store_id_content_hash_idx on public.sources using btree (store_id, content_hash)
  where (content_hash is not null);

create index sources_store_id_status_idx on public.sources using btree (store_id, status);

create index store_members_store_id_user_id_idx on public.store_members using btree (store_id, user_id);

create index task_categories_store_id_idx on public.task_categories using btree (store_id)
  where (is_enabled = true);

comment on column "public"."card_embeddings"."model_name" is 'D4: OpenAI text-embedding-3-small(1536) 고정. 모델 교체 시 임계값·골든셋 전면 재측정 필요';

comment on column "public"."knowledge_cards"."confidence" is 'D3: 60 미만이면 점주 검수 화면 상단 우선 노출. 0~100 백분율';

comment on column "public"."knowledge_cards"."is_sensitive" is 'D5: 컬럼만 유지. 현 릴리스는 마스킹 미적용. 향후 레시피 보호용';

comment on column "public"."knowledge_cards"."is_verified" is '검색 게이트의 approved 와 동일 의미. true 인 카드만 /reg/retrieve 대상';

comment on column "public"."pending_questions"."miss_reason" is '검색 게이트가 반환한 miss 사유 보존. 빈 지식 알림 분류에 사용';

comment on column "public"."source_frames"."landmark_desc" is '주변 사물 기준 표현만 허용. 화면좌표·거리 표현 금지';

comment on column "public"."sources"."status" is 'D6: 프론트가 2초 간격 폴링. FAILED 는 error_message 필수';

comment on column "public"."stores"."dek_encrypted" is 'D5 예약. 민감 지식 봉투암호화용. 현 릴리스에서는 쓰지 않음';

comment on column "public"."stores"."store_slug" is 'FastAPI /reg/* 의 문자열 store_id 를 BIGINT 로 해석하기 위한 별칭';

comment on extension "pg_trgm" is 'text similarity measurement and index searching based on trigrams';

comment on extension "vector" is 'vector data type and ivfflat and hnsw access methods';

comment on table "public"."message_citations" is 'BUDDY 메시지가 ANSWERED 인데 이 행이 0건이면 계약 위반. 답변을 폐기해야 함';

grant execute on function "public"."match_cards"(bigint, public.vector, integer) to public, "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."access_logs" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."card_embeddings" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."chat_messages" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."chat_sessions" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."facts" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."invite_codes" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."knowledge_cards" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."learning_progress" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."message_citations" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."owner_answers" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."pending_questions" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."roadmap_items" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."roadmap_stages" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."source_frames" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."source_kakao" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."source_scan" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."source_video" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."source_voice" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."sources" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."store_glossary" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."store_members" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."stores" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."task_categories" to "anon", "authenticated", "postgres", "service_role";

grant delete, insert, maintain, references, select, trigger, truncate, update on table "public"."users" to "anon", "authenticated", "postgres", "service_role";

alter default privileges for role "postgres" in schema "public" grant select, update, usage on sequences to "anon";

alter default privileges for role "postgres" in schema "public" grant select, update, usage on sequences to "authenticated";

alter default privileges for role "postgres" in schema "public" grant select, update, usage on sequences to "service_role";

alter default privileges for role "postgres" in schema "public" grant execute on FUNCTIONS to "anon";

alter default privileges for role "postgres" in schema "public" grant execute on FUNCTIONS to "authenticated";

alter default privileges for role "postgres" in schema "public" grant execute on FUNCTIONS to "service_role";

alter default privileges for role "postgres" in schema "public" grant delete, insert, maintain, references, select, trigger, truncate, update on tables to "anon";

alter default privileges for role "postgres" in schema "public" grant delete, insert, maintain, references, select, trigger, truncate, update on tables to "authenticated";

alter default privileges for role "postgres" in schema "public" grant delete, insert, maintain, references, select, trigger, truncate, update on tables to "service_role";
