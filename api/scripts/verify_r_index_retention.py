"""Run only against the disposable database created by verify_r_schema_rebuild."""
import asyncpg

from app.reg.embeddings import vector_literal


async def verify(pool, db):
    uid = await db.fetchval("insert into users(name,role) values('합성 정리 점주','OWNER') returning user_id")
    sid = await db.fetchval("insert into stores(owner_id,store_name,business_type) values($1,'합성 정리 매장','CAFE') returning store_id", uid)
    mid = await db.fetchval("insert into store_members(store_id,user_id,member_role) values($1,$2,'OWNER') returning member_id", sid, uid)
    vector = vector_literal([1.] + [0.] * 1535)
    ids = {}
    snapshots = []
    for number, (label, state, live) in enumerate([
        ('old', 'CONSUMED', False), ('kept_old', 'CONSUMED', False),
        ('recent', 'CONSUMED', False), ('active', 'CONSUMED', False),
        ('preparing', 'PREPARING', False), ('prepared', 'PREPARED', True),
        ('expired', 'PREPARED', False)], 1):
        pid = await db.fetchval('''insert into r_index_preparations(store_id,member_id,idempotency_key,
            request_hash,content_hash,content,expected_publication_revision,embedding_model,index_config_version,
            state,claim_id,lease_expires_at,expires_at,created_at)
            values($1,$2,$3,'synthetic','synthetic','{}',0,'synthetic','synthetic','PREPARING',
            '00000000-0000-0000-0000-000000000001',now()-interval '90 days',
            case when $4 then now()+interval '1 day' else now()-interval '90 days' end,
            now()-interval '90 days') returning prepared_id''', sid, mid, label, live)
        ids[label] = pid
        await db.execute('''insert into r_index_documents(store_id,prepared_id,card_id,card_version_id,
            block_id,approved_text,retrieval_text,embedding) values($1,$2,1,1,'b','synthetic','synthetic',$3::vector)''', sid, pid, vector)
        await db.execute('update r_index_preparations set state=$3 where store_id=$1 and prepared_id=$2', sid, pid, state)
        if state == 'CONSUMED':
            snapshot = await db.fetchval('''insert into knowledge_snapshots(store_id,knowledge_revision,
                snapshot_hash,glossary_version,renderer_version) values($1,$2,$3,'glossary/v1','r-approved/v1')
                returning snapshot_id''', sid, number, 'sha256:' + str(number)*64)
            snapshots.append(snapshot)
            await db.execute('''insert into r_index_publications(store_id,snapshot_id,prepared_id,retired_at)
                values($1,$2,$3,now()-interval '90 days'+$4*interval '1 day')''', sid, snapshot, pid, number)
    await db.execute('''insert into knowledge_publications(store_id,publication_revision,knowledge_revision,current_snapshot_id)
        values($1,4,4,$2)''', sid, snapshots[-1])
    await db.execute('update r_index_publications set retired_at=null where store_id=$1 and snapshot_id=$2', sid, snapshots[-1])
    await db.execute('update r_index_publications set retired_at=now() where store_id=$1 and snapshot_id=$2', sid, snapshots[-2])
    try:
        async with db.transaction():
            await db.execute('delete from r_index_documents where store_id=$1', sid)
    except asyncpg.RaiseError:
        print('PASS index retention direct deletion blocked')
    else:
        raise AssertionError('unguarded deletion')
    async with db.transaction():
        removed = await db.fetchval('select purge_r_index_documents($1,2,30)', sid)
    assert removed == 2
    remaining = {r['prepared_id'] for r in await db.fetch('select prepared_id from r_index_documents where store_id=$1', sid)}
    assert remaining == {ids[k] for k in ('kept_old','recent','active','preparing','prepared')}
    assert await db.fetchval('select count(*) from r_index_preparations where store_id=$1', sid) == 7
    assert await db.fetchval('select count(*) from knowledge_snapshots where store_id=$1', sid) == 4
    assert await db.fetchval('select documents_pruned_at is not null from r_index_preparations where store_id=$1 and prepared_id=$2', sid, ids['old'])
    print('PASS index retention active/preparing/prepared/N/grace/header protections')
    assert await db.fetchval('select purge_r_index_documents($1,2,30)', sid) == 0
    try:
        async with db.transaction():
            await db.execute('update knowledge_publications set current_snapshot_id=$2 where store_id=$1', sid, snapshots[0])
    except asyncpg.RaiseError:
        print('PASS index retention pruned index cannot reactivate')
    else:
        raise AssertionError('pruned index activated')
    # Retiring the active preparation starts a fresh grace period, even if created long ago.
    await db.execute('update knowledge_publications set current_snapshot_id=$2 where store_id=$1', sid, snapshots[1])
    assert not await db.fetchval('select r_index_prunable($1,$2,0,1)', sid, ids['active'])
    print('PASS index retention age starts at retirement')
