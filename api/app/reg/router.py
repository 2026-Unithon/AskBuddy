"""관호 (feat/db) — 지식 등록 · 검색 게이트.

지식 진입점은 POST /reg/retrieve 하나다 (불변식 3).
계약 (변경 금지):
  요청  { store_id, question, top_k }
  hit  → { kind: "hit",  candidates: [{ id, content, category, score }] }
  miss → { kind: "miss", reason: "no_match"|"intent_mismatch"|"no_anchor", message }
miss 면 LLM 을 호출하지 않는다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.deps import Db, resolve_store_id
from app.reg.embeddings import embed_text, vector_literal

router = APIRouter()

MISS_MESSAGE = "사장님께 확인 중"


class RetrieveRequest(BaseModel):
    store_id: str | int
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/retrieve")
async def retrieve(req: RetrieveRequest, db: Db):
    """검색 게이트. hit/miss 만 판정한다. miss 면 LLM 호출 금지."""
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is empty")

    # 골든셋·프론트 계약: 본문의 store_id(문자열 slug)를 진입점에서 한 번만 BIGINT 로 변환
    store_id = await resolve_store_id(db, req.store_id)
    settings = get_settings()

    # 질문 앵커가 너무 짧으면 no_anchor
    if len(question) < 2:
        return {
            "kind": "miss",
            "reason": "no_anchor",
            "message": MISS_MESSAGE,
        }

    query_vec = embed_text(question)
    rows = await db.fetch(
        """
        select
          m.card_id as id,
          m.content,
          coalesce(tc.category_name, '') as category,
          m.score
        from match_cards($1, $2::vector, $3) m
        join knowledge_cards c on c.card_id = m.card_id
        left join task_categories tc on tc.category_id = c.category_id
        where c.store_id = $1
        order by m.score desc
        """,
        store_id,
        vector_literal(query_vec),
        req.top_k,
    )

    # D11: 검색 hit/miss 는 retrieval_threshold. confidence_threshold(D3)는 검수용
    threshold = settings.retrieval_threshold
    candidates = [
        {
            "id": int(r["id"]),
            "content": r["content"],
            "category": r["category"],
            "score": float(r["score"]),
        }
        for r in rows
        if float(r["score"]) >= threshold
    ]

    if not candidates:
        return {
            "kind": "miss",
            "reason": "no_match",
            "message": MISS_MESSAGE,
        }

    return {"kind": "hit", "candidates": candidates}


@router.get("/cards")
async def list_cards(store_id: str | int, db: Db):
    """매장 승인 카드 목록. store_id 는 slug 또는 BIGINT."""
    sid = await resolve_store_id(db, store_id)
    rows = await db.fetch(
        """
        select
          c.card_id as id,
          c.title,
          c.content,
          coalesce(tc.category_name, '') as category,
          c.confidence,
          c.is_verified
        from knowledge_cards c
        left join task_categories tc on tc.category_id = c.category_id
        where c.store_id = $1
          and c.is_verified = true
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
