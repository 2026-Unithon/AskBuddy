"""W OWNER_ANSWER 인계용 durable claim/heartbeat/완료 접점.

W는 claim 뒤 DB 연결 없이 작업하고, 발행 transaction 안에서 finish를 호출한다.
finish 실패를 삼키면 안 된다. 같은 transaction 전체 rollback으로 오래된 발행을 막는다.
"""
from uuid import uuid4
import json

from app.contracts.publication import ApplyOwnerAnswerResult
from app.errors import ApiError
from app.contracts.errors import ERROR_TABLE
from app.contracts.hashing import digest
from app.learn.owner_delivery import require_owner
from app.notifications.service import create_notification_event

CONSUMER='W_OWNER_ANSWER_V2'
MAX_ATTEMPTS=10
HEARTBEAT_SECONDS=20


def retry_delay(attempt:int) -> int:
    if type(attempt) is not int or attempt<1:raise ValueError('positive attempt required')
    return min(60,2**min(attempt,6))


def should_retry(result:ApplyOwnerAnswerResult,attempt:int) -> bool:
    return (result.status=='FAILED' and result.retryable and result.error is not None
            and ERROR_TABLE[result.error.code][1] and attempt<MAX_ATTEMPTS)


async def _terminal(conn,*,store_id:int,event_id:int,owner_answer_id:int,reason:str,failure_key:str):
    await conn.execute("""update outbox_leases set status='FAILED',last_error=$4,updated_at=now()
        where store_id=$1 and consumer=$2 and event_id=$3""",store_id,CONSUMER,event_id,'TERMINAL:'+reason)
    await conn.execute("""update r_owner_knowledge_states set status='FAILED',updated_at=now()
        where store_id=$1 and owner_answer_id=$2""",store_id,owner_answer_id)
    owner=await conn.fetchval('select owner_id from stores where store_id=$1',store_id)
    if owner is not None:
        # Durable owner-facing operations alert; no private answer in the message.
        await create_notification_event(conn,store_id=store_id,recipient_user_id=owner,
            event_type='OWNER_ANSWER',aggregate_type='OWNER_ANSWER',aggregate_id=owner_answer_id,
            dedupe_key=f'r-handoff-failed:{store_id}:{event_id}:{failure_key}',title='지식 반영을 확인해 주세요',
            body='점주 답변 전달과 별개로 지식 반영이 중단됐습니다. 실패 원인을 확인한 뒤 재처리할 수 있습니다.',
            destination='/owner/questions/v2')


async def claim_owner_event(pool, *, store_id:int) -> dict|None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            event=await conn.fetchrow("""select e.event_id,e.owner_answer_id,r.question_id,r.revision_no,
                    coalesce(l.attempts,0) as attempts,l.leased_by
                from outbox_events e join r_owner_answer_revisions r
                  on r.store_id=e.store_id and r.owner_answer_id=e.owner_answer_id
                left join outbox_consumptions c on c.store_id=e.store_id and c.event_id=e.event_id and c.consumer=$2
                left join outbox_leases l on l.store_id=e.store_id and l.event_id=e.event_id and l.consumer=$2
                where e.store_id=$1 and e.event_type='OWNER_ANSWER_SUBMITTED' and c.event_id is null
                  and (l.event_id is null or l.leased_until<=clock_timestamp())
                  and (l.last_error is null or l.last_error not like 'TERMINAL:%')
                order by e.event_id for update of e skip locked limit 1""",store_id,CONSUMER)
            if event is None:return None
            latest=await conn.fetchval("""select max(revision_no) from r_owner_answer_revisions
                where store_id=$1 and question_id=$2""",store_id,event['question_id'])
            if latest!=event['revision_no']:
                await conn.execute("""insert into outbox_consumptions(store_id,consumer,event_id,result)
                    values($1,$2,$3,'STALE')""",store_id,CONSUMER,event['event_id'])
                return dict(event_id=str(event['event_id']),owner_answer_id=str(event['owner_answer_id']),stale=True)
            if event['attempts']>=MAX_ATTEMPTS:
                await _terminal(conn,store_id=store_id,event_id=event['event_id'],
                    owner_answer_id=event['owner_answer_id'],reason='RETRY_EXHAUSTED',failure_key=event['leased_by'])
                return None
            token=uuid4().hex
            attempts=await conn.fetchval("""insert into outbox_leases
                (store_id,consumer,event_id,leased_by,leased_until,attempts)
                values($1,$2,$3,$4,clock_timestamp()+interval '60 seconds',1)
                on conflict(store_id,consumer,event_id) do update set leased_by=excluded.leased_by,
                  leased_until=excluded.leased_until,attempts=outbox_leases.attempts+1,status='CLAIMED',last_error=null,updated_at=now()
                returning attempts""",store_id,CONSUMER,event['event_id'],token)
            return dict(event_id=str(event['event_id']),owner_answer_id=str(event['owner_answer_id']),
                        claim_token=token,attempt=attempts,stale=False)


async def heartbeat_owner_event(pool, *, store_id:int,event_id:int,claim_token:str) -> bool:
    async with pool.acquire() as conn:
        return bool(await conn.fetchval("""update outbox_leases set leased_until=clock_timestamp()+interval '60 seconds',updated_at=now()
            where store_id=$1 and consumer=$2 and event_id=$3 and leased_by=$4 and status='CLAIMED'
              and leased_until>clock_timestamp() returning event_id""",store_id,CONSUMER,event_id,claim_token))


async def finish_owner_event(conn, *, store_id:int,event_id:int,claim_token:str,result:ApplyOwnerAnswerResult) -> None:
    if not conn.is_in_transaction():raise ValueError('W publication and finish require one transaction')
    result=ApplyOwnerAnswerResult.model_validate(result.model_dump())
    event=await conn.fetchrow("""select e.owner_answer_id,r.question_id,r.revision_no
        from outbox_events e join r_owner_answer_revisions r on r.store_id=e.store_id and r.owner_answer_id=e.owner_answer_id
        where e.store_id=$1 and e.event_id=$2 and e.event_type='OWNER_ANSWER_SUBMITTED'""",store_id,event_id)
    if event is None:raise ApiError(404,'NOT_FOUND','인계 사건을 찾을 수 없습니다.')
    await conn.fetchval("select question_id from pending_questions where store_id=$1 and question_id=$2 for update",
                        store_id,event['question_id'])
    lease=await conn.fetchval("""select attempts from outbox_leases where store_id=$1 and consumer=$2 and event_id=$3
        and leased_by=$4 and status='CLAIMED' and leased_until>clock_timestamp() for update""",store_id,CONSUMER,event_id,claim_token)
    if lease is None:raise ApiError(409,'IDEMPOTENCY_CONFLICT','인계 작업의 권한이 만료됐습니다.')
    latest=await conn.fetchval("select max(revision_no) from r_owner_answer_revisions where store_id=$1 and question_id=$2",
                              store_id,event['question_id'])
    if latest!=event['revision_no']:raise ApiError(409,'IDEMPOTENCY_CONFLICT','새 점주 답변이 있습니다. 이전 작업을 되돌려야 합니다.')
    await conn.execute("""update r_owner_knowledge_states set status=$3,result=$4::jsonb,updated_at=now()
        where store_id=$1 and owner_answer_id=$2""",store_id,event['owner_answer_id'],result.status,result.model_dump_json())
    retry=should_retry(result,lease)
    if result.status=='FAILED' and not retry:
        await _terminal(conn,store_id=store_id,event_id=event_id,owner_answer_id=event['owner_answer_id'],
            reason='RETRY_EXHAUSTED' if lease>=MAX_ATTEMPTS else result.error.code,failure_key=claim_token)
        return
    await conn.execute("""update outbox_leases set status=$5,
        leased_until=clock_timestamp()+$6*interval '1 second',last_error=$7,updated_at=now()
        where store_id=$1 and consumer=$2 and event_id=$3 and leased_by=$4""",store_id,CONSUMER,event_id,claim_token,
        'FAILED' if retry else 'DONE',retry_delay(lease),result.error.code if retry else None)
    if result.status!='FAILED':
        await conn.execute("""insert into outbox_consumptions(store_id,consumer,event_id,result)
            values($1,$2,$3,$4)""",store_id,CONSUMER,event_id,'SKIPPED' if result.status=='FAILED' else 'APPLIED')


async def retry_owner_event(pool,*,store_id:int,member_id:int,event_id:int,request_id:str,reason:str) -> dict:
    """Explicit owner retry of the same business event, with durable audit/idempotency."""
    if not 8<=len(request_id)<=80 or not reason.strip() or len(reason)>300:
        raise ApiError(422,'INVALID_CONTRACT','재처리 사유와 요청 키가 필요합니다.')
    body_hash=digest(dict(event_id=event_id,reason=reason))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_owner(conn,store_id=store_id,member_id=member_id)
            await conn.execute('select pg_advisory_xact_lock(hashtextextended($1,0))',
                f'r:retry:{store_id}:{member_id}:{request_id}')
            saved=await conn.fetchrow("""select body_hash,response from operations where store_id=$1
                and member_id=$2 and operation='R_OWNER_RETRY' and idempotency_key=$3""",store_id,member_id,request_id)
            if saved:
                if saved['body_hash']!=body_hash:raise ApiError(409,'IDEMPOTENCY_CONFLICT','요청 키가 이미 사용됐습니다.')
                return json.loads(saved['response']) if isinstance(saved['response'],str) else saved['response']
            event=await conn.fetchrow("""select e.owner_answer_id,r.question_id,r.revision_no from outbox_events e
                join r_owner_answer_revisions r on r.store_id=e.store_id and r.owner_answer_id=e.owner_answer_id
                where e.store_id=$1 and e.event_id=$2 and e.event_type='OWNER_ANSWER_SUBMITTED' for update of e""",store_id,event_id)
            if event is None:raise ApiError(404,'NOT_FOUND','인계 사건을 찾을 수 없습니다.')
            await conn.fetchval('select question_id from pending_questions where store_id=$1 and question_id=$2 for update',
                store_id,event['question_id'])
            latest=await conn.fetchval('select max(revision_no) from r_owner_answer_revisions where store_id=$1 and question_id=$2',
                store_id,event['question_id'])
            lease=await conn.fetchrow("""select attempts,last_error from outbox_leases where store_id=$1
                and consumer=$2 and event_id=$3 and status='FAILED' for update""",store_id,CONSUMER,event_id)
            if (not lease or not (lease['last_error'] or '').startswith('TERMINAL:') or latest!=event['revision_no']):
                raise ApiError(409,'IDEMPOTENCY_CONFLICT','현재 답변의 종료된 실패만 재처리할 수 있습니다.')
            response=dict(event_id=str(event_id),previous_attempts=lease['attempts'],status='PENDING')
            await conn.execute("""insert into operations(store_id,member_id,operation,idempotency_key,body_hash,status,response)
                values($1,$2,'R_OWNER_RETRY',$3,$4,'SUCCEEDED',$5::jsonb)""",store_id,member_id,request_id,body_hash,
                json.dumps(dict(response,reason=reason)))
            await conn.execute("""update outbox_leases set attempts=0,last_error=null,leased_until=clock_timestamp(),
                leased_by=$4,updated_at=now() where store_id=$1 and consumer=$2 and event_id=$3""",store_id,CONSUMER,event_id,uuid4().hex)
            await conn.execute("""update r_owner_knowledge_states set status='PENDING',updated_at=now()
                where store_id=$1 and owner_answer_id=$2""",store_id,event['owner_answer_id'])
            return dict(response,reason=reason)
