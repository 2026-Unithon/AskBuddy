-- 20261108120400 보강(2026-11-09): 눈에 같은 두 글이 보이지 않는 글자(줄바꿈 금지 공백·폭 0 공백·BOM)만 다를 때도
-- 같은 말로 보고 열린 충돌을 닫는다. 120400 은 이미 배포됐을 수 있어 고치지 않고 이 파일로 덧붙인다.
-- squash 는 app/ingest/text_norm.squash 와 같다. 사실은 지우지 않고 충돌만 OBSOLETE. 다시 돌려도 같은 결과.
create or replace function pg_temp.squash(t text) returns text language sql immutable as $$
  select regexp_replace(coalesce(t, ''),
    '[[:space:]' || chr(160) || chr(8203) || chr(8204) || chr(8205) || chr(8288) || chr(65279) || ']', '', 'g')
$$;

update fact_conflicts c
   set status = 'OBSOLETE',
       decided_at = now(),
       resolution = jsonb_build_object('by', 'SAME_STATEMENT')
  from knowledge_facts kl
  join fact_revisions rl on rl.store_id = kl.store_id and rl.fact_revision_id = kl.head_revision_id,
       knowledge_facts kh
  join fact_revisions rh on rh.store_id = kh.store_id and rh.fact_revision_id = kh.head_revision_id
 where c.status = 'OPEN'
   and kl.store_id = c.store_id and kl.fact_id = c.fact_id_low
   and kh.store_id = c.store_id and kh.fact_id = c.fact_id_high
   and coalesce(rl.polarity, 'AFFIRM') = coalesce(rh.polarity, 'AFFIRM')
   and (
     (pg_temp.squash(rl.original_assertion) <> ''
      and pg_temp.squash(rl.original_assertion) = pg_temp.squash(rh.original_assertion))
     or (rl.quantity_value is not null and rh.quantity_value is not null
         and rl.quantity_value = rh.quantity_value
         and lower(pg_temp.squash(rl.quantity_unit)) = lower(pg_temp.squash(rh.quantity_unit)))
     or (rl.quantity_value is null and rh.quantity_value is null
         and pg_temp.squash(rl.value_text) <> ''
         and pg_temp.squash(rl.value_text) = pg_temp.squash(rh.value_text))
   );
