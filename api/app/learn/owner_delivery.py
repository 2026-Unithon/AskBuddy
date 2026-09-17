"""점주 원문을 원자 저장·전달한다. W의 지식 발행을 성공으로 추정하지 않는다."""
from __future__ import annotations

import json

from app.contracts.hashing import digest
from app.errors import ApiError
from app.notifications.service import create_notification_event


async def require_owner(conn, *, store_id: int, member_id: int) -> int:
    user_id = await conn.fetchval("""select user_id from store_members
        where store_id=$1 and member_id=$2 and member_role='OWNER' for share""", store_id, member_id)
    if user_id is None:
        raise ApiError(403, "FORBIDDEN", "현재 매장 점주 권한이 필요합니다.")
    return user_id


async def submit_owner_answer(pool, *, store_id: int, member_id: int, question_id: int,
                              request_id: str, answer: str, expected_revision: int) -> dict:
    if not 8 <= len(request_id) <= 80 or not answer.strip() or len(answer) > 10000 or expected_revision < 0:
        raise ApiError(422, "INVALID_CONTRACT", "답변과 요청 정보를 확인해 주세요.")
    body_hash = digest(dict(question_id=question_id, answer=answer, expected_revision=expected_revision))
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await require_owner(conn, store_id=store_id, member_id=member_id)
            await conn.execute("select pg_advisory_xact_lock(hashtextextended($1,0))",
                               f"r:owner:{store_id}:{member_id}:{request_id}")
            saved = await conn.fetchrow("""select body_hash,response from operations
                where store_id=$1 and member_id=$2 and operation='R_OWNER_ANSWER' and idempotency_key=$3""",
                store_id, member_id, request_id)
            if saved:
                if saved['body_hash'] != body_hash:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "같은 요청 키에 다른 답변을 사용할 수 없습니다.")
                return json.loads(saved['response']) if isinstance(saved['response'], str) else saved['response']
            pending = await conn.fetchrow("""select question_id,status from pending_questions
                where store_id=$1 and question_id=$2 and contract_version='v2' for update""", store_id, question_id)
            if pending is None:
                raise ApiError(404, "NOT_FOUND", "질문을 찾을 수 없습니다.")
            latest = await conn.fetchrow("""select owner_answer_id,revision_no from r_owner_answer_revisions
                where store_id=$1 and question_id=$2 order by revision_no desc limit 1""", store_id, question_id)
            if (latest['revision_no'] if latest else 0) != expected_revision:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "다른 답변이 먼저 저장됐습니다. 최신 답변을 확인해 주세요.")
            if latest is None and pending['status'] != 'WAITING':
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "질문의 처리 상태가 변경됐습니다.")
            answer_id = await conn.fetchval("""insert into owner_answers(question_id,answered_by,answer_text)
                values($1,$2,$3) returning answer_id""", question_id, user_id, answer)
            await conn.execute("""insert into r_owner_answer_revisions
                (store_id,question_id,owner_answer_id,revision_no,supersedes_answer_id) values($1,$2,$3,$4,$5)""",
                store_id, question_id, answer_id, expected_revision+1, latest['owner_answer_id'] if latest else None)
            await conn.execute("insert into r_owner_knowledge_states(store_id,owner_answer_id) values($1,$2)", store_id, answer_id)
            # 같은 pending의 occurrence만 전파한다. 문장이 같다는 이유로 다른 문맥을 합치지 않는다.
            recipients = await conn.fetch("""select distinct r.member_id,r.session_id,m.user_id
                from r_answer_receipts r join store_members m on m.store_id=r.store_id and m.member_id=r.member_id
                where r.store_id=$1 and r.pending_id=$2 order by r.member_id,r.session_id""", store_id, question_id)
            for recipient in recipients:
                # 탈퇴와 경쟁하면 해당 저장 전체가 rollback된다. 권한 없는 수신을 성공으로 세지 않는다.
                member = await conn.fetchval("select member_id from store_members where store_id=$1 and member_id=$2 for share",
                                             store_id, recipient['member_id'])
                if member is None:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "질문자의 매장 권한이 변경됐습니다.")
                message_id = await conn.fetchval("""insert into chat_messages
                    (session_id,sender_type,content,answer_type,answer_source,grounding_status,owner_answer_id)
                    values($1,'BUDDY',$2,'ANSWERED','OWNER_ANSWER','NOT_APPLICABLE',$3) returning message_id""",
                    recipient['session_id'], answer, answer_id)
                await conn.execute("""insert into r_owner_answer_deliveries
                    (store_id,owner_answer_id,member_id,session_id,message_id) values($1,$2,$3,$4,$5)""",
                    store_id, answer_id, member, recipient['session_id'], message_id)
                await create_notification_event(conn, store_id=store_id, recipient_user_id=recipient['user_id'],
                    event_type="OWNER_ANSWER", aggregate_type="OWNER_ANSWER", aggregate_id=answer_id,
                    dedupe_key=f"owner-answer:{store_id}:{answer_id}", title="사장님 답변이 도착했어요",
                    body="앱에서 질문과 답변을 확인해 주세요.",
                    destination=f"/staff/chat/v2?session_id={recipient['session_id']}")
            await conn.execute("update pending_questions set status='ANSWERED' where store_id=$1 and question_id=$2", store_id, question_id)
            event_id = await conn.fetchval("""insert into outbox_events
                (store_id,event_type,aggregate_id,owner_answer_id) values($1,'OWNER_ANSWER_SUBMITTED',$2,$2) returning event_id""",
                store_id, answer_id)
            result = dict(contract_version="v2", owner_answer_id=str(answer_id), revision=expected_revision+1,
                          event_id=str(event_id), knowledge_status="PENDING", delivered_sessions=len(recipients))
            await conn.execute("""insert into operations
                (store_id,member_id,operation,idempotency_key,body_hash,status,response,finished_at)
                values($1,$2,'R_OWNER_ANSWER',$3,$4,'SUCCEEDED',$5::jsonb,now())""",
                store_id, member_id, request_id, body_hash, json.dumps(result))
            return result
