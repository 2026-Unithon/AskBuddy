-- Diagnostics expire after 30 days; immutable answers and policy links remain.
begin;
create index r_answer_receipts_retention on r_answer_receipts(store_id,created_at)
  where execution_metadata <> '{}'::jsonb;

create or replace function askbuddy_answer_receipt_immutable() returns trigger language plpgsql as $$
begin
  if tg_table_name = 'r_answer_receipts' and tg_op = 'UPDATE' then
    if old.created_at <= clock_timestamp() - interval '30 days'
       and (to_jsonb(new) - 'execution_metadata') = (to_jsonb(old) - 'execution_metadata')
       and new.execution_metadata = (case when old.execution_metadata ? 'policy_receipt_id'
         then jsonb_build_object('policy_receipt_id',old.execution_metadata->'policy_receipt_id')
         else '{}'::jsonb end) then
      return new;
    end if;
  end if;
  raise exception 'answer history is immutable';
end;
$$;

create function purge_r_execution_metadata(target_store_id bigint) returns bigint
language plpgsql security invoker set search_path=public,pg_temp as $$
declare removed bigint;
begin
  update r_answer_receipts set execution_metadata = case when execution_metadata ? 'policy_receipt_id'
    then jsonb_build_object('policy_receipt_id',execution_metadata->'policy_receipt_id') else '{}'::jsonb end
  where store_id=target_store_id and created_at<=clock_timestamp()-interval '30 days'
    and (execution_metadata - 'policy_receipt_id') <> '{}'::jsonb;
  get diagnostics removed = row_count;
  return removed;
end;
$$;
revoke all on function purge_r_execution_metadata(bigint) from public,anon,authenticated;
grant execute on function purge_r_execution_metadata(bigint) to service_role;
-- Direct browser roles cannot read original questions or their diagnostics.
revoke all on r_answer_receipts,r_answer_citations from public,anon,authenticated;
alter table r_answer_receipts enable row level security;
alter table r_answer_citations enable row level security;
grant select,insert,update on r_answer_receipts to service_role;
grant select,insert on r_answer_citations to service_role;
grant usage on sequence r_answer_receipts_receipt_id_seq to service_role;
create policy r_receipts_backend on r_answer_receipts to service_role using(true) with check(true);
create policy r_citations_backend on r_answer_citations to service_role using(true) with check(true);
commit;
