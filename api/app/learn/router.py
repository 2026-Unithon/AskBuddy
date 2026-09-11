"""관호 (feat/db) — 미답변 순환 · 채팅 저장 · 로드맵.

miss 판정은 retrieve_question, 기록은 POST /pending 또는 POST /chat 이 한다.
점주 답변은 POST /pending/{id}/answer — 카드(승인) + 임베딩 + ANSWERED (가이드 6-4).
로드맵은 GET /roadmap (카드→칸 동기화) · PATCH 칸 상태 · progress_rate.
store_id 는 JWT 에서만 해석한다 (불변식 4).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.cards.router import _evidence_items
from app.deps import Claims, CurrentStoreId, CurrentUserId, Db
from app.errors import ApiError
from app.ingest.embed import embed_card
from app.learn import roadmap as roadmap_repo
from app.learn.schemas import (
    CompletionRequest,
    CompletionResult,
    LearnItemDetail,
    RoadmapCounts,
    RoadmapItem,
    RoadmapResponse,
    RoadmapStage,
    RoadmapStore,
)
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


class PatchRoadmapItemRequest(BaseModel):
    status: str = Field(pattern="^(LOCKED|IN_PROGRESS|DONE)$")


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


async def _waiting_same_question(db: Db, store_id: int, question: str):
    """매장 + 같은 문장 + WAITING 이면 기존 쪽지. B: 중복 INSERT 금지."""
    return await db.fetchrow(
        """
        select question_id, status, miss_reason, created_at, member_id
        from pending_questions
        where store_id = $1
          and status = 'WAITING'
          and trim(question_text) = $2
        order by created_at asc
        limit 1
        """,
        store_id,
        question,
    )


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

    existing = await _waiting_same_question(db, store_id, question)
    if existing:
        return {
            "question_id": int(existing["question_id"]),
            "status": existing["status"],
            "miss_reason": existing["miss_reason"],
            "question_text": question,
            "created_at": existing["created_at"].isoformat(),
        }

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
        select distinct on (q.question_text)
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
        order by q.question_text, q.created_at asc, q.question_id asc
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


@router.get("/staff")
async def list_staff(
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
):
    """점주 대시보드 직원 목록. STAFF 만. store_id 는 JWT.

    StaffLevel 은 DB 컬럼이 아니다. progress_rate 와 deploy_threshold 를 내려 프론트가 나눈다.
    """
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")

    store = await db.fetchrow(
        """
        select deploy_threshold
        from stores
        where store_id = $1
        """,
        store_id,
    )
    if not store:
        raise HTTPException(404, "store not found")
    threshold = int(store["deploy_threshold"])

    rows = await db.fetch(
        """
        select
          m.member_id,
          u.name,
          m.day_count,
          m.progress_rate,
          m.is_deployable
        from store_members m
        join users u on u.user_id = m.user_id
        where m.store_id = $1
          and m.member_role = 'STAFF'
        order by m.joined_at asc, m.member_id asc
        """,
        store_id,
    )
    return {
        "store_id": store_id,
        "deploy_threshold": threshold,
        "items": [
            {
                "member_id": int(r["member_id"]),
                "name": r["name"],
                "day_count": int(r["day_count"]),
                "progress_rate": float(r["progress_rate"]),
                "is_deployable": bool(r["is_deployable"]),
            }
            for r in rows
        ],
    }


@router.get("/questions")
async def list_questions(
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    limit: int = Query(default=100, ge=1, le=200),
):
    """점주용 매장 전체 질문. 알바가 물은 USER 메시지 + 그에 대한 답, 최신순.

    대기(miss)만 보지 않는다. 지식 hit · 점주 답 · 아직 대기 중을 한 목록에 둔다.
    문장이 다르면 별도 행이다. DISTINCT 로 묶지 않는다.
    """
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")

    rows = await db.fetch(
        """
        select
          um.message_id,
          um.content as question_text,
          um.created_at,
          u.name as asked_by,
          sm.member_id,
          bm.content as buddy_content,
          bm.answer_type as buddy_answer_type,
          case
            when pq.status = 'WAITING' then pq.question_id
            else waiting.question_id
          end as waiting_question_id,
          coalesce(oa_direct.answer_text, oa_match.answer_text) as owner_answer,
          coalesce(oa_direct.answered_at, oa_match.answered_at) as answered_at
        from chat_messages um
        join chat_sessions s
          on s.session_id = um.session_id
         and s.store_id = $1
        join store_members sm
          on sm.member_id = s.member_id
         and sm.store_id = s.store_id
        join users u on u.user_id = sm.user_id
        left join lateral (
          select content, answer_type
          from chat_messages
          where session_id = um.session_id
            and sender_type = 'BUDDY'
            and message_id > um.message_id
          order by message_id asc
          limit 1
        ) bm on true
        left join pending_questions pq
          on pq.store_id = $1
         and pq.message_id = um.message_id
        left join owner_answers oa_direct
          on oa_direct.question_id = pq.question_id
        left join lateral (
          select a.answer_text, a.answered_at
          from pending_questions q
          join owner_answers a on a.question_id = q.question_id
          where q.store_id = $1
            and trim(q.question_text) = trim(um.content)
          order by a.answered_at desc
          limit 1
        ) oa_match on oa_direct.answer_text is null
        left join lateral (
          select question_id
          from pending_questions
          where store_id = $1
            and status = 'WAITING'
            and trim(question_text) = trim(um.content)
          order by created_at desc, question_id desc
          limit 1
        ) waiting on true
        where um.sender_type = 'USER'
        order by um.created_at desc, um.message_id desc
        limit $2
        """,
        store_id,
        limit,
    )

    items: list[dict] = []
    for r in rows:
        owner_answer = r["owner_answer"]
        buddy_type = r["buddy_answer_type"]
        waiting_id = r["waiting_question_id"]
        if owner_answer:
            status = "OWNER_ANSWERED"
            answer_text = owner_answer
        elif buddy_type == "ANSWERED":
            status = "HIT"
            answer_text = r["buddy_content"]
        else:
            status = "WAITING"
            answer_text = None
        items.append(
            {
                "message_id": int(r["message_id"]),
                "question_text": r["question_text"],
                "asked_by": r["asked_by"],
                "member_id": int(r["member_id"]),
                "status": status,
                "answer_text": answer_text,
                "waiting_question_id": int(waiting_id) if waiting_id is not None else None,
                "answered_at": _iso(r["answered_at"]) or None,
                "created_at": _iso(r["created_at"]),
            }
        )

    return {"store_id": store_id, "items": items}


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
        select question_id, question_text, status, category_id, member_id
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

            askers = await db.fetch(
                """
                select distinct member_id
                from pending_questions
                where store_id = $1
                  and status = 'WAITING'
                  and trim(question_text) = $2
                """,
                store_id,
                pending["question_text"].strip(),
            )

            await db.execute(
                """
                update pending_questions
                set status = 'ANSWERED'
                where store_id = $1
                  and status = 'WAITING'
                  and trim(question_text) = $2
                """,
                store_id,
                pending["question_text"].strip(),
            )

            # 옛 「확인 중」은 남기고, 같은 질문을 한 알바 채팅에 답을 한 줄 보낸다 (A′).
            buddy_content = f"사장님이 답해주셨어요.\n\n{answer}"
            for asker in askers:
                session_id = await _open_session(db, store_id, int(asker["member_id"]))
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
                await db.execute(
                    """
                    insert into message_citations (message_id, card_id, relevance)
                    values ($1, $2, 100.00)
                    """,
                    buddy_id,
                    card_id,
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
            pending_row = await _waiting_same_question(db, store_id, question[:500])
            if pending_row:
                pending_question_id = int(pending_row["question_id"])
            else:
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


@router.get("/roadmap", response_model=RoadmapResponse)
async def get_roadmap(
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
) -> RoadmapResponse:
    """현재 승인 카드만 카테고리별로 묶고, 강제 잠금 없이 실제 완료를 계산한다."""
    member_id = await _member_id(db, store_id, user_id)
    store = await db.fetchrow(
        "select store_id, store_name from stores where store_id = $1", store_id
    )
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND", "접근할 수 있는 매장이 없습니다.")
    rows = await roadmap_repo.roadmap_rows(db, store_id, member_id)
    stages: list[RoadmapStage] = []
    by_category: dict[int, RoadmapStage] = {}
    done = 0
    reconfirm = 0
    continue_reconfirm: int | None = None
    continue_new: int | None = None
    for r in rows:
        category_id = int(r["category_id"])
        stage = by_category.get(category_id)
        if stage is None:
            stage = RoadmapStage(
                category_id=category_id,
                name=r["category_name"],
                order=int(r["sort_order"]),
                items=[],
            )
            by_category[category_id] = stage
            stages.append(stage)
        item_status = roadmap_repo.learning_status(
            r["progress_status"], r["completed_version_id"], r["published_version_id"]
        )
        item_id = int(r["item_id"])
        stage.items.append(
            RoadmapItem(
                item_id=item_id,
                card_id=int(r["card_id"]),
                published_version_id=int(r["published_version_id"]),
                title=r["title"],
                status=item_status,
            )
        )
        if item_status == "DONE":
            done += 1
        elif item_status == "RECONFIRM_REQUIRED":
            reconfirm += 1
            continue_reconfirm = continue_reconfirm or item_id
        else:
            continue_new = continue_new or item_id

    summary = {"total": len(rows), "done": done, "reconfirm_required": reconfirm}
    return RoadmapResponse(
        store=RoadmapStore(store_id=store_id, name=store["store_name"]),
        counts=RoadmapCounts(**summary),
        continue_item_id=continue_reconfirm or continue_new,
        stages=stages,
    )


@router.get("/items/{item_id}", response_model=LearnItemDetail)
async def get_roadmap_item(
    item_id: int,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
) -> LearnItemDetail:
    member_id = await _member_id(db, store_id, user_id)
    row = await roadmap_repo.item_row(db, store_id, member_id, item_id)
    if row is None:
        raise ApiError(404, "LEARN_ITEM_NOT_FOUND", "학습 항목을 찾을 수 없습니다.")
    version_id = int(row["published_version_id"])
    return LearnItemDetail(
        item_id=item_id,
        card_id=int(row["card_id"]),
        published_version_id=version_id,
        title=row["title"],
        content=row["content"],
        status=roadmap_repo.learning_status(
            row["progress_status"], row["completed_version_id"], version_id
        ),
        category={
            "category_id": int(row["category_id"]),
            "name": row["category_name"],
        },
        evidence=await _evidence_items(db, store_id, version_id),
        return_to={"path": "/staff/roadmap", "item_id": item_id},
    )


@router.put("/items/{item_id}/completion", response_model=CompletionResult)
async def put_roadmap_completion(
    item_id: int,
    req: CompletionRequest,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
) -> CompletionResult:
    member_id = await _member_id(db, store_id, user_id)
    async with db.transaction():
        item = await roadmap_repo.set_completion(
            db,
            store_id,
            member_id,
            item_id,
            published_version_id=req.published_version_id,
            completed=req.completed,
        )
        if item is None:
            raise ApiError(404, "LEARN_ITEM_NOT_FOUND", "학습 항목을 찾을 수 없습니다.")
        current_version_id = int(item["published_version_id"])
        if current_version_id != req.published_version_id:
            raise ApiError(
                409,
                "LEARN_VERSION_CONFLICT",
                "학습 내용이 변경되었습니다. 최신 내용을 다시 확인해 주세요.",
                details={"current_published_version_id": current_version_id},
            )
        summary = await roadmap_repo.counts(db, store_id, member_id)
        await roadmap_repo.update_member_rate(db, store_id, member_id, summary)
    return CompletionResult(
        item_id=item_id,
        card_id=int(item["card_id"]),
        published_version_id=current_version_id,
        status="DONE" if req.completed else "NOT_STARTED",
        counts=RoadmapCounts(**summary),
    )


@router.patch("/roadmap/items/{item_id}")
async def patch_roadmap_item(
    item_id: int,
    req: PatchRoadmapItemRequest,
    db: Db,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
):
    """기존 잠금형 요청을 새 완료 API로 연결하는 호환 어댑터."""
    member_id = await _member_id(db, store_id, user_id)
    item = await roadmap_repo.item_row(db, store_id, member_id, item_id)
    if not item:
        raise HTTPException(404, "roadmap item not found")

    async with db.transaction():
        await roadmap_repo.set_completion(
            db,
            store_id,
            member_id,
            item_id,
            published_version_id=int(item["published_version_id"]),
            completed=req.status == "DONE",
        )
        summary = await roadmap_repo.counts(db, store_id, member_id)
        rate = await roadmap_repo.update_member_rate(db, store_id, member_id, summary)

    return {
        "item_id": item_id,
        "status": req.status,
        "progress_rate": rate,
    }
