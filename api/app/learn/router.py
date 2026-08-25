"""관호 (feat/db) — 미답변 순환 진입점.

miss 판정은 POST /reg/retrieve 가 하고, 기록은 여기 POST /pending 이 한다 (선택 B).
store_id·member_id 는 JWT 에서만 해석한다 (불변식 4).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import CurrentStoreId, CurrentUserId, Db

router = APIRouter()


class CreatePendingRequest(BaseModel):
    question_text: str = Field(min_length=1, max_length=500)
    miss_reason: str = Field(pattern="^(no_match|intent_mismatch|no_anchor)$")
    message_id: int | None = None


async def _member_id(db: Db, store_id: int, user_id: int) -> int:
    row = await db.fetchrow(
        """
        select member_id
        from store_members
        where store_id = $1 and user_id = $2
        """,
        store_id,
        user_id,
    )
    if not row:
        raise HTTPException(403, "not a member of this store")
    return int(row["member_id"])


@router.post("/pending")
async def create_pending(
    req: CreatePendingRequest,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
):
    """채팅 miss 직후 호출. pending_questions 에 WAITING 행을 남긴다."""
    member_id = await _member_id(db, store_id, user_id)
    question = req.question_text.strip()
    if not question:
        raise HTTPException(400, "question_text is empty")

    if req.message_id is not None:
        msg = await db.fetchrow(
            """
            select m.message_id
            from chat_messages m
            join chat_sessions s on s.session_id = m.session_id
            where m.message_id = $1
              and s.store_id = $2
            """,
            req.message_id,
            store_id,
        )
        if not msg:
            raise HTTPException(404, "message not found in this store")

    row = await db.fetchrow(
        """
        insert into pending_questions (
          store_id, member_id, message_id, question_text, miss_reason, status
        )
        values ($1, $2, $3, $4, $5, 'WAITING')
        returning question_id, status, created_at, miss_reason
        """,
        store_id,
        member_id,
        req.message_id,
        question,
        req.miss_reason,
    )
    return {
        "question_id": int(row["question_id"]),
        "status": row["status"],
        "miss_reason": row["miss_reason"],
        "question_text": question,
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/pending")
async def list_pending(
    db: Db,
    store_id: CurrentStoreId,
    status: str = Query(default="WAITING", pattern="^(WAITING|ANSWERED)$"),
):
    """점주 대시보드 폴링용. JWT store_id 의 pending 만 반환한다."""
    rows = await db.fetch(
        """
        select
          q.question_id,
          q.question_text,
          q.miss_reason,
          q.status,
          q.created_at,
          q.member_id,
          u.name as asked_by
        from pending_questions q
        join store_members m on m.member_id = q.member_id and m.store_id = q.store_id
        join users u on u.user_id = m.user_id
        where q.store_id = $1
          and q.status = $2
        order by q.created_at asc
        """,
        store_id,
        status,
    )
    return {
        "store_id": store_id,
        "status": status,
        "items": [
            {
                "question_id": int(r["question_id"]),
                "question_text": r["question_text"],
                "miss_reason": r["miss_reason"],
                "status": r["status"],
                "member_id": int(r["member_id"]),
                "asked_by": r["asked_by"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }
