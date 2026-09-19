"""Run only inside the isolated schema-rebuild database after API fixtures exist."""
import asyncpg


async def verify(pool, admin, seed):
    store = seed['store_id']
    passed = 0
    def check(name, ok):
        nonlocal passed
        assert ok, name
        passed += 1
        print('PASS retention', name)
    ids = []
    for days in (31, 29):
        row = await admin.fetchval("""insert into r_answer_receipts(
            store_id,member_id,session_id,request_id,body_hash,original_question,resolved_query,
            context_snapshot,snapshot_id,knowledge_revision,user_message_id,buddy_message_id,
            pending_id,response,execution_metadata,created_at)
            select store_id,member_id,session_id,request_id||$2,body_hash,original_question,resolved_query,
            context_snapshot,snapshot_id,knowledge_revision,user_message_id,buddy_message_id,pending_id,response,
            '{"planner_version":"synthetic/v1","policy_receipt_id":"1"}'::jsonb,
            clock_timestamp()-make_interval(days=>$3)
            from r_answer_receipts where store_id=$1 order by receipt_id limit 1 returning receipt_id""",
            store, f':retain{days}', days)
        assert row is not None
        ids.append(row)
    original = await admin.fetchval('select original_question from r_answer_receipts where receipt_id=$1', ids[0])
    check('other store purge cannot touch these receipts', await admin.fetchval('select purge_r_execution_metadata($1)', 9223372036854775807) == 0)
    check('only expired metadata removed', await admin.fetchval('select purge_r_execution_metadata($1)', store) == 1)
    check('policy confirmation link retained', await admin.fetchval("select execution_metadata='{" + '"policy_receipt_id":"1"' + "}'::jsonb from r_answer_receipts where receipt_id=$1", ids[0]))
    check('fresh metadata retained', await admin.fetchval("select execution_metadata ? 'planner_version' from r_answer_receipts where receipt_id=$1", ids[1]))
    check('original question retained', await admin.fetchval('select original_question from r_answer_receipts where receipt_id=$1', ids[0]) == original)
    check('cleanup idempotent', await admin.fetchval('select purge_r_execution_metadata($1)', store) == 0)
    for sql in ("update r_answer_receipts set original_question='changed' where receipt_id=$1",
                "update r_answer_receipts set execution_metadata='{}'::jsonb where receipt_id=$1",
                "delete from r_answer_receipts where receipt_id=$1"):
        try:
            await admin.execute(sql, ids[1])
        except asyncpg.RaiseError:
            check('answer/fresh metadata remain immutable', True)
        else:
            raise AssertionError('immutable history changed')
    for role in ('anon', 'authenticated'):
        for sql in ('select * from r_answer_receipts', f'select purge_r_execution_metadata({store})'):
            async with pool.acquire() as conn:
                try:
                    async with conn.transaction():
                        await conn.execute(f'set local role {role}')
                        await conn.execute(sql)
                except asyncpg.InsufficientPrivilegeError:
                    check(role + ' cannot read or purge diagnostics', True)
                else:
                    raise AssertionError('browser role accessed diagnostics')
    print(f'Verified {passed} retention checks')
