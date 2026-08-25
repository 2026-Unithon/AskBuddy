"""관호 (feat/db) — 지식 등록 · 검색 게이트.

지식 진입점은 POST /reg/retrieve 하나다 (불변식 3).
계약 (변경 금지):
  요청  { store_id, question, top_k }
  hit  → { kind: "hit",  candidates: [{ id, content, category, score }] }
  miss → { kind: "miss", reason: "no_match"|"intent_mismatch"|"no_anchor", message }
miss 면 LLM 을 호출하지 않는다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class RetrieveRequest(BaseModel):
    store_id: str | int
    question: str
    top_k: int = 5


@router.post("/retrieve")
async def retrieve(req: RetrieveRequest):
    raise HTTPException(501, "not implemented — 관호 (feat/db)")


@router.get("/cards")
async def list_cards():
    raise HTTPException(501, "not implemented — 관호 (feat/db)")
