"""관호 (feat/db) — 지식 등록 · 검색 게이트.

인증된 회원만 공유 검색 서비스를 사용한다.
레거시 응답 형식을 유지하며 요청 store_id는 JWT 매장 안에서만 대조한다:
  요청  { store_id, question, top_k }
  hit  → { kind: "hit",  candidates: [{ id, content, category, score }] }
  miss → { kind: "miss", reason: "no_match"|"intent_mismatch"|"no_anchor", message }
miss 면 LLM 을 호출하지 않는다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.deps import CurrentStoreId, Db
from app.reg.retrieve import retrieve_question

router = APIRouter()


class RetrieveRequest(BaseModel):
    store_id: str | int
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/retrieve")
async def retrieve(req: RetrieveRequest, store_id: CurrentStoreId, db: Db):
    """검색 게이트. hit/miss 만 판정한다. miss 면 LLM 호출 금지."""
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is empty")

    await _check_requested_store(db, store_id, req.store_id)
    result = await retrieve_question(db, store_id, question, req.top_k)

    if result["kind"] == "miss":
        return {
            "kind": "miss",
            "reason": result["reason"],
            "message": result["message"],
        }

    return {
        "kind": "hit",
        "candidates": [
            {
                "id": c["id"],
                "content": c["content"],
                "category": c["category"],
                "score": c["score"],
            }
            for c in result["candidates"]
        ],
    }


@router.get("/cards")
async def list_cards(store_id: str | int, current_store_id: CurrentStoreId, db: Db):
    """매장 승인 카드 목록. store_id 는 slug 또는 BIGINT."""
    await _check_requested_store(db, current_store_id, store_id)
    sid = current_store_id
    rows = await db.fetch(
        """
        select
          c.card_id as id,
          v.title,
          v.content,
          coalesce(tc.category_name, '') as category,
          c.confidence,
          c.is_verified
        from knowledge_cards c
        join card_versions v on v.version_id = c.published_version_id
          and v.card_id = c.card_id and v.store_id = c.store_id
        left join task_categories tc on tc.category_id = c.category_id and tc.store_id = c.store_id
        where c.store_id = $1
          and c.is_verified = true
          and c.review_status = 'APPROVED'
        order by c.card_id
        """,
        sid,
    )
    return {
        "store_id": sid,
        "cards": [
            {
                "id": int(r["id"]),
                "title": r["title"],
                "content": r["content"],
                "category": r["category"],
                "confidence": float(r["confidence"]),
                "is_verified": bool(r["is_verified"]),
            }
            for r in rows
        ],
    }


async def _check_requested_store(db: Db, store_id: int, requested: str | int) -> None:
    """레거시 slug는 현재 매장 안에서만 대조하고 타 매장 존재를 조회하지 않는다."""
    row = await db.fetchrow(
        "select store_id from stores where store_id = $1 and (store_id::text = $2 or store_slug = $2)",
        store_id, str(requested),
    )
    if not row:
        raise HTTPException(404, "store not found")
