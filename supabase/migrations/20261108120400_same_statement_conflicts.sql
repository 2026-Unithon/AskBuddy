-- 사람 눈에 같은 두 값(띄어쓰기만 다르거나, 한 문장을 두 번 뽑아 수치만 달리 읽은 경우)으로 열린 충돌을 닫는다.
-- 2026-11-08 사용자 실화면: 같은 글 두 버튼을 고르라고 했다. 새 충돌은 fact_ledger.same_statement 가 막는다.
-- 사실은 지우지 않고 충돌만 OBSOLETE. 다시 돌려도 같은 결과(OPEN 만 고친다).
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
     (regexp_replace(coalesce(rl.original_assertion, ''), '\s', '', 'g') <> ''
      and regexp_replace(rl.original_assertion, '\s', '', 'g') = regexp_replace(rh.original_assertion, '\s', '', 'g'))
     or (rl.quantity_value is not null and rh.quantity_value is not null
         and rl.quantity_value = rh.quantity_value
         and lower(regexp_replace(coalesce(rl.quantity_unit, ''), '\s', '', 'g'))
           = lower(regexp_replace(coalesce(rh.quantity_unit, ''), '\s', '', 'g')))
     or (rl.quantity_value is null and rh.quantity_value is null
         and coalesce(rl.value_text, '') <> '' and coalesce(rh.value_text, '') <> ''
         and regexp_replace(rl.value_text, '\s', '', 'g') = regexp_replace(rh.value_text, '\s', '', 'g'))
   );
