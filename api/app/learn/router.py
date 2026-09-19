"""관호 (feat/db) — 미답변 순환 · 채팅 저장 · 로드맵.

miss 판정은 retrieve_question, 기록은 POST /pending 또는 POST /chat 이 한다.
점주 답변은 POST /pending/{id}/answer — 카드(승인) + 임베딩 + ANSWERED (가이드 6-4).
로드맵은 GET /roadmap (카드→칸 동기화) · PATCH 칸 상태 · progress_rate.
store_id 는 JWT 에서만 해석한다 (불변식 4).
"""
from __future__ import annotations

import json
import asyncio
from uuid import uuid4
from dataclasses import replace

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.cards.router import _evidence_items
from app.deps import Claims, CurrentStoreId, CurrentUserId, Db, get_pool, get_store_id
from app.errors import ApiError
from app.contracts.usage import UsageContext
from app.usage import DbUsageSink
from app.usage.repository import UsageWriteError
from app.learn.answer_usage import AnswerUsageStartError
from app.learn.request_limits import request_lease
from app.config import get_settings
from app.learn.answering import AnswerComposition, compose_grounded_answer
from app.learn.faq import list_faqs as list_faq_rows
from app.learn.knowledge_apply import (
    prepare_proposal,
    publish_existing_proposal,
    publish_new_proposal,
)
from app.learn.knowledge_loop import build_knowledge_plan
from app.learn import roadmap as roadmap_repo
from app.notifications.service import (
    create_pending_question_notification,
    deliver_notification,
)
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
from app.learn.v2_router import router as v2_router
router.include_router(v2_router)

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
          and contract_version = 'v1'
          and status = 'WAITING'
          and lower(regexp_replace(trim(question_text), '\\s+', ' ', 'g')) = $2
        order by created_at asc
        limit 1
        """,
        store_id,
        question,
    )


def _question_key(question: str) -> str:
    return " ".join(question.strip().lower().split())


async def _lock_pending_question_key(db: Db, store_id: int, question_key: str) -> None:
    """동시 요청도 같은 WAITING 질문을 두 번 만들지 않는다."""
    await db.execute(
        "select pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"askbuddy:pending:{store_id}:{question_key}",
    )


async def _record_pending_occurrence(
    db: Db,
    question_id: int,
    member_id: int,
    message_id: int | None,
    *, store_id: int,
) -> None:
    await db.execute(
        """
        insert into pending_question_occurrences (question_id, member_id, message_id)
        select $1, $2, $3
        from pending_questions q
        join store_members m on m.member_id=$2 and m.store_id=q.store_id
        where q.question_id=$1 and q.store_id=$4
          and ($3::bigint is null or exists (
            select 1 from chat_messages cm join chat_sessions cs on cs.session_id=cm.session_id
            where cm.message_id=$3 and cs.store_id=$4 and cs.member_id=$2))
        on conflict do nothing
        """,
        question_id,
        member_id,
        message_id,
        store_id,
    )


async def _citations_are_current(
    db: Db,
    store_id: int,
    composition: AnswerComposition,
) -> bool:
    """검색 후 공개 상태가 바뀐 카드를 답변에 쓰지 않도록 행을 잠근다."""
    expected = {
        int(card["id"]): int(card["version_id"]) for card in composition.candidates
    }
    if not expected or len(expected) != len(composition.candidates):
        return False
    rows = await db.fetch(
        """
        select card_id, published_version_id
        from knowledge_cards
        where store_id = $1
          and card_id = any($2::bigint[])
          and review_status = 'APPROVED'
          and is_verified = true
          and published_version_id is not null
        order by card_id
        for share
        """,
        store_id,
        list(expected),
    )
    actual = {int(row["card_id"]): int(row["published_version_id"]) for row in rows}
    return actual == expected


class _StaleChatKnowledge(Exception):
    """현재 공개본 검증 실패. pending을 만드는 지식 miss와 구분한다."""


async def _lock_chat_publication(db: Db, store_id: int) -> None:
    """W 발행과 같은 행을 먼저 잠근다. 외부 모델 호출 후 저장 트랜잭션 안에서만 사용."""
    await db.execute("""insert into knowledge_publications(store_id) values($1)
                        on conflict(store_id) do nothing""", store_id)
    await db.fetchrow("""select knowledge_revision from knowledge_publications
                         where store_id=$1 for share""", store_id)


@router.post("/pending")
async def require_v2_pending(req: CreatePendingRequest, claims: Claims, user_id: CurrentUserId):
    async with get_pool().acquire() as db:
        store_id = await get_store_id(claims, db)
        await _member_id(db, store_id, user_id)
    raise ApiError(409, "V2_REQUIRED", "새 질문은 새 Buddy 화면에서 확인해 주세요.",
                   details={"destination": "/staff/chat/v2"})


async def create_pending(
    req: CreatePendingRequest,
    background: BackgroundTasks,
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
              and s.member_id = $3 and s.contract_version = 'v1'
            """,
            req.message_id,
            store_id,
            member_id,
        )
        if not msg:
            raise HTTPException(404, "message not found in this store")

    question_key = _question_key(question)
    notification_id: int | None = None
    async with db.transaction():
        await _lock_pending_question_key(db, store_id, question_key)
        existing = await _waiting_same_question(db, store_id, question_key)
        if existing:
            await _record_pending_occurrence(
                db, int(existing["question_id"]), member_id, req.message_id, store_id=store_id
            )
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
        await _record_pending_occurrence(
            db, int(row["question_id"]), member_id, req.message_id, store_id=store_id
        )
        notification_id = await create_pending_question_notification(
            db, store_id, int(row["question_id"]), question
        )
    if notification_id is not None:
        background.add_task(deliver_notification, store_id, notification_id)
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
        select distinct on (q.normalized_question)
          q.question_id,
          q.question_text,
          q.miss_reason,
          q.status,
          q.created_at,
          q.member_id,
          u.name as asked_by,
          greatest(coalesce(occurrence.question_count, 0), 1) as question_count,
          greatest(coalesce(occurrence.questioner_count, 0), 1) as questioner_count
        from pending_questions q
        join store_members m on m.member_id = q.member_id and m.store_id = q.store_id
        join users u on u.user_id = m.user_id
        left join lateral (
          select count(*) as question_count,
                 count(distinct o.member_id) as questioner_count
          from pending_questions same_q
          join pending_question_occurrences o
            on o.question_id = same_q.question_id
          where same_q.store_id = q.store_id
            and same_q.contract_version = 'v1'
            and same_q.normalized_question = q.normalized_question
            and same_q.status = q.status
        ) occurrence on true
        where q.store_id = $1
          and q.contract_version = 'v1'
          and q.status = $2
        order by q.normalized_question, q.created_at asc, q.question_id asc
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
                "question_count": int(r["question_count"]),
                "questioner_count": int(r["questioner_count"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/pending/{question_id}")
async def get_pending(
    question_id: int,
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
):
    """알림 딥링크가 가리키는 질문의 현재 상태를 매장 범위 안에서 확인한다."""
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")
    row = await db.fetchrow(
        """
        select q.question_id, q.question_text, q.miss_reason, q.status, q.created_at,
               u.name as asked_by, a.answer_text, a.answered_at
        from pending_questions q
        join store_members m on m.member_id = q.member_id and m.store_id = q.store_id
        join users u on u.user_id = m.user_id
        left join owner_answers a on a.question_id = q.question_id
        where q.store_id = $1 and q.question_id = $2
          and q.contract_version = 'v1'
        """,
        store_id,
        question_id,
    )
    if row is None:
        raise HTTPException(404, "pending question not found")
    return {
        "question_id": int(row["question_id"]),
        "question_text": row["question_text"],
        "miss_reason": row["miss_reason"],
        "status": row["status"],
        "asked_by": row["asked_by"],
        "answer_text": row["answer_text"],
        "answered_at": _iso(row["answered_at"]) or None,
        "created_at": _iso(row["created_at"]),
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
         and s.contract_version = 'v1'
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
         and pq.contract_version = 'v1'
         and pq.message_id = um.message_id
        left join owner_answers oa_direct
          on oa_direct.question_id = pq.question_id
        left join lateral (
          select a.answer_text, a.answered_at
          from pending_questions q
          join owner_answers a on a.question_id = q.question_id
          where q.store_id = $1
            and q.contract_version = 'v1'
            and trim(q.question_text) = trim(um.content)
          order by a.answered_at desc
          limit 1
        ) oa_match on oa_direct.answer_text is null
        left join lateral (
          select question_id
          from pending_questions
          where store_id = $1
            and contract_version = 'v1'
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
    """점주 원문은 즉시 전달하고 카드 반영은 관계별 안전 정책으로 분리한다."""
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
          and contract_version = 'v1'
        """,
        question_id,
        store_id,
    )
    if not pending:
        raise HTTPException(404, "pending question not found")
    if pending["status"] != "WAITING":
        raise HTTPException(409, "already answered")

    plan = await build_knowledge_plan(
        db, store_id, pending["question_text"].strip(), answer
    )
    question_key = _question_key(pending["question_text"])

    async with db.transaction():
        await _lock_pending_question_key(db, store_id, question_key)
        locked = await db.fetchrow(
            """
            select question_id, status
            from pending_questions
            where store_id = $1 and question_id = $2
              and contract_version = 'v1'
            for update
            """,
            store_id,
            question_id,
        )
        if locked is None:
            raise HTTPException(404, "pending question not found")
        if locked["status"] != "WAITING":
            raise HTTPException(409, "already answered")

        target_is_current = True
        if plan.target_card_id is not None:
            target = await db.fetchrow(
                """
                select published_version_id, review_status, is_verified
                from knowledge_cards
                where store_id = $1 and card_id = $2
                for share
                """,
                store_id,
                plan.target_card_id,
            )
            target_is_current = bool(
                target
                and target["review_status"] == "APPROVED"
                and target["is_verified"]
                and target["published_version_id"] == plan.target_version_id
            )
            if not target_is_current:
                plan = replace(
                    plan,
                    relation_type="CONFLICT",
                    auto_publish=False,
                    reason=f"{plan.reason}; 분석 이후 대상 카드 상태 또는 버전 변경",
                )

        askers = await db.fetch(
            """
            select distinct occurrence.member_id
            from pending_questions q
            join pending_question_occurrences occurrence
              on occurrence.question_id = q.question_id
            where q.store_id = $1 and q.status = 'WAITING'
              and q.contract_version = 'v1'
              and q.normalized_question = $2
            """,
            store_id,
            question_key,
        )
        answer_id = int(
            await db.fetchval(
                """
                insert into owner_answers (question_id, answered_by, answer_text)
                values ($1, $2, $3)
                returning answer_id
                """,
                question_id,
                user_id,
                answer,
            )
        )
        if plan.relation_type == "IDENTICAL" and target_is_current:
            proposal_status = "LINKED"
        elif plan.relation_type == "NEW" and plan.auto_publish:
            proposal_status = "ANALYZED"
        else:
            proposal_status = "PENDING_REVIEW"

        proposal_id = int(
            await db.fetchval(
                """
                insert into knowledge_change_proposals (
                  store_id, answer_id, relation_type,
                  target_card_id, target_version_id, category_id,
                  proposed_title, proposed_content, reason, status, resolved_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::varchar,
                          case when $10::varchar = 'LINKED' then now() else null end)
                returning proposal_id
                """,
                store_id,
                answer_id,
                plan.relation_type,
                plan.target_card_id,
                plan.target_version_id,
                plan.category_id,
                plan.proposed_title,
                plan.proposed_content,
                plan.reason,
                proposal_status,
            )
        )
        if proposal_status == "LINKED":
            await db.execute(
                "update owner_answers set card_id = $2 where answer_id = $1",
                answer_id,
                plan.target_card_id,
            )
        elif plan.target_card_id is not None:
            await db.execute(
                """
                update knowledge_cards
                set needs_review_reason = $3
                where store_id = $1 and card_id = $2
                  and review_status <> 'EXCLUDED'
                """,
                store_id,
                plan.target_card_id,
                f"OWNER_ANSWER_{plan.relation_type}",
            )

        await db.execute(
            """
            update pending_questions set status = 'ANSWERED'
            where store_id = $1 and status = 'WAITING'
              and contract_version = 'v1'
              and normalized_question = $2
            """,
            store_id,
            question_key,
        )

        buddy_content = f"사장님이 답해주셨어요.\n\n{answer}"
        for asker in askers:
            session_id = await _open_session(db, store_id, int(asker["member_id"]))
            buddy_id = int(
                await db.fetchval(
                    """
                    insert into chat_messages (
                      session_id, sender_type, content, answer_type,
                      answer_source, grounding_status, owner_answer_id
                    ) values ($1, 'BUDDY', $2, 'ANSWERED',
                              'OWNER_ANSWER', 'NOT_APPLICABLE', $3)
                    returning message_id
                    """,
                    session_id,
                    buddy_content,
                    answer_id,
                )
            )
            if proposal_status == "LINKED":
                await db.execute(
                    """
                    insert into message_citations (
                      message_id, card_id, version_id, relevance
                    ) values ($1, $2, $3, 100.00)
                    """,
                    buddy_id,
                    plan.target_card_id,
                    plan.target_version_id,
                )

    card_id = plan.target_card_id if proposal_status == "LINKED" else None
    version_id = plan.target_version_id if proposal_status == "LINKED" else None
    knowledge_status = proposal_status
    if proposal_status == "ANALYZED":
        try:
            preparation = await prepare_proposal(db, store_id, proposal_id)
            async with db.transaction():
                card_id, version_id = await publish_new_proposal(
                    db, store_id, proposal_id, user_id, preparation=preparation
                )
            knowledge_status = "PUBLISHED"
        except Exception as exc:
            await db.execute(
                """
                update knowledge_change_proposals
                set status = 'FAILED', error = $3::jsonb
                where store_id = $1 and proposal_id = $2
                """,
                store_id,
                proposal_id,
                json.dumps({"message": str(exc)[:500]}, ensure_ascii=False),
            )
            knowledge_status = "FAILED"

    return {
        "question_id": question_id,
        "status": "ANSWERED",
        "card_id": card_id,
        "version_id": version_id,
        "answer_text": answer,
        "knowledge": {
            "proposal_id": proposal_id,
            "relation_type": plan.relation_type,
            "status": knowledge_status,
            "category_id": plan.category_id,
            "category_name": plan.category_name,
            "requires_review": knowledge_status in ("PENDING_REVIEW", "FAILED"),
        },
    }


@router.get("/knowledge-proposals")
async def list_knowledge_proposals(
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    status: str = Query(
        default="PENDING_REVIEW",
        pattern="^(ANALYZED|LINKED|PENDING_REVIEW|PUBLISHED|FAILED|DISMISSED)$",
    ),
):
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")
    rows = await db.fetch(
        """
        select p.*, q.question_text, a.answer_text,
               current_v.title as current_title, current_v.content as current_content
        from knowledge_change_proposals p
        join owner_answers a on a.answer_id = p.answer_id
        join pending_questions q on q.question_id = a.question_id
        left join card_versions current_v on current_v.version_id = p.target_version_id
        where p.store_id = $1 and p.status = $2
        order by p.created_at desc, p.proposal_id desc
        """,
        store_id,
        status,
    )
    return {
        "store_id": store_id,
        "status": status,
        "items": [
            {
                "proposal_id": int(row["proposal_id"]),
                "relation_type": row["relation_type"],
                "status": row["status"],
                "question_text": row["question_text"],
                "answer_text": row["answer_text"],
                "target_card_id": int(row["target_card_id"])
                if row["target_card_id"] is not None
                else None,
                "target_version_id": int(row["target_version_id"])
                if row["target_version_id"] is not None
                else None,
                "current_title": row["current_title"],
                "current_content": row["current_content"],
                "proposed_title": row["proposed_title"],
                "proposed_content": row["proposed_content"],
                "reason": row["reason"],
                "category_id": int(row["category_id"]),
                "created_at": _iso(row["created_at"]),
            }
            for row in rows
        ],
    }


@router.post("/knowledge-proposals/{proposal_id}/approve")
async def approve_knowledge_proposal(
    proposal_id: int,
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
    user_id: CurrentUserId,
):
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")
    relation = await db.fetchval(
        """
        select relation_type from knowledge_change_proposals
        where store_id = $1 and proposal_id = $2
        """,
        store_id,
        proposal_id,
    )
    if relation is None:
        raise HTTPException(404, "knowledge proposal not found")
    try:
        preparation = await prepare_proposal(db, store_id, proposal_id)
        async with db.transaction():
            if relation == "NEW":
                card_id, version_id = await publish_new_proposal(
                    db, store_id, proposal_id, user_id, preparation=preparation
                )
            else:
                card_id, version_id = await publish_existing_proposal(
                    db, store_id, proposal_id, user_id, preparation=preparation
                )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "proposal_id": proposal_id,
        "status": "PUBLISHED",
        "card_id": card_id,
        "version_id": version_id,
    }


@router.post("/knowledge-proposals/{proposal_id}/dismiss")
async def dismiss_knowledge_proposal(
    proposal_id: int,
    db: Db,
    claims: Claims,
    store_id: CurrentStoreId,
):
    if claims.get("role") != "OWNER":
        raise HTTPException(403, "owner only")
    async with db.transaction():
        proposal = await db.fetchrow(
            """
            select target_card_id, status from knowledge_change_proposals
            where store_id = $1 and proposal_id = $2 for update
            """,
            store_id,
            proposal_id,
        )
        if proposal is None:
            raise HTTPException(404, "knowledge proposal not found")
        if proposal["status"] not in ("PENDING_REVIEW", "FAILED"):
            raise HTTPException(409, "proposal cannot be dismissed")
        await db.execute(
            """
            update knowledge_change_proposals
            set status = 'DISMISSED', resolved_at = now()
            where store_id = $1 and proposal_id = $2
            """,
            store_id,
            proposal_id,
        )
        if proposal["target_card_id"] is not None:
            await db.execute(
                """
                update knowledge_cards k set needs_review_reason = null
                where k.store_id = $1 and k.card_id = $2
                  and k.needs_review_reason like 'OWNER_ANSWER_%'
                  and not exists (
                    select 1 from knowledge_change_proposals p
                    where p.store_id = $1 and p.target_card_id = $2
                      and p.status = 'PENDING_REVIEW'
                  )
                """,
                store_id,
                int(proposal["target_card_id"]),
            )
    return {"proposal_id": proposal_id, "status": "DISMISSED"}


@router.get("/faqs")
async def get_faqs(
    db: Db,
    store_id: CurrentStoreId,
    min_questions: int = Query(default=2, ge=1, le=100),
    limit: int = Query(default=20, ge=1, le=100),
):
    items = await list_faq_rows(
        db, store_id, min_questions=min_questions, limit=limit
    )
    return {
        "store_id": store_id,
        "items": [
            {
                **item,
                "last_asked_at": _iso(item["last_asked_at"]),
            }
            for item in items
        ],
    }


async def _open_session(db: Db, store_id: int, member_id: int) -> int:
    """이 멤버의 열린 세션. 없으면 하나 만든다."""
    row = await db.fetchrow(
        """
        select session_id
        from chat_sessions
        where store_id = $1 and member_id = $2 and contract_version = 'v1'
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
async def ask_chat(req: ChatAskRequest, claims: Claims, user_id: CurrentUserId):
    async with get_pool().acquire() as db:
        store_id = await get_store_id(claims, db)
        await _member_id(db, store_id, user_id)
    raise ApiError(409, "V2_REQUIRED", "새 질문은 새 Buddy 화면에서 확인해 주세요.",
                   details={"destination": "/staff/chat/v2"})


async def legacy_chat_regression(req: ChatAskRequest, background: BackgroundTasks, claims: Claims, user_id: CurrentUserId):
    """Unrouted legacy regression fixture. Never mount in the product application."""
    deadline = asyncio.get_running_loop().time() + get_settings().chat_deadline_seconds
    completed_response = None
    attempt_state = {"stale": False}
    try:
        async with asyncio.timeout_at(deadline):
            pool = get_pool()
            async with pool.acquire() as db:
                store_id = await get_store_id(claims, db)
            async with request_lease(pool, store_id, user_id):
                completed_response = await _ask_chat(req, background, claims, user_id, deadline=deadline,
                                                     attempt_state=attempt_state)
            return completed_response
    except TimeoutError as exc:
        # 저장을 마친 뒤 lease 정리가 취소되어도 저장 성공을 retryable 실패로 바꾸지 않는다.
        if completed_response is not None:
            return completed_response
        if attempt_state["stale"]:
            raise ApiError(409, "STALE_KNOWLEDGE", "변경된 내용을 확인할 시간이 부족합니다. 다시 질문해 주세요.", retryable=True) from exc
        raise ApiError(504, "DEADLINE_EXCEEDED", "답변 처리 시간이 초과되었습니다.", retryable=True) from exc
    except UsageWriteError as exc:
        raise ApiError(503, "USAGE_UNAVAILABLE", "검색 계측을 시작하지 못했습니다.", retryable=True) from exc


async def _ask_chat(
    req: ChatAskRequest,
    background: BackgroundTasks,
    claims: Claims,
    user_id: CurrentUserId,
    *, deadline: float, attempt_state: dict | None = None,
):
    """검색 게이트 → 근거 제한 생성/원문 폴백 → 대화·citation 원자 저장."""
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is empty")

    pool = get_pool()
    async with pool.acquire() as db:
        store_id = await get_store_id(claims, db)
        member_id = await _member_id(db, store_id, user_id)
    operation_id = uuid4().hex
    loop = asyncio.get_running_loop()
    settings = get_settings()
    model_started = loop.time()
    for requery in range(2):
        try:
            result, composition = await _search_and_compose_chat(
                pool, store_id, question, operation_id=operation_id,
                model_started=model_started, deadline=deadline, requery=requery)
            # 공개 변경으로 사라진 근거를 지식 부족의 pending으로 바꾸지 않는다.
            if requery and composition is None:
                raise _StaleChatKnowledge()
            return await _save_chat_response(
                pool, store_id, user_id, claims, background, question, result, composition)
        except _StaleChatKnowledge:
            if attempt_state is not None:
                attempt_state["stale"] = True
            if requery == 0 and min(deadline-loop.time()-settings.chat_save_reserve_seconds,
                                    settings.llm_total_budget_seconds-(loop.time()-model_started)) > 0:
                continue
            raise ApiError(409, "STALE_KNOWLEDGE", "승인된 내용이 변경됐습니다. 다시 질문해 주세요.", retryable=True)
        except TimeoutError:
            if requery:
                raise ApiError(409, "STALE_KNOWLEDGE", "변경된 내용을 확인할 시간이 부족합니다. 다시 질문해 주세요.", retryable=True)
            raise
    raise AssertionError("unreachable")


async def _search_and_compose_chat(pool, store_id: int, question: str, *,
                                   operation_id: str, model_started: float,
                                   deadline: float, requery: int):
    loop = asyncio.get_running_loop()
    settings = get_settings()
    # stale 재검색은 새 질문 계획이지 공급자 오류 재시도가 아니다. 시도별 원장을 분리한다.
    call_scope = f"chat:{operation_id}" + (f":stale:{requery}" if requery else "")
    search_budget = min(settings.search_deadline_seconds, deadline-loop.time()-settings.chat_save_reserve_seconds)
    search_budget = min(search_budget, settings.llm_total_budget_seconds-(loop.time()-model_started))
    if search_budget <= 0:
        raise TimeoutError()
    result = await asyncio.wait_for(retrieve_question(pool, store_id, question, usage_sink=DbUsageSink(pool),
        usage_context=UsageContext(store_id=str(store_id), cost_phase="OPERATING",
            cost_purpose="PRODUCT", stage="QUERY", operation_id=operation_id,
            logical_call_id=f"{call_scope}:query")), timeout=search_budget)
    answer_budget = min(settings.answer_deadline_seconds,
                        settings.llm_total_budget_seconds-(loop.time()-model_started),
                        deadline-loop.time()-settings.chat_save_reserve_seconds)
    if result["kind"] == "hit" and answer_budget <= 0:
        raise TimeoutError()
    try:
        composition = (
            await asyncio.wait_for(compose_grounded_answer(
                question, result["candidates"], usage_sink=DbUsageSink(pool),
                usage_context=UsageContext(
                    store_id=str(store_id), cost_phase="OPERATING", cost_purpose="PRODUCT",
                    stage="ANSWER", operation_id=operation_id,
                    logical_call_id=f"{call_scope}:answer")), timeout=answer_budget)
            if result["kind"] == "hit" else None
        )
    except AnswerUsageStartError as exc:
        raise ApiError(503, "USAGE_UNAVAILABLE", "답변 계측을 시작하지 못했습니다.",
                       retryable=True) from exc
    return result, composition


async def _save_chat_response(pool, store_id: int, user_id: int, claims, background,
                              question: str, result: dict, composition):
    notification_id: int | None = None
    async with pool.acquire() as db:
        # 외부 호출 중 탈퇴/권한 변경이 있었으면 대화를 저장하지 않는다.
        await get_store_id(claims, db)
        member_id = await _member_id(db, store_id, user_id)
        async with db.transaction():
            await _lock_chat_publication(db, store_id)
            if composition is not None and not await _citations_are_current(db, store_id, composition):
                raise _StaleChatKnowledge()
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

            use_hit = composition is not None
            if use_hit:
                assert composition is not None
                buddy_content = composition.content
                buddy_id = int(
                    await db.fetchval(
                        """
                        insert into chat_messages (
                          session_id, sender_type, content, answer_type,
                          answer_source, grounding_status
                        )
                        values ($1, 'BUDDY', $2, 'ANSWERED', $3, $4)
                        returning message_id
                        """,
                        session_id,
                        buddy_content,
                        composition.source,
                        composition.grounding_status,
                    )
                )
                for card in composition.candidates:
                    relevance = round(float(card["score"]) * 100, 2)
                    await db.execute(
                        """
                        insert into message_citations (
                          message_id, card_id, version_id, relevance
                        )
                        values ($1, $2, $3, $4)
                        """,
                        buddy_id,
                        card["id"],
                        card["version_id"],
                        relevance,
                    )
                    citations.append(
                        {
                            "card_id": card["id"],
                            "version_id": card["version_id"],
                            "title": card["title"] or card["category"],
                            "relevance": relevance,
                        }
                    )
                answer_type = "ANSWERED"
                answer_source = composition.source
                grounding_status = composition.grounding_status
            else:
                buddy_content = "아직 확인된 내용이 없어요. 사장님께 확인 중이에요 🙏"
                buddy_id = int(
                    await db.fetchval(
                        """
                        insert into chat_messages (
                          session_id, sender_type, content, answer_type,
                          answer_source, grounding_status
                        )
                        values ($1, 'BUDDY', $2, 'NO_ANSWER',
                                'MISS', 'NOT_APPLICABLE')
                        returning message_id
                        """,
                        session_id,
                        buddy_content,
                    )
                )
                question_key = _question_key(question[:500])
                await _lock_pending_question_key(db, store_id, question_key)
                pending_row = await _waiting_same_question(db, store_id, question_key)
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
                            result.get("reason", "no_match"),
                            )
                        )
                    notification_id = await create_pending_question_notification(
                        db, store_id, pending_question_id, question[:500]
                    )
                await _record_pending_occurrence(
                    db, pending_question_id, member_id, user_message_id, store_id=store_id
                )
                answer_type = "NO_ANSWER"
                answer_source = "MISS"
                grounding_status = "NOT_APPLICABLE"
    if notification_id is not None:
        background.add_task(deliver_notification, store_id, notification_id)

    return {
        "session_id": session_id,
        "user_message_id": user_message_id,
        "buddy": {
            "message_id": buddy_id,
            "answer_type": answer_type,
            "content": buddy_content,
            "answer_source": answer_source,
            "grounding_status": grounding_status,
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
        where store_id = $1 and member_id = $2 and contract_version = 'v1'
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
          m.answer_source,
          m.grounding_status,
          m.created_at,
          c.card_id,
          c.version_id,
          c.relevance,
          coalesce(cv.title, kc.title) as card_title,
          (
            kc.review_status = 'APPROVED'
            and kc.is_verified = true
            and kc.published_version_id = c.version_id
          ) as is_current
        from chat_messages m
        left join message_citations c on c.message_id = m.message_id
        left join knowledge_cards kc
          on kc.card_id = c.card_id and kc.store_id = $2
        left join card_versions cv
          on cv.version_id = c.version_id and cv.store_id = $2
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
                "answer_source": r["answer_source"],
                "grounding_status": r["grounding_status"],
                "created_at": _iso(r["created_at"]),
                "citations": [],
            }
            by_id[mid] = msg
            messages.append(msg)
        if r["card_id"] is not None:
            msg["citations"].append(
                {
                    "card_id": int(r["card_id"]),
                    "version_id": int(r["version_id"]) if r["version_id"] is not None else None,
                    "title": r["card_title"] or "",
                    "relevance": float(r["relevance"]) if r["relevance"] is not None else 0,
                    "is_current": bool(r["is_current"]),
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
