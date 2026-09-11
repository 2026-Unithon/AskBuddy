begin;

alter table pending_questions
  add column if not exists normalized_question text;

create or replace function askbuddy_normalize_question_text(p_text text)
returns text
language sql
immutable
parallel safe
as $$
  select lower(regexp_replace(trim(coalesce(p_text, '')), '\s+', ' ', 'g'));
$$;

update pending_questions
set normalized_question = askbuddy_normalize_question_text(question_text)
where normalized_question is null
   or normalized_question <> askbuddy_normalize_question_text(question_text);

alter table pending_questions
  alter column normalized_question set not null;

create or replace function askbuddy_fill_normalized_question()
returns trigger
language plpgsql
as $$
begin
  new.normalized_question := askbuddy_normalize_question_text(new.question_text);
  if tg_op = 'UPDATE'
     and old.status = 'ANSWERED'
     and new.question_text is distinct from old.question_text then
    raise exception 'answered question text is immutable';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_pending_questions_normalize on pending_questions;
create trigger trg_pending_questions_normalize
before insert or update of question_text on pending_questions
for each row execute function askbuddy_fill_normalized_question();

create index if not exists idx_pending_questions_store_normalized
  on pending_questions (store_id, normalized_question, status, created_at desc);

create table if not exists pending_question_occurrences (
  occurrence_id bigint generated always as identity primary key,
  question_id   bigint not null references pending_questions(question_id) on delete cascade,
  member_id     bigint not null references store_members(member_id) on delete cascade,
  message_id    bigint unique references chat_messages(message_id) on delete set null,
  asked_at      timestamptz not null default now(),
  unique (question_id, member_id, message_id)
);

insert into pending_question_occurrences (question_id, member_id, message_id, asked_at)
select question_id, member_id, message_id, created_at
from pending_questions
on conflict do nothing;

create index if not exists idx_pending_occurrences_question_member
  on pending_question_occurrences (question_id, member_id, asked_at desc);

create unique index if not exists uq_task_categories_store_category
  on task_categories (store_id, category_id);

create or replace function askbuddy_protect_owner_answer_raw()
returns trigger
language plpgsql
as $$
begin
  if new.question_id is distinct from old.question_id
     or new.answered_by is distinct from old.answered_by
     or new.answer_text is distinct from old.answer_text
     or new.answered_at is distinct from old.answered_at then
    raise exception 'owner answer raw fields are immutable';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_owner_answers_protect_raw on owner_answers;
create trigger trg_owner_answers_protect_raw
before update on owner_answers
for each row execute function askbuddy_protect_owner_answer_raw();

alter table chat_messages
  add column if not exists owner_answer_id bigint
    references owner_answers(answer_id) on delete set null;

create index if not exists idx_chat_messages_owner_answer
  on chat_messages (owner_answer_id)
  where owner_answer_id is not null;

create table if not exists knowledge_change_proposals (
  proposal_id       bigint generated always as identity primary key,
  store_id          bigint not null references stores(store_id) on delete cascade,
  answer_id         bigint not null unique references owner_answers(answer_id) on delete cascade,
  relation_type     varchar(20) not null
                    check (relation_type in ('IDENTICAL', 'SUPPLEMENT', 'CONFLICT', 'NEW')),
  target_card_id    bigint,
  target_version_id bigint references card_versions(version_id) on delete restrict,
  category_id       bigint not null,
  proposed_title    varchar(200) not null,
  proposed_content  text not null,
  reason            text,
  status            varchar(30) not null
                    check (status in (
                      'ANALYZED', 'LINKED', 'PENDING_REVIEW',
                      'PUBLISHED', 'FAILED', 'DISMISSED'
                    )),
  result_card_id    bigint,
  result_version_id bigint references card_versions(version_id) on delete restrict,
  error             jsonb,
  created_at        timestamptz not null default now(),
  resolved_at       timestamptz,
  foreign key (store_id, target_card_id)
    references knowledge_cards(store_id, card_id) on delete restrict,
  foreign key (store_id, result_card_id)
    references knowledge_cards(store_id, card_id) on delete restrict,
  foreign key (store_id, category_id)
    references task_categories(store_id, category_id) on delete restrict,
  foreign key (target_card_id, target_version_id)
    references card_versions(card_id, version_id) on delete restrict,
  foreign key (result_card_id, result_version_id)
    references card_versions(card_id, version_id) on delete restrict
);

create index if not exists idx_knowledge_change_proposals_store_status
  on knowledge_change_proposals (store_id, status, created_at desc);

create index if not exists idx_knowledge_change_proposals_target
  on knowledge_change_proposals (store_id, target_card_id, created_at desc)
  where target_card_id is not null;

comment on table knowledge_change_proposals is
  '점주 원문 답변과 공개 카드 반영을 분리한다. SUPPLEMENT/CONFLICT는 승인 전 공개본을 바꾸지 않는다.';
comment on column pending_questions.normalized_question is
  '공백과 대소문자만 정규화한 질문 키. 중복 대기 방지와 FAQ 집계에 사용한다.';
comment on table pending_question_occurrences is
  '대기 질문은 중복하지 않되 같은 질문을 한 모든 직원과 채팅 메시지를 보존한다.';
comment on column chat_messages.owner_answer_id is
  '직원에게 전달된 점주 원문 답변의 불변 원본 링크.';

commit;
