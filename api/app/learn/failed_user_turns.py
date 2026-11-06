"""Bounded user-only recovery after semantic errors; no model output is retained here."""
from app.errors import ApiError
from app.learn.question_contexts import _lock_session

RECOVERABLE={'GENERAL_INVALID_PROPOSAL','GENERAL_VERIFICATION_REJECTED','GENERAL_MODEL_UNAVAILABLE','GENERAL_DEADLINE'}


async def validate_failed_request(conn,*,store_id:int,member_id:int,session_id:int,request_id:str,question:str):
    row=await conn.fetchrow('''select session_id,question from r_failed_user_turns
        where store_id=$1 and member_id=$2 and request_id=$3 and expires_at>clock_timestamp()''',store_id,member_id,request_id)
    if row and (row['session_id']!=session_id or row['question']!=question):
        raise ApiError(409,'IDEMPOTENCY_CONFLICT','같은 요청 키에 다른 본문을 사용할 수 없습니다.')


async def record_failed_turn(pool,*,store_id:int,member_id:int,session_id:int,request_id:str,question:str,error_code:str):
    if error_code not in RECOVERABLE:raise ValueError('not a recoverable semantic error')
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _lock_session(conn,store_id=store_id,member_id=member_id,session_id=session_id)
            await conn.execute('delete from r_failed_user_turns where store_id=$1 and expires_at<=clock_timestamp()',store_id)
            await validate_failed_request(conn,store_id=store_id,member_id=member_id,session_id=session_id,request_id=request_id,question=question)
            if await conn.fetchval('''select exists(select 1 from r_answer_receipts
                where store_id=$1 and member_id=$2 and request_id=$3)''',store_id,member_id,request_id):return
            await conn.execute('''insert into r_failed_user_turns(store_id,member_id,session_id,request_id,question,error_code)
                values($1,$2,$3,$4,$5,$6) on conflict(store_id,member_id,request_id) do nothing''',
                store_id,member_id,session_id,request_id,question,error_code)


async def failed_turns(conn,*,store_id:int,member_id:int,session_id:int,exclude_request_id:str|None=None):
    return await conn.fetch('''select f.failed_turn_id,f.question,f.created_at from r_failed_user_turns f
        where f.store_id=$1 and f.member_id=$2 and f.session_id=$3 and f.expires_at>clock_timestamp()
          and ($4::text is null or f.request_id<>$4)
          and not exists(select 1 from r_answer_receipts r where r.store_id=f.store_id and r.member_id=f.member_id and r.request_id=f.request_id)
        order by f.failed_turn_id desc limit 10''',store_id,member_id,session_id,exclude_request_id)


async def validate_failed_head(conn,*,store_id:int,member_id:int,session_id:int,request_id:str,expected_head:int):
    rows=await failed_turns(conn,store_id=store_id,member_id=member_id,session_id=session_id,exclude_request_id=request_id)
    head=rows[0]['failed_turn_id'] if rows else 0
    if type(expected_head) is not int or expected_head!=head:
        raise ApiError(409,'STALE_DIALOGUE','대화가 변경됐습니다. 최신 대화를 확인한 뒤 다시 질문해 주세요.',retryable=True)
