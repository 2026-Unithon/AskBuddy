"""관호 (feat/db) — 미답변 순환 · 채팅 저장.

miss 판정은 retrieve_question, 기록은 POST /pending 또는 POST /chat 이 한다.
점주 답변은 POST /pending/{id}/answer — 카드(승인) + 임베딩 + ANSWERED (가이드 6-4).
store_id 는 JWT 에서만 해석한다 (불변식 4).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import Claims, CurrentStoreId, CurrentUserId, Db
from app.ingest.embed import embed_card
from app.reg.retrieve import retrieve_question

router = APIRouter()

_TITLE_MAX = 200


class CreatePendingRequest(BaseModel):
    question_text: str = Field(min_length=1, max_length=500)
    miss_reason: str = Field(pattern="^(no_match|intent_mismatch|no_anchor)$")
    message_id: int | None = None


class AnswerPendingRequest(BaseModel):
    answer_text: str = Field(min_length=1, max_length=4000)


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


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


@router.post("/pending/{question_id}/answer")
async def answer_pending(
    question_id: int,
    req: AnswerPendingRequest,
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
):
    """점주 답변 → 지식 카드(is_verified=true) + 임베딩 + WAITING→ANSWERED.

    점주 답은 검수 없이 바로 검색 노출 (가이드 6-4).
    """
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")

    answer = req.answer_text.strip()
    if not answer:
        raise HTTPException(400, "answer_text is empty")

    pending = await db.fetchrow(
        """
        select question_id, question_text, status, category_id
        from pending_questions
        where question_id = $1
          and store_id = $2
        """,
        question_id,
        store_id,
    )
    if not pending:
        raise HTTPException(404, "pending question not found")
    if pending["status"] != "WAITING":
        raise HTTPException(409, "already answered")

    title = pending["question_text"][:_TITLE_MAX]

    try:
        async with db.transaction():
            card_id = await db.fetchval(
                """
                insert into knowledge_cards (
                  store_id, category_id, source_id, title, content,
                  confidence, is_verified
                )
                values ($1, $2, null, $3, $4, 100.00, true)
                returning card_id
                """,
                store_id,
                pending["category_id"],
                title,
                answer,
            )
            card_id = int(card_id)

            await db.execute(
                """
                insert into owner_answers (
                  question_id, answered_by, answer_text, card_id
                )
                values ($1, $2, $3, $4)
                """,
                question_id,
                user_id,
                answer,
                card_id,
            )

            # 승인된 카드만 embed_card 가 받는다. 같은 커넥션·트랜잭션에서 적재.
            await embed_card(db, store_id, card_id)

            await db.execute(
                """
                update pending_questions
                set status = 'ANSWERED'
                where question_id = $1
                  and store_id = $2
                  and status = 'WAITING'
                """,
                question_id,
                store_id,
            )
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e

    return {
        "question_id": question_id,
        "status": "ANSWERED",
        "card_id": card_id,
        "answer_text": answer,
    }


async def _open_session(db: Db, store_id: int, member_id: int) -> int:
    """이 멤버의 열린 세션. 없으면 하나 만든다."""
    row = await db.fetchrow(
        """
        select session_id
        from chat_sessions
        where store_id = $1 and member_id = $2
        order by started_at desc
        limit 1
        """,
        store_id,
        member_id,
    )
    if row:
        return int(row["session_id"])
    session_id = await db.fetchval(
        """
        insert into chat_sessions (store_id, member_id)
        values ($1, $2)
        returning session_id
        """,
        store_id,
        member_id,
    )
    return int(session_id)


def _iso(value) -> str:
    return value.isoformat() if value is not None else ""


@router.post("/chat")
async def ask_chat(
    req: ChatAskRequest,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
):
    """신입 질문 한 방: 검색 → 대화 저장 → miss 면 pending 까지.

    hit 1차: 상위 카드 content 를 Buddy 문장으로 쓰고 citation 을 남긴다 (LLM 없음).
    miss: LLM 호출 없음. NO_ANSWER + pending WAITING.
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is empty")

    member_id = await _member_id(db, store_id, user_id)
    result = await retrieve_question(db, store_id, question)

    async with db.transaction():
        session_id = await _open_session(db, store_id, member_id)
        user_message_id = int(
            await db.fetchval(
                """
                insert into chat_messages (session_id, sender_type, content)
                values ($1, 'USER', $2)
                returning message_id
                """,
                session_id,
                question,
            )
        )

        pending_question_id = None
        citations: list[dict] = []

        if result["kind"] == "hit":
            top = result["candidates"][0]
            buddy_content = top["content"]
            buddy_id = int(
                await db.fetchval(
                    """
                    insert into chat_messages (
                      session_id, sender_type, content, answer_type
                    )
                    values ($1, 'BUDDY', $2, 'ANSWERED')
                    returning message_id
                    """,
                    session_id,
                    buddy_content,
                )
            )
            # ANSWERED 인데 citation 0건이면 계약 위반. 상위 후보를 반드시 남긴다.
            relevance = round(float(top["score"]) * 100, 2)
            await db.execute(
                """
                insert into message_citations (message_id, card_id, relevance)
                values ($1, $2, $3)
                """,
                buddy_id,
                top["id"],
                relevance,
            )
            citations = [
                {
                    "card_id": top["id"],
                    "title": top["title"] or top["category"],
                    "relevance": relevance,
                }
            ]
            answer_type = "ANSWERED"
        else:
            buddy_content = "아직 확인된 내용이 없어요. 사장님께 확인 중이에요 🙏"
            buddy_id = int(
                await db.fetchval(
                    """
                    insert into chat_messages (
                      session_id, sender_type, content, answer_type
                    )
                    values ($1, 'BUDDY', $2, 'NO_ANSWER')
                    returning message_id
                    """,
                    session_id,
                    buddy_content,
                )
            )
            pending_question_id = int(
                await db.fetchval(
                    """
                    insert into pending_questions (
                      store_id, member_id, message_id,
                      question_text, miss_reason, status
                    )
                    values ($1, $2, $3, $4, $5, 'WAITING')
                    returning question_id
                    """,
                    store_id,
                    member_id,
                    user_message_id,
                    question[:500],
                    result["reason"],
                )
            )
            answer_type = "NO_ANSWER"

    return {
        "session_id": session_id,
        "user_message_id": user_message_id,
        "buddy": {
            "message_id": buddy_id,
            "answer_type": answer_type,
            "content": buddy_content,
            "citations": citations,
        },
        "pending_question_id": pending_question_id,
    }


@router.get("/chat")
async def list_chat(
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
):
    """이 멤버의 최근 세션 메시지. 새로고침 검증용."""
    member_id = await _member_id(db, store_id, user_id)
    session = await db.fetchrow(
        """
        select session_id, started_at
        from chat_sessions
        where store_id = $1 and member_id = $2
        order by started_at desc
        limit 1
        """,
        store_id,
        member_id,
    )
    if not session:
        return {"session_id": None, "messages": []}

    session_id = int(session["session_id"])
    rows = await db.fetch(
        """
        select
          m.message_id,
          m.sender_type,
          m.content,
          m.answer_type,
          m.created_at,
          c.card_id,
          c.relevance,
          kc.title as card_title
        from chat_messages m
        left join message_citations c on c.message_id = m.message_id
        left join knowledge_cards kc
          on kc.card_id = c.card_id and kc.store_id = $2
        where m.session_id = $1
        order by m.created_at asc, m.message_id asc, c.citation_id asc
        """,
        session_id,
        store_id,
    )

    messages: list[dict] = []
    by_id: dict[int, dict] = {}
    for r in rows:
        mid = int(r["message_id"])
        msg = by_id.get(mid)
        if msg is None:
            msg = {
                "message_id": mid,
                "sender_type": r["sender_type"],
                "content": r["content"],
                "answer_type": r["answer_type"],
                "created_at": _iso(r["created_at"]),
                "citations": [],
            }
            by_id[mid] = msg
            messages.append(msg)
        if r["card_id"] is not None:
            msg["citations"].append(
                {
                    "card_id": int(r["card_id"]),
                    "title": r["card_title"] or "",
                    "relevance": float(r["relevance"]) if r["relevance"] is not None else 0,
                }
            )

    return {
        "session_id": session_id,
        "started_at": _iso(session["started_at"]),
        "messages": messages,
    }
