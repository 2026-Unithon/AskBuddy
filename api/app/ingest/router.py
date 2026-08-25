"""준혁 (feat/input) — 멀티모달 전처리 · 추출 · 임베딩 적재.

상태 머신: UPLOADED → PROCESSING → DONE | FAILED (FAILED 는 error_message 필수)
프론트는 GET /ingest/status 를 2초 간격 폴링한다 (D6).
파일 바이너리를 받지 않는다. Storage 경로 문자열만 받는다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ProcessRequest(BaseModel):
    source_id: int


@router.post("/process")
async def process(req: ProcessRequest):
    raise HTTPException(501, "not implemented — 준혁 (feat/input)")


@router.get("/status")
async def status(source_id: int):
    raise HTTPException(501, "not implemented — 준혁 (feat/input)")
