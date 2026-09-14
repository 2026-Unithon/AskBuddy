-- M0 공통 operation·outbox·소비자 중복 제거 (C0 결정서 §4.3, CP-04)
--
-- 왜 지금 만드는가:
--   응답이 유실되거나 commit 결과가 불명확할 때 재시도가 업무를 두 번 만들면
--   점주에게 같은 알림이 두 번 가고, 카드가 두 번 공개된다. 이걸 코드로만 막으면
--   호출 경로마다 규칙이 달라진다. DB unique 로 못 박는다.
--
--   outbox 전달은 at-least-once 다. 같은 사건이 두 번 오고 순서가 뒤집힌다.
--   소비 결과를 (매장, 소비자, 사건) 으로 유일하게 두면 두 번 반영하지 않는다.
--
-- 격리: RLS 를 쓰지 않으므로(D1) 모든 표가 store_id 를 갖고,
--       매장 경계를 넘는 참조는 composite FK 로 막는다.

begin;

-- ── 요청 멱등성 ────────────────────────────────────────────────────────────
create table if not exists operations (
  operation_id    bigint generated always as identity primary key,
  store_id        bigint      not null references stores(store_id) on delete cascade,
  -- 회원 없이 도는 내부 worker 도 있다
  member_id       bigint      references store_members(member_id) on delete set null,
  operation       varchar(40) not null,
  idempotency_key varchar(80) not null,
  -- 같은 키에 다른 본문이면 409 다. 조용히 덮지 않는다
  body_hash       text        not null,
  status          varchar(20) not null default 'STARTED'
    check (status in ('STARTED', 'SUCCEEDED', 'FAILED')),
  -- 성공 응답을 그대로 되돌려주기 위해 보관한다. 24시간 (§4.3)
  response        jsonb,
  error_code      varchar(40),
  created_at      timestamptz not null default now(),
  finished_at     timestamptz,
  expires_at      timestamptz not null default now() + interval '24 hours',
  unique (store_id, member_id, operation, idempotency_key)
);

create index if not exists idx_operations_store_expiry
  on operations (store_id, expires_at);

-- 응답을 저장했다면 성공한 것이다. 둘이 어긋나면 재조회가 틀린 답을 준다
alter table operations drop constraint if exists operations_response_matches_status;
alter table operations add constraint operations_response_matches_status
  check ((status = 'SUCCEEDED') = (response is not null));

-- ── outbox ────────────────────────────────────────────────────────────────
-- payload 에 업무 내용을 담지 않는다. 실으면 권한이 바뀐 뒤에도 옛 내용이 나간다
create table if not exists outbox_events (
  event_id          bigint generated always as identity primary key,
  store_id          bigint      not null references stores(store_id) on delete cascade,
  contract_version  varchar(10) not null default 'v1',
  event_type        varchar(40) not null
    check (event_type in ('KNOWLEDGE_PUBLISHED', 'CARD_EXCLUDED',
                          'CARD_RESTORED', 'OWNER_ANSWER_SUBMITTED')),
  aggregate_id      bigint      not null,
  knowledge_revision bigint,
  owner_answer_id   bigint,
  occurred_at       timestamptz not null default now(),
  unique (store_id, event_id)
);

-- 같은 판에 대한 같은 종류의 사건은 하나다. 재시도가 사건을 늘리지 않는다
create unique index if not exists uq_outbox_publication_event
  on outbox_events (store_id, knowledge_revision, event_type)
  where knowledge_revision is not null;

alter table outbox_events drop constraint if exists outbox_events_payload_matches_type;
alter table outbox_events add constraint outbox_events_payload_matches_type
  check (
    (event_type = 'OWNER_ANSWER_SUBMITTED' and owner_answer_id is not null)
    or (event_type <> 'OWNER_ANSWER_SUBMITTED' and knowledge_revision is not null)
  );

-- ── 소비 결과 ──────────────────────────────────────────────────────────────
-- at-least-once 전달을 소비 쪽에서 한 번으로 만든다
create table if not exists outbox_consumptions (
  store_id    bigint      not null references stores(store_id) on delete cascade,
  consumer    varchar(40) not null,
  event_id    bigint      not null,
  result      varchar(20) not null
    check (result in ('APPLIED', 'STALE', 'RESYNC', 'SKIPPED')),
  consumed_at timestamptz not null default now(),
  primary key (store_id, consumer, event_id),
  -- 다른 매장의 사건을 소비한 것으로 기록할 수 없다
  foreign key (store_id, event_id)
    references outbox_events (store_id, event_id) on delete cascade
);

-- 소비자가 어디까지 반영했는지. 낮은 판으로 되돌리지 않기 위한 기준선
create table if not exists outbox_cursors (
  store_id           bigint      not null references stores(store_id) on delete cascade,
  consumer           varchar(40) not null,
  knowledge_revision bigint      not null default 0,
  resync_required    boolean     not null default false,
  updated_at         timestamptz not null default now(),
  primary key (store_id, consumer)
);

-- ── worker lease ──────────────────────────────────────────────────────────
-- BackgroundTasks 단독에 전달 보장을 맡기지 않는다 (§4.3)
create table if not exists outbox_leases (
  store_id     bigint      not null references stores(store_id) on delete cascade,
  consumer     varchar(40) not null,
  event_id     bigint      not null,
  leased_by    varchar(80) not null,
  leased_until timestamptz not null,
  attempts     int         not null default 0,
  status       varchar(20) not null default 'CLAIMED'
    check (status in ('CLAIMED', 'DONE', 'FAILED')),
  last_error   text,
  updated_at   timestamptz not null default now(),
  primary key (store_id, consumer, event_id),
  foreign key (store_id, event_id)
    references outbox_events (store_id, event_id) on delete cascade
);

-- 만료된 lease 를 다시 집는다. lease 60초·heartbeat 20초 (§4.3)
create index if not exists idx_outbox_leases_claimable
  on outbox_leases (consumer, leased_until) where status = 'CLAIMED';

comment on table operations is
  '요청 멱등성. 같은 키·다른 본문은 IDEMPOTENCY_CONFLICT 다 (M0 §4.3)';
comment on table outbox_events is
  '소비자에게 나가는 사건. 업무 내용을 담지 않는다 — 권한 있는 조회로 가져간다 (M0 §4.3)';
comment on table outbox_consumptions is
  'at-least-once 전달을 한 번의 반영으로 만든다 (M0 §4.3)';

commit;
