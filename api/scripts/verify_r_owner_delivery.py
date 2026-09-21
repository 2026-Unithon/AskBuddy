"""격리 실제 DB: 점주 원문·수정 CAS·원자 전달·outbox. W 모델은 호출하지 않는다."""
import asyncio
from unittest.mock import patch

from app.errors import ApiError
from app.learn.owner_delivery import submit_owner_answer
from app.learn.owner_handoff import claim_owner_event,heartbeat_owner_event,finish_owner_event,retry_owner_event
from app.contracts.publication import ApplyOwnerAnswerResult


async def verify(pool,admin,seed):
    passed=[]
    def check(name,ok):
        assert ok,name
        passed.append(name)
        print('PASS owner delivery',name)
    store_id=seed['store_id']
    # 앞선 HTTP 시나리오의 사건을 실제 인계 접점으로 처리하고 이 시나리오를 시작한다.
    while previous:=await claim_owner_event(pool,store_id=store_id):
        if not previous['stale']:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await finish_owner_event(conn,store_id=store_id,event_id=int(previous['event_id']),
                        claim_token=previous['claim_token'],result=ApplyOwnerAnswerResult(status='REVIEW'))
    pending=await admin.fetchval("select question_id from pending_questions where store_id=$1 and contract_version='v2' and status='WAITING' order by question_id desc limit 1",store_id)
    async def submit(key,answer='  원문\n225 ml  ',revision=0,member_id=None):
        return await submit_owner_answer(pool,store_id=store_id,member_id=member_id or seed['member_id'],
            question_id=pending,request_id=key,answer=answer,expected_revision=revision)
    before=await admin.fetchval('select count(*) from owner_answers')
    async def failure(*args,**kwargs):raise RuntimeError('injected notification failure')
    try:
        with patch('app.learn.owner_delivery.create_notification_event',failure):
            await submit('owner-rollback-key')
    except RuntimeError:pass
    else:raise AssertionError('expected rollback')
    check('notification failure rolls back original and pending',
        await admin.fetchval('select count(*) from owner_answers')==before and
        await admin.fetchval('select status from pending_questions where store_id=$1 and question_id=$2',store_id,pending)=='WAITING')
    first,repeat=await asyncio.gather(submit('owner-first-key'),submit('owner-first-key'))
    check('concurrent request replays one answer',first==repeat and await admin.fetchval('select count(*) from owner_answers')==before+1)
    aid=int(first['owner_answer_id'])
    check('raw whitespace preserved',await admin.fetchval('select answer_text from owner_answers where answer_id=$1',aid)=='  원문\n225 ml  ')
    check('outbox contains IDs only',await admin.fetchval("select count(*) from outbox_events where store_id=$1 and owner_answer_id=$2 and event_type='OWNER_ANSWER_SUBMITTED'",store_id,aid)==1)
    check('knowledge remains PENDING',await admin.fetchval('select status from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2',store_id,aid)=='PENDING')
    check('exact pending sessions delivered',await admin.fetchval('select count(*) from r_owner_answer_deliveries where store_id=$1 and owner_answer_id=$2',store_id,aid)==first['delivered_sessions']>0)
    for key,answer,rev in [('owner-first-key','다른 원문',0),('owner-stale-key','수정',0)]:
        try:await submit(key,answer,rev)
        except ApiError as exc:check('conflicting request/revision rejected',exc.status_code==409)
        else:raise AssertionError('conflict accepted')
    results=await asyncio.gather(submit('owner-edit-one','수정 1',1),submit('owner-edit-two','수정 2',1),return_exceptions=True)
    check('concurrent edits only one wins',sum(isinstance(r,dict) for r in results)==1 and sum(isinstance(r,ApiError) for r in results)==1)
    try:await admin.execute('update owner_answers set answer_text=$1 where answer_id=$2','변조',aid)
    except Exception as exc:check('original immutable in DB','immutable' in str(exc))
    else:raise AssertionError('mutable original')
    check('correction keeps original',await admin.fetchval('select answer_text from owner_answers where answer_id=$1',aid)=='  원문\n225 ml  ')
    try:await submit('owner-invalid-member',member_id=999999)
    except ApiError as exc:check('non owner rejected',exc.status_code==403)
    else:raise AssertionError('missing owner accepted')
    old=await claim_owner_event(pool,store_id=store_id)
    check('superseded event skipped before W apply',old['stale'] and int(old['owner_answer_id'])==aid)
    claims=await asyncio.gather(claim_owner_event(pool,store_id=store_id),claim_owner_event(pool,store_id=store_id))
    claim=next(c for c in claims if c)
    check('concurrent workers claim once',sum(c is not None for c in claims)==1)
    check('heartbeat requires current claim',not await heartbeat_owner_event(pool,store_id=store_id,event_id=int(claim['event_id']),claim_token='wrong'))
    check('current claim heartbeat succeeds',await heartbeat_owner_event(pool,store_id=store_id,event_id=int(claim['event_id']),claim_token=claim['claim_token']))
    await admin.execute("update outbox_leases set leased_until=clock_timestamp()-interval '1 second' where store_id=$1 and event_id=$2",store_id,int(claim['event_id']))
    newer=await claim_owner_event(pool,store_id=store_id)
    check('expired claim recovered as next attempt',newer['attempt']==2 and newer['claim_token']!=claim['claim_token'])
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await finish_owner_event(conn,store_id=store_id,event_id=int(claim['event_id']),claim_token=claim['claim_token'],result=ApplyOwnerAnswerResult(status='REVIEW'))
        except ApiError as exc:check('old worker fenced',exc.status_code==409)
        else:raise AssertionError('old worker committed')
        async with conn.transaction():
            await finish_owner_event(conn,store_id=store_id,event_id=int(newer['event_id']),claim_token=newer['claim_token'],result=ApplyOwnerAnswerResult(status='REVIEW'))
    check('knowledge state independent of delivered original',await admin.fetchval('select status from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2',store_id,int(newer['owner_answer_id']))=='REVIEW')
    check('completed event not redelivered',await claim_owner_event(pool,store_id=store_id) is None)
    session_id=await admin.fetchval('select session_id from r_answer_receipts where store_id=$1 and pending_id=$2 limit 1',store_id,pending)
    from app.learn.question_contexts import _lock_session
    async with pool.acquire() as held:
        async with held.transaction():
            await _lock_session(held,store_id=store_id,member_id=seed['member_id'],session_id=session_id)
            reply=await asyncio.wait_for(submit('owner-session-lock','수정 3',2),timeout=3)
            check('session context lock permits owner message FK',reply['revision']==3)
    failed=ApplyOwnerAnswerResult(status='FAILED',retryable=True,error=dict(code='MODEL_UNAVAILABLE',
        message='synthetic outage',retryable=True,request_id='synthetic-outage'))
    for attempt_no in range(1,11):
        claimed=await claim_owner_event(pool,store_id=store_id)
        check('retry attempt bounded',claimed is not None and claimed['attempt']==attempt_no)
        event_id=int(claimed['event_id'])
        async with pool.acquire() as conn:
            async with conn.transaction():
                await finish_owner_event(conn,store_id=store_id,event_id=event_id,
                    claim_token=claimed['claim_token'],result=failed)
        check('backoff prevents immediate retry',await claim_owner_event(pool,store_id=store_id) is None)
        await admin.execute("""update outbox_leases set leased_until=clock_timestamp()-interval '1 second'
            where store_id=$1 and consumer='W_OWNER_ANSWER_V2' and event_id=$2""",store_id,event_id)
    check('no eleventh automatic attempt',await claim_owner_event(pool,store_id=store_id) is None)
    async def retry():
        return await retry_owner_event(pool,store_id=store_id,member_id=seed['member_id'],event_id=event_id,
            request_id='synthetic-manual-retry',reason='합성 공급자 복구')
    one,two=await asyncio.gather(retry(),retry())
    check('manual retry idempotent on same event',one==two and one['previous_attempts']==10)
    claimed=await claim_owner_event(pool,store_id=store_id)
    check('manual retry restarts bounded cycle with fencing',int(claimed['event_id'])==event_id and claimed['attempt']==1)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await finish_owner_event(conn,store_id=store_id,event_id=event_id,
                claim_token=claimed['claim_token'],result=ApplyOwnerAnswerResult(status='REVIEW'))
    from app.learn.faq import list_faqs
    faqs=await list_faqs(admin,store_id,min_questions=1,limit=100)
    check('FAQ legacy and v2 current-approval query executes',isinstance(faqs,list))
    # Exercise the real R receiver with a synthetic W completion and existing approved index.
    from app.reg.hybrid import read_current_index
    snapshot,_,_=await read_current_index(admin,store_id=store_id)
    card=snapshot.cards[0]
    reply=await submit('owner-published-roundtrip','합성 지식 반영',3)
    claimed=await claim_owner_event(pool,store_id=store_id)
    completion=dict(store_id=store_id,event_id=int(claimed['event_id']),claim_token=claimed['claim_token'])
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await finish_owner_event(conn,**completion,result=ApplyOwnerAnswerResult(
                    status='PUBLISHED',card_id=card.card_id,knowledge_revision='999999'))
    except ApiError:check('unpublished W revision cannot complete delivery',True)
    else:raise AssertionError('fabricated publication accepted')
    check('invalid completion leaves knowledge pending',await admin.fetchval(
        'select status from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2',
        store_id,int(reply['owner_answer_id']))=='PENDING')
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                with patch('app.learn.owner_publication.create_notification_event',side_effect=RuntimeError('synthetic failure')):
                    await finish_owner_event(conn,**completion,result=ApplyOwnerAnswerResult(
                        status='PUBLISHED',card_id=card.card_id,knowledge_revision=snapshot.knowledge_revision))
    except RuntimeError:pass
    else:raise AssertionError('notification failure was not injected')
    check('completion notification failure rolls back state and consumption',await admin.fetchval(
        "select status from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2",
        store_id,int(reply['owner_answer_id']))=='PENDING' and not await admin.fetchval(
        "select exists(select 1 from outbox_consumptions where store_id=$1 and event_id=$2 and consumer='W_OWNER_ANSWER_V2')",
        store_id,completion['event_id']))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await finish_owner_event(conn,**completion,result=ApplyOwnerAnswerResult(
                status='PUBLISHED',card_id=card.card_id,knowledge_revision=snapshot.knowledge_revision))
    check('completion pins published card version',await admin.fetchval(
        "select result->>'published_card_version_id' from r_owner_knowledge_states where store_id=$1 and owner_answer_id=$2",
        store_id,int(reply['owner_answer_id']))==card.card_version_id)
    check('knowledge completion creates durable recipient notification',await admin.fetchval(
        "select count(*) from notification_events where store_id=$1 and aggregate_id=$2 and dedupe_key like 'r-knowledge-ready:%'",
        store_id,int(reply['owner_answer_id']))>0)
    check('published completion consumed once',await claim_owner_event(pool,store_id=store_id) is None)
    from app.learn.faq import v2_faq_rows
    category=await admin.fetchval("insert into task_categories(store_id,category_name) values($1,'합성 왕복') returning category_id",store_id)
    await admin.execute('update knowledge_cards set category_id=$3 where store_id=$1 and card_id=$2',store_id,int(card.card_id),category)
    receipt_ids={str(r['receipt_id']) for r in await admin.fetch(
        'select receipt_id from r_answer_receipts where store_id=$1 and pending_id=$2',store_id,pending)}
    rows=await v2_faq_rows(admin,store_id=store_id)
    check('published owner answer enters FAQ through exact card version',bool(receipt_ids) and receipt_ids <= {str(r['receipt_id']) for r in rows})
    # Roll back the synthetic card change after checking later versions cannot inherit the old answer.
    async with admin.transaction():
        await admin.execute('update knowledge_cards set published_version_id=null where store_id=$1 and card_id=$2',store_id,int(card.card_id))
        rows=await v2_faq_rows(admin,store_id=store_id)
        check('withdrawn card removes owner FAQ association',not receipt_ids & {str(r['receipt_id']) for r in rows})
        await admin.execute('update knowledge_cards set published_version_id=$3 where store_id=$1 and card_id=$2',store_id,int(card.card_id),int(card.card_version_id))
    print(f'Verified {len(passed)} owner delivery checks')
