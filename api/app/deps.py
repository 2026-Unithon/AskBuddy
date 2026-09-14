"""공용 — DB 세션과 JWT. 수정 전 팀 합의 (CLAUDE.md 폴더 소유권).

RLS 를 쓰지 않으므로(D1) 매장 격리는 전적으로 이 파일의 store_id 가 책임진다.
요청 본문의 store_id 를 신뢰하지 않는다. 아래 CurrentStoreId 만 신뢰한다.
"""
from typing import Annotated, Any, AsyncIterator
import re

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException

from app.config import get_settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(get_settings().supabase_db_url, min_size=1, max_size=10)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """백그라운드 작업용. 요청 커넥션이 닫힌 뒤에도 풀에서 직접 얻는다."""
    if _pool is None:
        raise RuntimeError("db pool not initialized")
    return _pool


async def get_db() -> AsyncIterator[asyncpg.Connection]:
    if _pool is None:
        raise HTTPException(503, "db pool not initialized")
    async with _pool.acquire() as conn:
        yield conn


Db = Annotated[asyncpg.Connection, Depends(get_db)]


# ── JWT ────────────────────────────────────────────────────────────────────

def create_token(payload: dict[str, Any]) -> str:
    s = get_settings()
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


async def get_claims(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    s = get_settings()
    try:
        return jwt.decode(authorization[7:], s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, "invalid token") from e


Claims = Annotated[dict[str, Any], Depends(get_claims)]


def _claim_id(claims: dict[str, Any], name: str) -> int:
    value = claims.get(name)
    if type(value) not in (str, int) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise HTTPException(403, "invalid identity")
    value = int(value)
    if value > 9223372036854775807:
        raise HTTPException(403, "invalid identity")
    return value


# store-isolation-ok: store_id를 JWT에서 확정하는 인증 경계이며 조회에 반드시 사용한다.
async def get_store_id(claims: Claims, db: Db) -> int:
    """모든 조회의 선행 조건. 기본값도 Optional 도 두지 않는다."""
    store_id = _claim_id(claims, "store_id")
    user_id = _claim_id(claims, "user_id")
    member = await db.fetchrow(
        "select member_role from store_members where store_id = $1 and user_id = $2",
        store_id, user_id,
    )
    if not member or member["member_role"] not in ("OWNER", "STAFF") or member["member_role"] != claims.get("role"):
        raise HTTPException(403, "current membership required")
    return store_id


async def get_user_id(claims: Claims) -> int:
    return _claim_id(claims, "user_id")


CurrentStoreId = Annotated[int, Depends(get_store_id)]
CurrentUserId = Annotated[int, Depends(get_user_id)]
