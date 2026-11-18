-- 계획 10(2026-11-12, D23): 카드 표시는 모델이 쓰고 서버가 검사한다.
-- 블록은 구역 제목(heading)을, 줄(card_version_lines)은 표시 글과 근거 사실 판을 가진다.
-- 줄은 W 표시용이다. 공개 snapshot·답변(R)은 줄이 아니라 사실을 인용한다(D12).
alter table card_version_blocks add column if not exists heading varchar(40);

create table if not exists card_version_lines (
  store_id          bigint not null,
  card_version_id   bigint not null,
  block_id          varchar(40) not null,
  line_no           int not null check (line_no >= 1),
  text              varchar(300) not null check (btrim(text) <> ''),
  fact_revision_ids bigint[] not null check (cardinality(fact_revision_ids) >= 1),
  primary key (store_id, card_version_id, block_id, line_no),
  foreign key (store_id, card_version_id, block_id)
    references card_version_blocks (store_id, card_version_id, block_id)
    on delete cascade
);

-- 판에 고정된 줄은 고치지 않는다. 새 글은 새 판이다.
-- 블록째 지우는 연쇄 삭제(pg_trigger_depth() > 1)와 매장 파기만 비켜 준다
create or replace function askbuddy_card_version_lines_immutable()
returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' and pg_trigger_depth() > 1 then
    return old;
  end if;
  raise exception 'card_version_lines 는 판에 고정된 줄이라 고칠 수 없다';
end;
$$;

drop trigger if exists trg_card_version_lines_immutable on card_version_lines;
create trigger trg_card_version_lines_immutable before update or delete on card_version_lines
  for each row when (not askbuddy_purging(old.store_id)) execute function askbuddy_card_version_lines_immutable();
