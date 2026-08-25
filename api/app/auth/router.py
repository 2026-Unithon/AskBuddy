"""관호 (feat/db) — 가입 · 로그인 · 초대코드 합류.

main.py 는 이 파일의 router 만 import 한다. 엔드포인트는 여기 안에서 자유롭게 추가한다.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/login")
async def login():
    raise HTTPException(501, "not implemented — 관호 (feat/db)")


@router.post("/signup")
async def signup():
    raise HTTPException(501, "not implemented — 관호 (feat/db)")


@router.post("/join")
async def join():
    """초대코드로 매장 합류 → store_members."""
    raise HTTPException(501, "not implemented — 관호 (feat/db)")
