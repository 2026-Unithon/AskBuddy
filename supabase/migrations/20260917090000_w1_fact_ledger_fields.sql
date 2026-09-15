-- W1 사실 원장 확장 — 원장이 추출 결과를 온전히 담게 한다
--
-- 왜:
--   지금 원장(source_facts)은 대상·속성·값만 담는다. 그래서 추출이 규격·부정·
--   조건·예외·순서를 뽑아도 저장할 자리가 없어 전부 버려진다. variant 컬럼은
--   있지만 파이프라인이 늘 null 을 넣는다 — 카드에서 거꾸로 베껴 쓰기 때문이다.
--
--   "얼음을 먼저 넣지 않는다" 가 부정 표시 없이 저장되면 금지가 지시가 된다.
--   "포장 주문일 때만" 이 빠지면 모든 주문에 적용된다. 값만 남기면 안 된다.
--
-- 전부 nullable 가산 컬럼이다. 기존 행과 기존 코드는 그대로 돈다.

begin;

alter table source_facts add column if not exists original_assertion text;
alter table source_facts add column if not exists unit varchar(20);
alter table source_facts add column if not exists polarity varchar(10)
  not null default 'AFFIRM' check (polarity in ('AFFIRM', 'NEGATE'));
-- 조건·예외는 본문에 녹이면 나중에 그것만 떼어 확인할 수 없다
alter table source_facts add column if not exists conditions jsonb
  not null default '[]'::jsonb;
alter table source_facts add column if not exists exceptions jsonb
  not null default '[]'::jsonb;
-- 절차의 자리. 순서가 바뀌면 의미가 바뀌는 사실이 있다
alter table source_facts add column if not exists step_order int
  check (step_order is null or step_order >= 1);
-- 이 사실보다 먼저 지켜야 하는 사실들 (같은 자료 안의 local_ref)
alter table source_facts add column if not exists requires jsonb
  not null default '[]'::jsonb;
-- 모델 출력 안에서의 이름표. 조립이 어느 사실을 골랐는지 잇는 데 쓴다
alter table source_facts add column if not exists local_ref varchar(40);
-- 어느 구간에서 나왔나. 구간 분할을 켰을 때 손실 위치를 좁힌다
alter table source_facts add column if not exists segment_id varchar(80);
-- 조립이 이 사실을 카드에 실었는가. **원장을 먼저 쓰기 때문에 생기는 칸이다**
alter table source_facts add column if not exists assembly_state varchar(20)
  not null default 'PENDING'
  check (assembly_state in ('PENDING', 'LINKED', 'DROPPED'));

create index if not exists idx_source_facts_store_assembly
  on source_facts (store_id, assembly_state);

comment on column source_facts.assembly_state is
  'PENDING 조립 전 · LINKED 카드에 실림 · DROPPED 조립이 버림. '
  '원장을 조립 전에 쓰기 때문에 버려진 사실이 남고, 그래야 추출 손실과 '
  '조립 손실을 가를 수 있다 (W1)';
comment on column source_facts.original_assertion is
  '자료에 나온 원문. 값은 그 위의 해석이고 이것이 권위 기준이다';

commit;
