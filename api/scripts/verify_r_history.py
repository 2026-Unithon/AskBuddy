"""격리 DB의 실제 인증 API로 최신 이력·세션 대기 요약을 검증한다."""
from contextlib import asynccontextmanager
from unittest.mock import patch


async def verify(client, admin, seed, headers, foreign_headers, check):
    async def session(key):
        response = await client.post('/learn/v2/sessions', headers=headers, json={'request_id': key})
        assert response.status_code == 200, response.text
        return response.json()['session_id']

    sid = await session('history-pagination-session')
    ids = []
    for count in (99, 100, 101, 200, 201):
        for number in range(len(ids), count):
            ids.append(str(await admin.fetchval("""insert into chat_messages(session_id,sender_type,content)
                values($1,'USER',$2) returning message_id""", int(sid), f'합성 기록 {number+1}')))
        response = await client.get(f'/learn/v2/sessions/{sid}/history?latest=true', headers=headers)
        assert response.status_code == 200, response.text
        page = response.json()
        check(f'latest history {count} returns ordered newest page', [m['message_id'] for m in page['messages']] == ids[-100:])
        check(f'latest history {count} exact cursor', page['next_before'] == (ids[-100] if count > 100 else None))
        check(f'plain history {count} has no pending work', not page['has_pending_updates'])
        collected = page['messages']
        while page['next_before']:
            page = (await client.get(f"/learn/v2/sessions/{sid}/history?latest=true&before={page['next_before']}", headers=headers)).json()
            collected = page['messages'] + collected
        check(f'older pages {count} preserve every message once', [m['message_id'] for m in collected] == ids)
    legacy = (await client.get(f'/learn/v2/sessions/{sid}/history?limit=100', headers=headers)).json()
    check('legacy forward history remains compatible', [m['message_id'] for m in legacy['messages']] == ids[:100] and legacy['next_after'] == ids[99])
    tail = (await client.get(f'/learn/v2/sessions/{sid}/history?after={ids[100]}', headers=headers)).json()
    check('exact forward page has no phantom cursor', len(tail['messages']) == 100 and tail['next_after'] is None)
    for query in ('latest=true&after=1', 'before=1', 'latest=true&before=0', 'limit=101'):
        bad = await client.get(f'/learn/v2/sessions/{sid}/history?{query}', headers=headers)
        check('invalid history cursor rejected '+query, bad.status_code == 422)
    foreign = await client.get(f'/learn/v2/sessions/{sid}/history?latest=true', headers=foreign_headers)
    check('latest history summary cannot cross member', foreign.status_code == 404)

    waiting = await session('history-waiting-session')
    async def ask(key, question, **extra):
        response = await client.post('/learn/v2/chat', headers=headers, json=dict(
            session_id=waiting, request_id=key, question=question, **extra))
        assert response.status_code == 200, response.text
        return response

    pending = []
    for number in range(2):
        question = f'알레르기 확인 {number}'
        policy = await ask(f'history-policy-{number}', question)
        result = await ask(f'history-confirm-{number}', question, policy_receipt_id=policy.headers['x-answer-receipt-id'])
        pending.append(result.json()['pending_id'])
    # 이전 페이지의 두 이관 뒤에 완료 메시지가 있어도 요약은 세션 전체를 본다.
    await ask('history-last-complete', '개인정보 알려줘')
    async def status():
        result = await client.get(f'/learn/v2/sessions/{waiting}/history?latest=true&limit=1', headers=headers)
        assert result.status_code == 200, result.text
        return result.json()['has_pending_updates']
    check('earlier pending survives later completed response and pagination', await status())
    answers = []
    for number, pid in enumerate(pending):
        result = await client.post(f'/learn/v2/pending/{pid}/answers', headers=headers,
            json=dict(request_id=f'history-owner-{number}', answer='합성 점주 원문', expected_revision=0))
        assert result.status_code == 200, result.text
        answers.append(result.json())
        await admin.execute("update r_owner_knowledge_states set status='PUBLISHED' where store_id=$1 and owner_answer_id=$2",
                            seed['store_id'], int(answers[-1]['owner_answer_id']))
        check('remaining pending keeps polling' if number == 0 else 'all resolved stops polling', await status() == (number == 0))
    first = answers[0]
    aid = int(first['owner_answer_id'])
    async def state(value):
        await admin.execute('update r_owner_knowledge_states set status=$3 where store_id=$1 and owner_answer_id=$2', seed['store_id'], aid, value)
    for value, expected in [('PENDING', True), ('REVIEW', True), ('LINKED', False), ('FAILED', False)]:
        await state(value)
        check('knowledge state '+value, await status() == expected)
    await admin.execute("""insert into outbox_leases(store_id,consumer,event_id,leased_by,leased_until,status,last_error)
        values($1,'W_OWNER_ANSWER_V2',$2,'synthetic-history',clock_timestamp()+interval '60 seconds','FAILED','TEMPORARY')""",
        seed['store_id'], int(first['event_id']))
    check('retryable knowledge failure keeps polling', await status())
    await admin.execute("update outbox_leases set last_error='TERMINAL:RETRY_EXHAUSTED' where store_id=$1 and event_id=$2",
                        seed['store_id'], int(first['event_id']))
    check('terminal knowledge failure stops polling', not await status())
    await state('PENDING')
    revision = await client.post(f'/learn/v2/pending/{pending[0]}/answers', headers=headers,
        json=dict(request_id='history-owner-revision', answer='합성 정정 원문', expected_revision=1))
    assert revision.status_code == 200, revision.text
    await admin.execute("update r_owner_knowledge_states set status='PUBLISHED' where store_id=$1 and owner_answer_id=$2",
                        seed['store_id'], int(revision.json()['owner_answer_id']))
    check('superseded pending revision does not poll forever', not await status())
    # 메시지를 읽은 직후 공개 완료가 커밋되는 경합을 실제 별도 연결로 주입한다.
    from app.learn import v2_router
    pool = v2_router.get_pool()
    current_aid = int(revision.json()['owner_answer_id'])
    await admin.execute("update r_owner_knowledge_states set status='PENDING' where store_id=$1 and owner_answer_id=$2",
                        seed['store_id'], current_aid)
    injected = False

    class Connection:
        def __init__(self, conn): self.conn = conn
        def __getattr__(self, name): return getattr(self.conn, name)
        async def fetch(self, sql, *args):
            nonlocal injected
            rows = await self.conn.fetch(sql, *args)
            if not injected and 'select m.message_id' in sql:
                injected = True
                await admin.execute("update r_owner_knowledge_states set status='PUBLISHED' where store_id=$1 and owner_answer_id=$2",
                                    seed['store_id'], current_aid)
            return rows

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            async with pool.acquire() as conn: yield Connection(conn)

    with patch.object(v2_router, 'get_pool', return_value=Pool()):
        raced = await client.get(f'/learn/v2/sessions/{waiting}/history?latest=true', headers=headers)
    assert raced.status_code == 200, raced.text
    data = raced.json()
    observed = next(m for m in data['messages'] if m['owner_answer_id'] == str(current_aid))
    check('concurrent publication keeps messages and pending summary in one snapshot',
          injected and observed['knowledge_status'] == 'PENDING' and data['has_pending_updates'])
    check('next read observes publication and stops polling', not await status())
    empty = (await client.get(f'/learn/v2/sessions/{sid}/history?latest=true', headers=headers)).json()
    check('other session pending never leaks into summary', not empty['has_pending_updates'])
