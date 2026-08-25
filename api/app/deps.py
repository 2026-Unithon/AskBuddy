"""공용 — DB 세션과 JWT. 수정 전 팀 합의 (CLAUDE.md 폴더 소유권).

RLS 를 쓰지 않으므로(D1) 매장 격리는 전적으로 이 파일의 store_id 가 책임진다.
요청 본문의 store_id 를 신뢰하지 않는다. 아래 CurrentStoreId 만 신뢰한다.
"""
from typing import Annotated, Any, AsyncIterator

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
        return jwt.decode(authorization[7:], s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}") from e


Claims = Annotated[dict[str, Any], Depends(get_claims)]


async def get_store_id(claims: Claims) -> int:
    """모든 조회의 선행 조건. 기본값도 Optional 도 두지 않는다."""
    store_id = claims.get("store_id")
    if store_id is None:
        raise HTTPException(403, "token has no store_id")
    return int(store_id)


async def get_user_id(claims: Claims) -> int:
    user_id = claims.get("user_id")
    if user_id is None:
        raise HTTPException(403, "token has no user_id")
    return int(user_id)


CurrentStoreId = Annotated[int, Depends(get_store_id)]
CurrentUserId = Annotated[int, Depends(get_user_id)]


# ── store_slug → store_id ──────────────────────────────────────────────────

async def resolve_store_id(db: asyncpg.Connection, raw: str | int) -> int:
    """기존 API 계약의 문자열 store_id("demo-cafe")를 BIGINT 로 해석한다.
    진입점에서 한 번만 호출한다."""
    if isinstance(raw, int) or str(raw).isdigit():
        return int(raw)
    row = await db.fetchrow("select store_id from stores where store_slug = $1", str(raw))
    if not row:
        raise HTTPException(404, f"unknown store: {raw}")
    return int(row["store_id"])
