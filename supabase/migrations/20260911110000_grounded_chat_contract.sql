begin;

alter table chat_messages
  add column if not exists answer_source varchar(30),
  add column if not exists grounding_status varchar(20);

update chat_messages
set answer_source = case
      when answer_type = 'NO_ANSWER' then 'MISS'
      when answer_type = 'ANSWERED' then 'CARD_ORIGINAL'
      else answer_source
    end,
    grounding_status = case
      when answer_type = 'NO_ANSWER' then 'NOT_APPLICABLE'
      when answer_type = 'ANSWERED' then 'LEGACY'
      else grounding_status
    end
where sender_type = 'BUDDY'
  and (answer_source is null or grounding_status is null);

alter table chat_messages
  drop constraint if exists chat_messages_answer_source_check,
  add constraint chat_messages_answer_source_check
    check (
      answer_source is null
      or answer_source in ('CARD_ORIGINAL', 'GROUNDED_LLM', 'MISS', 'OWNER_ANSWER')
    ),
  drop constraint if exists chat_messages_grounding_status_check,
  add constraint chat_messages_grounding_status_check
    check (
      grounding_status is null
      or grounding_status in ('VERIFIED', 'FALLBACK', 'NOT_APPLICABLE', 'LEGACY')
    );

alter table message_citations
  add column if not exists version_id bigint;

update message_citations mc
set version_id = c.published_version_id
from knowledge_cards c
where c.card_id = mc.card_id
  and mc.version_id is null;

create unique index if not exists uq_card_versions_card_version
  on card_versions (card_id, version_id);

alter table message_citations
  drop constraint if exists message_citations_version_id_fkey,
  drop constraint if exists message_citations_card_version_fkey,
  add constraint message_citations_card_version_fkey
    foreign key (card_id, version_id)
    references card_versions(card_id, version_id) on delete restrict;

create index if not exists idx_message_citations_version
  on message_citations (version_id)
  where version_id is not null;

comment on column chat_messages.answer_source is
  'CARD_ORIGINAL/GROUNDED_LLM/MISS/OWNER_ANSWER. 생성 답변과 결정적 폴백을 구분한다.';
comment on column chat_messages.grounding_status is
  '생성 답변의 서버 검증 결과. LEGACY는 이 계약 도입 전 저장된 답변이다.';
comment on column message_citations.version_id is
  '답변 생성 당시 실제 사용한 공개 카드 버전. 과거 대화 감사 추적용이다.';

commit;
