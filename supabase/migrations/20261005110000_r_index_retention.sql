-- No cleanup is enabled by this migration. N and M are supplied only by the
-- disabled-by-default application sweep. Keep all snapshot/provenance headers.
begin;
alter table r_index_publications add column retired_at timestamptz;
alter table r_index_preparations add column documents_pruned_at timestamptz;
-- Give historical rows a full grace period after deployment.
update r_index_publications a set retired_at=clock_timestamp()
where not exists (select 1 from knowledge_publications p
  where p.store_id=a.store_id and p.current_snapshot_id=a.snapshot_id);

create function r_index_retired() returns trigger language plpgsql as $$
begin
  if new.current_snapshot_id is distinct from old.current_snapshot_id then
    if exists (select 1 from r_index_publications a join r_index_preparations i
        on i.store_id=a.store_id and i.prepared_id=a.prepared_id
        where a.store_id=new.store_id and a.snapshot_id=new.current_snapshot_id
          and i.documents_pruned_at is not null) then
      raise exception 'cannot activate a pruned index';
    end if;
    update r_index_publications set retired_at=clock_timestamp()
      where store_id=old.store_id and snapshot_id=old.current_snapshot_id;
    update r_index_publications set retired_at=null
      where store_id=new.store_id and snapshot_id=new.current_snapshot_id;
  end if;
  return new;
end;
$$;
create trigger r_index_retirement after update of current_snapshot_id on knowledge_publications
  for each row execute function r_index_retired();

create function r_index_prunable(sid bigint, pid bigint, keep_n integer, age_days integer)
returns boolean language sql stable as $$
  select keep_n >= 0 and age_days >= 1 and exists (
    select 1 from r_index_preparations i
    left join r_index_publications a on a.store_id=i.store_id and a.prepared_id=i.prepared_id
    where i.store_id=sid and i.prepared_id=pid
      and i.state <> 'PREPARING'
      and (i.state <> 'PREPARED' or i.expires_at <= now())
      and greatest(i.created_at, i.expires_at, coalesce(a.retired_at, i.created_at))
            <= now() - make_interval(days => age_days)
      and (i.state <> 'CONSUMED' or a.retired_at is not null)
      and not exists (select 1 from knowledge_publications p
          where p.store_id=sid and p.current_snapshot_id=a.snapshot_id)
      and pid not in (
        select previous.prepared_id from r_index_publications previous
        join knowledge_snapshots s on s.store_id=previous.store_id and s.snapshot_id=previous.snapshot_id
        where previous.store_id=sid and previous.retired_at is not null
        order by previous.retired_at desc, s.knowledge_revision desc limit keep_n)
  );
$$;

create or replace function askbuddy_index_documents_immutable()
returns trigger language plpgsql as $$
declare preparation_state text; keep_n integer; age_days integer;
begin
  if TG_OP = 'DELETE' then
    -- Same lock order as publication/activation. Recheck under locks, never trust a list
    -- selected before a concurrent publication. The settings alone cannot bypass guards.
    perform 1 from knowledge_publications where store_id=old.store_id for update;
    perform 1 from r_index_preparations where store_id=old.store_id
      and prepared_id=old.prepared_id for update;
    keep_n := nullif(current_setting('askbuddy.index_gc_keep', true),'')::integer;
    age_days := nullif(current_setting('askbuddy.index_gc_days', true),'')::integer;
    if keep_n is not null and age_days is not null
       and r_index_prunable(old.store_id, old.prepared_id, keep_n, age_days) then
      update r_index_preparations set documents_pruned_at=clock_timestamp()
        where store_id=old.store_id and prepared_id=old.prepared_id
          and documents_pruned_at is null;
      return old;
    end if;
    raise exception 'index retention policy protects these documents';
  end if;
  if TG_OP <> 'INSERT' then
    raise exception 'prepared index documents are append-only';
  end if;
  select state into preparation_state from r_index_preparations
    where store_id=new.store_id and prepared_id=new.prepared_id for share;
  if preparation_state is distinct from 'PREPARING' then
    raise exception 'cannot append documents after preparation';
  end if;
  return new;
end;
$$;

create function purge_r_index_documents(sid bigint, keep_n integer, age_days integer)
returns bigint language plpgsql as $$
declare removed bigint; previous_keep text; previous_days text;
begin
  if keep_n is null or age_days is null or keep_n < 0 or age_days < 1 then
    raise exception 'explicit valid retention policy is required';
  end if;
  perform 1 from knowledge_publications where store_id=sid for update;
  -- Lock candidate headers before the document DELETE (preparation inserts take a
  -- shared header lock). Protect in-flight readers through the retirement grace period.
  perform 1 from r_index_preparations i where i.store_id=sid
    and r_index_prunable(sid,i.prepared_id,keep_n,age_days) order by i.prepared_id for update;
  previous_keep := current_setting('askbuddy.index_gc_keep',true);
  previous_days := current_setting('askbuddy.index_gc_days',true);
  perform set_config('askbuddy.index_gc_keep',keep_n::text,true);
  perform set_config('askbuddy.index_gc_days',age_days::text,true);
  with removed_docs as (
    delete from r_index_documents d where d.store_id=sid
      and r_index_prunable(sid,d.prepared_id,keep_n,age_days)
    returning d.prepared_id
  ) select count(*) into removed from removed_docs;
  perform set_config('askbuddy.index_gc_keep',coalesce(previous_keep,''),true);
  perform set_config('askbuddy.index_gc_days',coalesce(previous_days,''),true);
  return removed;
end;
$$;
commit;
