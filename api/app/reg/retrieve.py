"""검색 게이트 판정. /reg/retrieve 와 /learn/chat 이 같은 함수를 쓴다.

공개 JSON 계약은 바꾸지 않는다. 내부 후보는 title 을 더 실어 citation 에 쓴다.
"""
from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from app.config import get_settings
from app.reg.embeddings import embed_text, vector_literal

MISS_MESSAGE = "사장님께 확인 중"


async def retrieve_question(
    db: asyncpg.Connection,
    store_id: int,
    question: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """hit/miss 만 판정한다. miss 면 LLM 을 부르지 않는다."""
    question = question.strip()
    if len(question) < 2:
        return {
            "kind": "miss",
            "reason": "no_anchor",
            "message": MISS_MESSAGE,
            "candidates": [],
        }

    query_vec = await asyncio.to_thread(embed_text, question)
    rows = await db.fetch(
        """
        select
          m.card_id as id,
          m.content,
          m.title,
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
        top_k,
    )

    threshold = get_settings().retrieval_threshold
    candidates = [
        {
            "id": int(r["id"]),
            "content": r["content"],
            "title": r["title"] or "",
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
            "candidates": [],
        }

    return {"kind": "hit", "candidates": candidates}
