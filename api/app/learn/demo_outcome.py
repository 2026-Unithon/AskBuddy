"""Minimal own-request demo diagnostics. No prompt, response text or provider ID is returned."""
import json
from app.contracts.hashing import digest
from app.errors import ApiError

async def outcome(conn, *, store_id, user_id, request_id):
    member=await conn.fetchval("""select member_id from store_members where store_id=$1
        and user_id=$2 and member_role='STAFF' and removed_at is null""",store_id,user_id)
    if member is None:raise ApiError(403,'FORBIDDEN','현재 매장의 직원만 조회할 수 있습니다.')
    op=digest(dict(member_id=member,request_id=request_id))
    ids=[]
    for n in (0,1):
        query='v2:'+op[7:]+':q'+str(n)
        ids.extend([query,*('general:'+digest(dict(call=query,phase=p))[7:] for p in ('proposal','verify'))])
    calls=await conn.fetch("""select stage,requested_model,status,error_code,latency_ms,
        (provider_request_id is not null or completion_tokens is not null) as provider_reply_observed
        from ai_usage_attempts where store_id=$1 and logical_call_id=any($2::text[])
        and operation_id=$3 and cost_purpose='PRODUCT' and mode='real' and evaluation_run_id is null
        order by started_at,usage_attempt_id""",store_id,ids,op)
    r=await conn.fetchrow("""select r.receipt_id,r.session_id,r.response->>'action' as action,
        r.execution_metadata,m.answer_source from r_answer_receipts r join chat_messages m
        on m.message_id=r.buddy_message_id and m.session_id=r.session_id
        where r.store_id=$1 and r.member_id=$2 and r.request_id=$3""",store_id,member,request_id)
    if not r and not calls:raise ApiError(404,'NOT_FOUND','이 요청의 기록이 없습니다.')
    meta=(r['execution_metadata'] if r else None) or {}
    if isinstance(meta,str):meta=json.loads(meta)
    semantic=meta.get('general_semantics') or {}
    return dict(store_id=store_id,session_id=r['session_id'] if r else None,receipt_id=r['receipt_id'] if r else None,
        action=r['action'] if r else None,answer_source=r['answer_source'] if r else None,
        semantic_status=semantic.get('status'),reason=semantic.get('reason') or semantic.get('reason_code'),
        semantic_phase=semantic.get('phase'),semantic_error_type=semantic.get('error_type'),
        retrieval_mode=meta.get('retrieval_mode'),calls=[dict(row) for row in calls])
