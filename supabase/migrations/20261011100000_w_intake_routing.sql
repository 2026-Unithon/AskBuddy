-- Phase B — 입구 분류 기록·점주 답변 첨부·점주 선택 칩·사실 ext (가산 변경만).
-- 설계 W_PHASE_B_INTAKE_ROUTER_DESIGN_20261010.md B-D3a·B-D6·4-3, 계획 W_PHASE_B_PLAN_20261011.md.

alter table sources add column if not exists owner_hints text[];
alter table sources drop constraint if exists sources_owner_hints_check;
alter table sources add constraint sources_owner_hints_check
  check (owner_hints is null
         or owner_hints <@ array['RECIPE','PROCEDURE','POLICY','REFERENCE','NOTICE']::text[]);

-- 로직별 확장 칸. 원장에만 둔다 — 사실 판 hash·공개 계약에 넣지 않는다(설계 4-3)
alter table source_facts add column if not exists ext jsonb;

create table if not exists intake_route_decisions (
  decision_id      bigserial primary key,
  store_id         bigint not null references stores(store_id),
  source_id        bigint not null references sources(source_id),
  entry            varchar(20) not null check (entry in ('UPLOAD', 'OWNER_ANSWER')),
  owner_answer_id  bigint references owner_answers(answer_id),
  normalizer       varchar(20) not null
                   check (normalizer in ('DOC_TEXT','DOC_IMAGE','AUDIO','VIDEO','CHAT','OWNER_TEXT')),
  -- 표본 요약만 남긴다. 원문은 저장하지 않는다(B-D6)
  sample_summary   jsonb not null,
  sample_hash      char(64) not null,
  owner_hints      text[],
  model            varchar(120),
  prompt_digest    varchar(64),
  model_sections   jsonb not null,
  decisions        jsonb not null,
  source_decision  jsonb not null,
  source_logic     varchar(20) not null
                   check (source_logic in ('RECIPE','PROCEDURE','POLICY','REFERENCE','NOTICE','NONE')),
  logical_call_id  varchar(80),
  created_at       timestamptz not null default now()
);
create index if not exists intake_route_decisions_source_idx
  on intake_route_decisions (store_id, source_id, decision_id desc);

create table if not exists owner_answer_attachments (
  store_id             bigint not null references stores(store_id),
  pending_question_id  bigint not null references pending_questions(question_id),
  source_id            bigint not null references sources(source_id),
  created_at           timestamptz not null default now(),
  primary key (store_id, source_id)
);
create index if not exists owner_answer_attachments_question_idx
  on owner_answer_attachments (store_id, pending_question_id);

create or replace function askbuddy_intake_store_check()
returns trigger language plpgsql as $$
begin
  -- 자료가 이 매장 것이어야 한다(D1)
  if not exists (select 1 from sources s where s.source_id = new.source_id and s.store_id = new.store_id) then
    raise exception '입구 기록의 자료 매장이 맞지 않는다 (store=%, source=%)', new.store_id, new.source_id;
  end if;
  if tg_table_name = 'owner_answer_attachments' then
    if not exists (select 1 from pending_questions q
                   where q.question_id = new.pending_question_id and q.store_id = new.store_id)
       or exists (select 1 from sources s where s.source_id = new.source_id and s.source_type = 'OWNER_TEXT') then
      raise exception '점주 답변 첨부의 질문 매장 또는 자료 종류가 맞지 않는다 (store=%, question=%, source=%)',
        new.store_id, new.pending_question_id, new.source_id;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists trg_intake_route_decisions_store_check on intake_route_decisions;
create trigger trg_intake_route_decisions_store_check
before insert or update on intake_route_decisions
for each row execute function askbuddy_intake_store_check();

drop trigger if exists trg_owner_answer_attachments_store_check on owner_answer_attachments;
create trigger trg_owner_answer_attachments_store_check
before insert or update on owner_answer_attachments
for each row execute function askbuddy_intake_store_check();

comment on table intake_route_decisions is '입구 분류 개발용 기록(Phase B B-D6). 제품 화면·API 없음';
comment on table owner_answer_attachments is '점주 답변 첨부 자료 — 대기 질문에 묶는다(Phase B B-D1)';
